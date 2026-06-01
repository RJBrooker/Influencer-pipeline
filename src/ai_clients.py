"""
src/ai_clients.py

This file handles all direct communication with the AI APIs (Google Gemini and Fal.ai/Veo). 
If you ever want to change how prompts are structured, how the AI models are called, 
or swap out Gemini for another AI model in the future, this is the file to edit.
"""

import asyncio

import fal_client
import httpx
from google import genai
from google.genai import types
from prefect import task, get_run_logger

from src.config import BatchParameters, PromptInputs, settings
from .cost_tracker import CostTracker


def get_gemini_client() -> genai.Client:
    if not settings:
        raise ValueError("Settings not loaded.")
    return genai.Client(api_key=settings.gemini_api_key)


@task(retries=3, retry_delay_seconds=10)
async def generate_base_image(params: BatchParameters, inputs: PromptInputs, tracker: CostTracker) -> bytes:
    """
    Calls the Gemini API to generate the very first 'Base' image for a video batch.
    Uses the initial image prompt and any additional instructions from the Google Sheet.
    Returns the raw image bytes.
    """
    logger = get_run_logger()
    client = get_gemini_client()
    logger.info(f"Generating base image using {params.image.model}")
    full_prompt = (
        f"{inputs.initial_image_prompt}\n\nEnsure the image is generated in a {params.image.aspect_ratio} aspect ratio."
    )

    response = await client.aio.models.generate_content(
        model=params.image.model,
        contents=full_prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"], temperature=params.text.temperature),
    )

    # Track cost
    tracker.add_image()
    # Image models don't return token counts in the same way, we just track the image generated.

    return response.candidates[0].content.parts[0].inline_data.data


@task(retries=3, retry_delay_seconds=5)
async def generate_video_prompt(
    params: BatchParameters, inputs: PromptInputs, image_prompt: str, tracker: CostTracker
) -> str:
    """
    Takes a static image prompt and asks Gemini to rewrite it into a dynamic video prompt.
    It applies any 'Additional Video Instructions' the user provided in the Google Sheet.
    Returns the newly generated video prompt string.
    """
    logger = get_run_logger()
    client = get_gemini_client()
    logger.info("Generating video prompt via Gemini")
    instruction = f"""
    You are an expert AI video prompt engineer. Convert the following static image prompt into a dynamic video generation prompt.
    Incorporate these additional instructions: {inputs.additional_video_instructions}
    
    Image Prompt:
    {image_prompt}
    
    Return ONLY the video prompt text. Do not include any conversational filler.
    """
    response = await client.aio.models.generate_content(
        model=params.text.model,
        contents=instruction,
        config=types.GenerateContentConfig(temperature=params.text.temperature),
    )

    # Track text tokens
    if response.usage_metadata:
        tracker.add_tokens(response.usage_metadata.prompt_token_count, response.usage_metadata.candidates_token_count)

    return response.text.strip()


@task(retries=3, retry_delay_seconds=5)
async def generate_modified_prompts(
    params: BatchParameters, inputs: PromptInputs, location: str, base_image_prompt: str, tracker: CostTracker
) -> tuple[str, str]:
    """
    Takes the original base image prompt and asks Gemini to adapt it for a new specific location.
    It guarantees the core subjects remain the same, but changes the background.
    After creating the new image prompt, it also generates the matching video prompt.
    Returns a tuple of (new_image_prompt, new_video_prompt).
    """
    logger = get_run_logger()
    client = get_gemini_client()
    logger.info(f"Writing modified prompts for: {location}")

    # 1. Rewrite Image Prompt
    img_prompt_req = f"""
    You are an expert AI prompt engineer. I have a base image prompt. 
    Rewrite it so the subjects, camera angle, and lighting remain EXACTLY the same, but change the background location to: {location}.
    Additional instructions: {inputs.additional_image_instructions}
    
    Base Prompt: {base_image_prompt}
    
    Return ONLY the new image prompt text. Do not include any conversational filler.
    """

    # Using gather to run both prompts concurrently could be done, but they depend on each other.
    img_response = await client.aio.models.generate_content(
        model=params.text.model,
        contents=img_prompt_req,
        config=types.GenerateContentConfig(temperature=params.text.temperature),
    )
    new_image_prompt = img_response.text.strip()
    if img_response.usage_metadata:
        tracker.add_tokens(
            img_response.usage_metadata.prompt_token_count, img_response.usage_metadata.candidates_token_count
        )

    # 2. Rewrite Video Prompt
    vid_prompt_req = f"""
    Convert the following static image prompt into a dynamic video POV prompt.
    The location is {location}. Describe the motion, physics, and wind.
    Additional instructions: {inputs.additional_video_instructions}
    
    Image Prompt: {new_image_prompt}
    
    Return ONLY the new video prompt text. Do not include any conversational filler.
    """
    vid_response = await client.aio.models.generate_content(
        model=params.text.model,
        contents=vid_prompt_req,
        config=types.GenerateContentConfig(temperature=params.text.temperature),
    )
    new_video_prompt = vid_response.text.strip()
    if vid_response.usage_metadata:
        tracker.add_tokens(
            vid_response.usage_metadata.prompt_token_count, vid_response.usage_metadata.candidates_token_count
        )

    return new_image_prompt, new_video_prompt


@task(retries=3, retry_delay_seconds=10)
async def generate_location_image(
    params: BatchParameters, location: str, new_img_prompt: str, orig_image_bytes: bytes, tracker: CostTracker
) -> bytes:
    """
    Generates a new image based on a reference image (the base image) for a specific location.
    The new image uses the reference for character consistency while applying the new location prompt.
    Returns the raw image bytes.
    """
    logger = get_run_logger()
    client = get_gemini_client()
    logger.info(f"Generating location image for {location} using {params.image.model}")
    image_part = types.Part.from_bytes(data=orig_image_bytes, mime_type="image/jpeg")
    full_prompt = f"Use the attached image as a strict character and style reference. {new_img_prompt}\n\nEnsure the image is generated in a {params.image.aspect_ratio} aspect ratio."

    response = await client.aio.models.generate_content(
        model=params.image.model,
        contents=[image_part, full_prompt],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"], temperature=params.text.temperature),
    )

    tracker.add_image()
    return response.candidates[0].content.parts[0].inline_data.data


@task(retries=2, retry_delay_seconds=30)
async def generate_video(
    params: BatchParameters, video_prompt: str, image_path: str, output_path: str, tracker: CostTracker
) -> None:
    """
    Calls the Fal.ai API (using the Veo or Hunyuan models) to generate a video.
    It uploads the static image, passes the dynamic video prompt, and waits for the generation to complete.
    Once finished, it downloads the resulting .mp4 file and saves it to the specified output_path.
    """
    logger = get_run_logger()
    client = get_gemini_client()
    logger.info(f"Generating video using {params.video.model} for {output_path}")

    if "fal-ai" in params.video.model:
        if not settings.fal_key:
            raise ValueError("FAL_KEY environment variable is missing but a fal.ai model was selected.")

        # fal_client is currently synchronous, so we run it in a thread pool to not block asyncio
        logger.info("Uploading image to Fal.ai...")
        uploaded_image_url = await asyncio.to_thread(fal_client.upload_file, image_path)

        logger.info("Generating video via Fal.ai...")
        result = await asyncio.to_thread(
            fal_client.subscribe,
            params.video.model,
            arguments={"prompt": video_prompt, "image_url": uploaded_image_url},
        )

        video_url = result.get("video", {}).get("url")
        if not video_url:
            raise RuntimeError("Fal.ai generation failed or returned no video URL.")

        logger.info(f"Downloading video from Fal.ai for {output_path}...")
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(video_url)
            response.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(response.content)

        tracker.add_video()

    else:
        # Veo pipeline (Async)
        operation = await client.aio.models.generate_videos(
            model=params.video.model,
            prompt=video_prompt,
            image=types.Image.from_file(location=image_path),
            config=types.GenerateVideosConfig(aspect_ratio=params.video.aspect_ratio, person_generation="allow_adult"),
        )

        logger.info(f"Waiting for Veo video generation to complete for {output_path}...")
        attempts = 0
        while not operation.done:
            attempts += 1
            if attempts % 2 == 0:  # Log every 30 seconds to avoid spamming too much, but show we are alive
                logger.info(f"⏳ Still generating... (Ping #{attempts}: Veo API indicates 'done: False')")
            await asyncio.sleep(15)  # Replaces time.sleep(15) allowing concurrency
            operation = await client.aio.operations.get(operation=operation)

        response = getattr(operation, "result", None) or getattr(operation, "response", None)
        if response and response.generated_videos:
            generated_video = response.generated_videos[0]
            logger.info(f"Downloading video from Veo for {output_path}...")
            # client.files.download is sync, we could run in thread or async wrapper
            await asyncio.to_thread(client.files.download, file=generated_video.video)
            await asyncio.to_thread(generated_video.video.save, output_path)
            tracker.add_video()
        else:
            raise RuntimeError("Veo video generation failed or returned no videos.")
