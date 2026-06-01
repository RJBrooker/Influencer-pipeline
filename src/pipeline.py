"""
src/pipeline.py

This is the "Core Brain" of the application. It contains the business logic for the three main 
steps of the pipeline: generating the base scene, generating location variations, and 
generating the final videos in bulk. It acts as the orchestrator, pulling data from Google Sheets, 
calling the AI clients to generate media, and saving the outputs.
"""

import asyncio
import json
import os
import re

from loguru import logger
from prefect import flow

from src.ai_clients import (
    generate_base_image,
    generate_location_image,
    generate_modified_prompts,
    generate_video,
    generate_video_prompt,
)
from src.cost_tracker import CostTracker
from src.sheets import (
    fetch_inputs,
    fetch_parameters,
    get_outputs,
    get_sheets_client,
    update_output_row,
)


def sanitize_filename(name: str) -> str:
    """
    Takes an arbitrary string (like a location name) and cleans it up so it can be 
    safely used as a filename (e.g., converting spaces to underscores, removing special chars).
    """
    return re.sub(r"[^a-zA-Z0-9]", "_", name).strip("_").lower()[:30]


def ensure_project_dirs(project: str) -> tuple[str, str]:
    """
    Creates the necessary 'images' and 'videos' subdirectories inside the project's main folder.
    If they already exist, it does nothing. Returns the paths to both directories.
    """
    base_dir = os.path.join("projects", project)
    images_dir = os.path.join(base_dir, "images")
    videos_dir = os.path.join(base_dir, "videos")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(videos_dir, exist_ok=True)
    return images_dir, videos_dir


def load_project_config(project: str) -> str:
    """
    Reads the 'project_config.json' file located in the project's directory to retrieve 
    the specific Google Sheet ID tied to this batch of videos.
    """
    config_path = os.path.join("projects", project, "project_config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Project '{project}' not found or missing config! Run 'uv run python main_pipeline.py init' first.")
    
    with open(config_path, "r") as f:
        project_config = json.load(f)
        
    spreadsheet_id = project_config.get("spreadsheet_id")
    if not spreadsheet_id:
        raise ValueError(f"Project '{project}' is missing a spreadsheet_id in its config.")
        
    return spreadsheet_id


@flow(name="Step 1: Generate Base Scene")
async def generate_base_scene(project: str):
    """Step 1: Generates the initial base image and the base video prompt."""
    logger.info(f"🚀 Starting Step 1: Base Scene for Project '{project}'...")
    
    spreadsheet_id = load_project_config(project)
    images_dir, videos_dir = ensure_project_dirs(project)
    tracker = CostTracker()
    
    sheets_client = await asyncio.to_thread(get_sheets_client)
    params = await asyncio.to_thread(fetch_parameters, sheets_client, spreadsheet_id)
    inputs = await asyncio.to_thread(fetch_inputs, sheets_client, spreadsheet_id)
    outputs = await asyncio.to_thread(get_outputs, sheets_client, spreadsheet_id)
    
    tracker.text_model = params.text.model
    tracker.image_model = params.image.model
    tracker.video_model = params.video.model
    
    original_row = next((r for r in outputs if r.get("Project") == project and r.get("Type") == "Original"), None)
    
    base_image_file = inputs.initial_image_file
    base_video_prompt = original_row.get("Video Prompt") if original_row else None
    
    if not base_image_file or not os.path.exists(os.path.join(images_dir, base_image_file)):
        logger.info("🎨 Generating Initial Base Image...")
        base_image_bytes = await generate_base_image(params=params, inputs=inputs, tracker=tracker)
        base_image_file = "00_original_image.jpg"
        
        with open(os.path.join(images_dir, base_image_file), "wb") as f:
            f.write(base_image_bytes)
            
        row_data = {
            "Project": project, "Type": "Original", "Location": "N/A", "Image Input": "N/A",
            "Image Prompt": inputs.initial_image_prompt, "Video Prompt": "",
            "Image File": base_image_file, "Video File": ""
        }
        await asyncio.to_thread(update_output_row, sheets_client, spreadsheet_id, row_data, "Type", "Original", project)
    else:
        logger.info(f"✔️ Found existing Initial Image: {base_image_file}")
        
    if not base_video_prompt:
        logger.info("📝 Generating Initial Video Prompt...")
        base_video_prompt = await generate_video_prompt(
            params=params, inputs=inputs, image_prompt=inputs.initial_image_prompt, tracker=tracker
        )
        row_data = {
            "Project": project, "Type": "Original", "Location": "N/A", "Image Input": "N/A",
            "Image Prompt": inputs.initial_image_prompt, "Video Prompt": base_video_prompt,
            "Image File": base_image_file, "Video File": original_row.get("Video File", "") if original_row else ""
        }
        await asyncio.to_thread(update_output_row, sheets_client, spreadsheet_id, row_data, "Type", "Original", project)
    else:
         logger.info("✔️ Found existing Initial Video Prompt")

    logger.info("🛑 Base step completed. Review the image in your output folder before proceeding.")
    tracker.print_receipt()


async def _generate_single_location_image(i: int, location: str, inputs, params, outputs, orig_image_bytes, base_image_file, tracker, sheets_client, spreadsheet_id, project, images_dir):
    """
    Helper function for Step 2.
    For a single location, it generates the modified image/video prompts, then uses the AI 
    to generate the location-specific image. Finally, it logs the results to Google Sheets.
    """
    loc_row = next((r for r in outputs if r.get("Project") == project and r.get("Type") == "Location" and r.get("Location") == location), None)
    
    new_img_prompt = loc_row.get("Image Prompt") if loc_row else None
    new_vid_prompt = loc_row.get("Video Prompt") if loc_row else None
    loc_img_file = loc_row.get("Image File") if loc_row else None
    vid_file = loc_row.get("Video File") if loc_row else None
    
    if not new_img_prompt or not new_vid_prompt:
        new_img_prompt, new_vid_prompt = await generate_modified_prompts(
            params=params, inputs=inputs, location=location, base_image_prompt=inputs.initial_image_prompt, tracker=tracker
        )
        
    if not loc_img_file or not os.path.exists(os.path.join(images_dir, loc_img_file)):
        loc_img_file = f"{i:02d}_loc_{sanitize_filename(location)}.jpg"
        loc_img_bytes = await generate_location_image(
            params=params, location=location, new_img_prompt=new_img_prompt, orig_image_bytes=orig_image_bytes, tracker=tracker
        )
        with open(os.path.join(images_dir, loc_img_file), "wb") as f:
            f.write(loc_img_bytes)
            
        row_data = {
            "Project": project, "Type": "Location", "Location": location, "Image Input": base_image_file,
            "Image Prompt": new_img_prompt, "Video Prompt": new_vid_prompt,
            "Image File": loc_img_file, "Video File": vid_file or ""
        }
        await asyncio.to_thread(update_output_row, sheets_client, spreadsheet_id, row_data, "Location", location, project)
    else:
        logger.info(f"✔️ Found existing Image for {location}: {loc_img_file}")


@flow(name="Step 2: Generate Location Variations")
async def generate_location_variations(project: str, test_mode: bool = False):
    """Step 2: Generates modified prompts and images for each location."""
    logger.info(f"🚀 Starting Step 2: Location Variations for Project '{project}'...")
    if test_mode:
        logger.warning("🧪 TEST MODE ENABLED: Will only process 1 location.")
        
    spreadsheet_id = load_project_config(project)
    images_dir, videos_dir = ensure_project_dirs(project)
    tracker = CostTracker()
    
    sheets_client = await asyncio.to_thread(get_sheets_client)
    params = await asyncio.to_thread(fetch_parameters, sheets_client, spreadsheet_id)
    inputs = await asyncio.to_thread(fetch_inputs, sheets_client, spreadsheet_id)
    outputs = await asyncio.to_thread(get_outputs, sheets_client, spreadsheet_id)
    
    tracker.text_model = params.text.model
    tracker.image_model = params.image.model
    tracker.video_model = params.video.model
    
    original_row = next((r for r in outputs if r.get("Project") == project and r.get("Type") == "Original"), None)
    if not original_row or not original_row.get("Image File"):
        logger.error("❌ Base image not found in outputs! Please run 'run-base' first.")
        return
        
    base_image_file = original_row.get("Image File")
    with open(os.path.join(images_dir, base_image_file), "rb") as f:
        orig_image_bytes = f.read()

    locations_to_process = inputs.locations[:1] if test_mode else inputs.locations
    logger.info(f"🌍 Processing {len(locations_to_process)} location images concurrently...")
    
    tasks = []
    for i, location in enumerate(locations_to_process, start=1):
        tasks.append(_generate_single_location_image(
            i, location, inputs, params, outputs, orig_image_bytes, base_image_file, tracker, sheets_client, spreadsheet_id, project, images_dir
        ))
        
    await asyncio.gather(*tasks)
    logger.info("🛑 Location step completed. Review the location images before generating videos.")
    tracker.print_receipt()


async def _generate_single_video(location: str, loc_row: dict, params, tracker, sheets_client, spreadsheet_id, project, images_dir, videos_dir):
    """
    Helper function for Step 3.
    Takes a generated image and a video prompt, sends them to the video AI API (Veo/Fal), 
    waits for the .mp4 file, saves it locally, and updates the Google Sheet row.
    """
    vid_file = loc_row.get("Video File")
    loc_img_file = loc_row.get("Image File")
    vid_prompt = loc_row.get("Video Prompt")
    
    if not loc_img_file or not os.path.exists(os.path.join(images_dir, str(loc_img_file))):
        logger.warning(f"⚠️ Cannot generate video for {location} because image does not exist yet.")
        return

    if vid_file and vid_file != "N/A" and os.path.exists(os.path.join(videos_dir, vid_file)):
        logger.info(f"✔️ Found existing Video for {location}: {vid_file}")
        return
         
    if loc_img_file.lower().endswith(('.jpg', '.jpeg', '.png')):
        new_vid_file = loc_img_file.rsplit('.', 1)[0] + ".mp4"
    else:
        new_vid_file = loc_img_file + ".mp4"
        
    output_filepath = os.path.join(videos_dir, new_vid_file)
    
    await generate_video(
        params=params, video_prompt=vid_prompt, 
        image_path=os.path.join(images_dir, loc_img_file), 
        output_path=output_filepath, tracker=tracker
    )
    
    row_data = dict(loc_row)
    row_data["Video File"] = new_vid_file
    
    # We use Type "Original" if location is N/A (base video), otherwise "Location"
    match_col = "Type" if location == "N/A" else "Location"
    match_val = "Original" if location == "N/A" else location
    
    await asyncio.to_thread(update_output_row, sheets_client, spreadsheet_id, row_data, match_col, match_val, project)


@flow(name="Step 3: Generate Final Videos")
async def generate_final_videos(project: str, test_mode: bool = False):
    """Step 3: Generates Veo/Fal videos for all existing images."""
    logger.info(f"🚀 Starting Step 3: Video Generation for Project '{project}'...")
    if test_mode:
        logger.warning("🧪 TEST MODE ENABLED: Will only process 1 video.")
        
    spreadsheet_id = load_project_config(project)
    images_dir, videos_dir = ensure_project_dirs(project)
    tracker = CostTracker()
    
    sheets_client = await asyncio.to_thread(get_sheets_client)
    params = await asyncio.to_thread(fetch_parameters, sheets_client, spreadsheet_id)
    outputs = await asyncio.to_thread(get_outputs, sheets_client, spreadsheet_id)
    
    tracker.text_model = params.text.model
    tracker.image_model = params.image.model
    tracker.video_model = params.video.model
    
    project_rows = [r for r in outputs if r.get("Project") == project]
    
    rows_to_process = project_rows[:1] if test_mode else project_rows
    logger.info(f"🎬 Processing {len(rows_to_process)} video generations concurrently...")
    
    tasks = []
    for row in rows_to_process:
        location = row.get("Location", "N/A")
        tasks.append(_generate_single_video(
            location, row, params, tracker, sheets_client, spreadsheet_id, project, images_dir, videos_dir
        ))
        
    await asyncio.gather(*tasks)
    logger.info(f"🎉 Project '{project}' Final Videos Complete!")
    tracker.print_receipt()
