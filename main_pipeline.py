"""
main_pipeline.py

This is the primary entry point and Command Line Interface (CLI) for the AI Video Batch Pipeline.
It does NOT contain the heavy lifting logic. Instead, it provides the clean, intuitive commands 
(init, run-base, run-locations, run-videos) that you type into your terminal. When a command is run,
it delegates the actual work to the core logic found in `src/pipeline.py`.
"""

import asyncio
import json
import os
import typer

from src.pipeline import (
    generate_base_scene,
    generate_location_variations,
    generate_final_videos
)

app = typer.Typer(help="AI Video Batch Generator CLI")

@app.command("init")
def init_project(
    project: str = typer.Argument(..., help="The unique name for your new project."),
    sheet_id: str = typer.Option(..., "--sheet-id", help="The Google Sheet ID for this specific project.")
):
    """Initializes a new project workspace, saves its configuration, and tests the Google Sheet connection."""
    base_dir = os.path.join("projects", project)
    os.makedirs(base_dir, exist_ok=True)
    
    config_path = os.path.join(base_dir, "project_config.json")
    config_data = {"spreadsheet_id": sheet_id}
    
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=4)
        
    typer.secho(f"✅ Project '{project}' workspace created at: {base_dir}", fg=typer.colors.GREEN)
    typer.secho("🔄 Testing connection to Google Sheets...")
    
    try:
        from src.sheets import get_sheets_client, fetch_parameters, fetch_inputs, log_event
        client = get_sheets_client()
        # This will verify auth and also trigger the caching to defaults.json!
        fetch_parameters(client, sheet_id)
        fetch_inputs(client, sheet_id)
        
        # Log the initialization!
        log_event(client, sheet_id, project, "Initialization", "Completed")
        
        typer.secho("✅ Successfully connected to Google Sheets and cached initial parameters!", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Failed to connect to Google Sheets: {e}", fg=typer.colors.RED)
        typer.secho("Make sure your credentials are correct and the Google Sheet is shared with your service account if needed.", fg=typer.colors.YELLOW)

@app.command("run-base")
def run_base(project: str = typer.Argument(..., help="The unique project name.")):
    """Step 1: Generates ONLY the base image and video prompt, then stops so you can review."""
    asyncio.run(generate_base_scene(project=project))

@app.command("run-locations")
def run_locations(
    project: str = typer.Argument(..., help="The unique project name."),
    test_mode: bool = typer.Option(False, "--test-mode", help="Limits to 1 location.")
):
    """Step 2: Generates ONLY the modified location prompts and location images (no videos)."""
    asyncio.run(generate_location_variations(project=project, test_mode=test_mode))

@app.command("run-videos")
def run_videos(
    project: str = typer.Argument(..., help="The unique project name."),
    test_mode: bool = typer.Option(False, "--test-mode", help="Limits to 1 video.")
):
    """Step 3: Generates the Veo/Fal videos for all existing images."""
    asyncio.run(generate_final_videos(project=project, test_mode=test_mode))

if __name__ == "__main__":
    app()
