"""
src/sheets.py

This file handles all read and write operations to your Google Sheets. 
It fetches your input parameters and logs the outputs (like the locations of the 
generated images and videos) back into the "OUTPUTS" tab.
"""

import json
import os

import gspread
from google.oauth2.credentials import Credentials
from loguru import logger

from .config import settings, BatchParameters, PromptInputs, TextSettings, ImageSettings, VideoSettings

DEFAULTS_FILE = "defaults.json"


def get_sheets_client() -> gspread.Client:
    """Authenticates and returns a gspread client."""
    if not settings:
        raise ValueError("Settings not loaded.")

    creds = Credentials.from_authorized_user_file(
        settings.google_token_path, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)


def fetch_parameters(client: gspread.Client, spreadsheet_id: str) -> BatchParameters:
    """Fetches generation parameters from the PARAMETERS tab, caching them in defaults.json."""
    try:
        logger.info("Fetching parameters from Google Sheets...")
        doc = client.open_by_key(spreadsheet_id)
        
        try:
            sheet = doc.worksheet("PARAMETERS")
        except gspread.exceptions.WorksheetNotFound:
            logger.warning("PARAMETERS tab not found. Creating it with defaults.")
            sheet = doc.add_worksheet(title="PARAMETERS", rows=10, cols=2)
            
        records = sheet.get_all_records()
        
        defaults = BatchParameters()
        if not records:
            logger.info("Populating PARAMETERS tab with default values...")
            if not sheet.row_values(1):
                sheet.append_row(["Parameter", "Value"])
            sheet.append_rows([
                ["📝 Text Model", defaults.text.model],
                ["🌡️ Text Temperature", defaults.text.temperature],
                ["🖼️ Image Model", defaults.image.model],
                ["📐 Image Aspect Ratio", defaults.image.aspect_ratio],
                ["🎬 Video Model", defaults.video.model],
                ["📐 Video Aspect Ratio", defaults.video.aspect_ratio],
            ])
            records = sheet.get_all_records()

        params = {r.get("Parameter"): r.get("Value") for r in records}
        
        batch_params = BatchParameters(
            text=TextSettings(
                model=params.get("📝 Text Model") or defaults.text.model, 
                temperature=float(params.get("🌡️ Text Temperature") if params.get("🌡️ Text Temperature") not in [None, ""] else defaults.text.temperature)
            ),
            image=ImageSettings(
                model=params.get("🖼️ Image Model") or defaults.image.model, 
                aspect_ratio=params.get("📐 Image Aspect Ratio") or defaults.image.aspect_ratio
            ),
            video=VideoSettings(
                model=params.get("🎬 Video Model") or defaults.video.model, 
                aspect_ratio=params.get("📐 Video Aspect Ratio") or defaults.video.aspect_ratio
            )
        )
        
        # Save cache
        _update_defaults_cache("parameters", batch_params.model_dump())
        return batch_params

    except Exception as e:
        logger.error(f"Failed to fetch parameters from Google Sheets: {e}")
        logger.warning(f"Attempting to load fallback parameters from {DEFAULTS_FILE}...")
        return _load_fallback("parameters", BatchParameters)


def fetch_inputs(client: gspread.Client, spreadsheet_id: str) -> PromptInputs:
    """Fetches base prompts and locations from the PROMPT INPUTS tab, caching them in defaults.json."""
    try:
        logger.info("Fetching inputs from Google Sheets...")
        doc = client.open_by_key(spreadsheet_id)
        
        try:
            sheet = doc.worksheet("PROMPT INPUTS")
        except gspread.exceptions.WorksheetNotFound:
            logger.warning("PROMPT INPUTS tab not found. Creating it with defaults.")
            sheet = doc.add_worksheet(title="PROMPT INPUTS", rows=10, cols=2)
            
        records = sheet.get_all_records()
        
        if not records:
            logger.info("Populating PROMPT INPUTS tab with default values...")
            if not sheet.row_values(1):
                sheet.append_row(["Input Field", "Value"])
            sheet.append_rows([
                ["Initial Image Prompt", "A cinematic shot of a fashion model, highly detailed, 4k"],
                ["Locations", "Paris\nTokyo\nNew York"],
                ["Additional Image Instructions", "Keep lighting natural and photorealistic"],
                ["Additional Video Instructions", "Gentle cinematic camera pan"],
                ["Initial Image File", ""]
            ])
            records = sheet.get_all_records()
        
        inputs = {str(r.get("Input Field", "")).strip(): str(r.get("Value", "")).strip() for r in records}
        
        # Build locations list
        locations = []
        loc_str = inputs.get("Locations", "")
        if loc_str:
            locations = [loc.strip() for loc in loc_str.split("\n") if loc.strip()]

        prompt_inputs = PromptInputs(
            initial_image_prompt=inputs.get("Initial Image Prompt") or inputs.get("Initial Image Prompts", ""),
            additional_image_instructions=inputs.get("Additional Image Instructions", ""),
            additional_video_instructions=inputs.get("Additional Video Instructions", ""),
            locations=locations,
            initial_image_file=inputs.get("Initial Image File", "") or None
        )
        
        # Save cache
        _update_defaults_cache("inputs", prompt_inputs.model_dump())
        return prompt_inputs

    except Exception as e:
        logger.error(f"Failed to fetch inputs from Google Sheets: {e}")
        logger.warning(f"Attempting to load fallback inputs from {DEFAULTS_FILE}...")
        return _load_fallback("inputs", PromptInputs)


def _update_defaults_cache(key: str, data: dict):
    """Helper to update a specific section of the defaults.json file."""
    cache = {}
    if os.path.exists(DEFAULTS_FILE):
        try:
            with open(DEFAULTS_FILE, "r") as f:
                cache = json.load(f)
        except Exception:
            pass
    
    cache[key] = data
    with open(DEFAULTS_FILE, "w") as f:
        json.dump(cache, f, indent=4)


def _load_fallback(key: str, model_class):
    """Helper to load a Pydantic model from the defaults.json fallback."""
    if not os.path.exists(DEFAULTS_FILE):
        raise RuntimeError(f"Cannot fallback to {DEFAULTS_FILE} because it does not exist.")
    with open(DEFAULTS_FILE, "r") as f:
        cache = json.load(f)
        
    data = cache.get(key)
    if not data:
        raise ValueError(f"Section '{key}' not found in {DEFAULTS_FILE}.")
        
    logger.success(f"Successfully loaded {key} fallback from {DEFAULTS_FILE}!")
    return model_class(**data)


def get_outputs(client: gspread.Client, spreadsheet_id: str) -> list[dict]:
    """Reads the OUTPUTS tab."""
    try:
        sheet = client.open_by_key(spreadsheet_id).worksheet("OUTPUTS")
        return sheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("OUTPUTS tab not found. Creating it.")
        doc = client.open_by_key(spreadsheet_id)
        sheet = doc.add_worksheet(title="OUTPUTS", rows=100, cols=10)
        headers = ["Project", "Type", "Location", "Image Input", "Image Prompt", "Video Prompt", "Image File", "Video File"]
        sheet.append_row(headers)
        return []


def update_output_row(client: gspread.Client, spreadsheet_id: str, row_data: dict, match_col: str, match_val: str, project_name: str):
    """
    Updates a row in the OUTPUTS tab, or appends a new one if it doesn't exist.
    Matches based on BOTH the Project column and the provided match_col.
    """
    sheet = client.open_by_key(spreadsheet_id).worksheet("OUTPUTS")
    records = sheet.get_all_records()

    headers = sheet.row_values(1)

    # Ensure row_data aligns with headers
    ordered_values = [row_data.get(h, "") for h in headers]

    # Find row to update (must match both Project and the specified column)
    row_idx = -1
    for i, r in enumerate(records):
        if r.get("Project") == project_name and r.get(match_col) == match_val:
            row_idx = i + 2 # +2 because sheet is 1-indexed and header is row 1
            break

    if row_idx == -1:
        # Append
        logger.info(f"Appending new row to OUTPUTS: {match_val}")
        sheet.append_row(ordered_values)
    else:
        # Update specific row
        logger.info(f"Updating row {row_idx} in OUTPUTS: {match_val}")
        # Build cell range, e.g., A2:G2
        end_col_letter = chr(ord("A") + len(headers) - 1)
        cell_range = f"A{row_idx}:{end_col_letter}{row_idx}"
        sheet.update(cell_range, [ordered_values])


def update_input_field(client: gspread.Client, spreadsheet_id: str, field_name: str, value: str):
    """Updates a specific field in the PROMPT INPUTS tab."""
    try:
        sheet = client.open_by_key(spreadsheet_id).worksheet("PROMPT INPUTS")
        cell = sheet.find(field_name)
        if cell:
            # Update the value cell right next to the label cell
            sheet.update_cell(cell.row, cell.col + 1, value)
        else:
            # Append if not found
            sheet.append_row([field_name, value])
    except Exception as e:
        logger.error(f"Failed to update input field: {e}")
