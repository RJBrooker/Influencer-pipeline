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
    """Initializes a new project workspace and saves its configuration."""
    base_dir = os.path.join("projects", project)
    os.makedirs(base_dir, exist_ok=True)
    
    config_path = os.path.join(base_dir, "project_config.json")
    config_data = {"spreadsheet_id": sheet_id}
    
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=4)
        
    typer.secho(f"✅ Project '{project}' initialized successfully!", fg=typer.colors.GREEN)
    typer.secho(f"📁 Workspace created at: {base_dir}")
    typer.secho(f"📝 Config saved with Sheet ID: {sheet_id}")

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
