"""
src/config.py

This file defines the data structures and settings for the entire project. 
It maps your local `.env` variables (like API keys) to the codebase, and defines 
the standard pricing structures used by the CostTracker.
"""

from typing import Dict, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Standard Pricing Constants (Adjust as necessary)
PRICING: Dict[str, Dict[str, float]] = {
    "gemini-2.5-flash": {"input_per_1m": 0.075, "output_per_1m": 0.30},
    "gemini-3.1-pro-preview": {"input_per_1m": 1.25, "output_per_1m": 5.00},
    "gemini-3.0-pro-image": {"per_image": 0.03},
    "veo-3.1-generate-preview": {"per_video": 0.05},
    "fal-ai/hunyuan-video": {"per_video": 0.04},
}


class PipelineSettings(BaseSettings):
    """
    Loads secrets from environment variables or .env file.
    """

    gemini_api_key: str = Field(..., env="GEMINI_API_KEY")
    spreadsheet_id: Optional[str] = Field(None, env="SPREADSHEET_ID")
    google_credentials_path: str = Field(..., env="GOOGLE_CREDENTIALS_PATH")
    google_token_path: str = Field(..., env="GOOGLE_TOKEN_PATH")
    fal_key: Optional[str] = Field(None, env="FAL_KEY")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class TextSettings(BaseModel):
    model: str = "gemini-3.1-pro-preview"
    temperature: float = 0.0


class ImageSettings(BaseModel):
    model: str = "gemini-3.0-pro-image"
    aspect_ratio: str = "9:16"


class VideoSettings(BaseModel):
    model: str = "veo-3.1-generate-preview"
    aspect_ratio: str = "9:16"
    duration_seconds: int = 4


class BatchParameters(BaseModel):
    """
    Represents the settings fetched from the Google Sheet 'PARAMETERS' tab.
    """

    text: TextSettings = TextSettings()
    image: ImageSettings = ImageSettings()
    video: VideoSettings = VideoSettings()


class PromptInputs(BaseModel):
    """
    Represents the inputs fetched from the Google Sheet 'PROMPT INPUTS' tab.
    """

    initial_image_prompt: str
    locations: list[str]
    additional_image_instructions: str = ""
    additional_video_instructions: str = ""
    initial_image_file: Optional[str] = None


# Global settings instance
try:
    settings = PipelineSettings()
except Exception as e:
    # Allow import without immediately crashing if .env isn't set up perfectly yet
    print(f"Warning: Failed to load PipelineSettings: {e}")
    settings = None
