# AI Influencer Pipeline 🎬

A modern, multi-project pipeline to generate AI influencer images and videos consistently using Gemini and Fal.ai.

## 🛠️ Setup

1. **Install Dependencies:**
   ```bash
   uv sync
   ```
2. **Configure Secrets:**
   Copy `.env.example` to `.env` and fill in your API keys (Google Gemini, Fal.ai, and Google credentials).

## 🚀 The Workflow

This pipeline is designed for intuitive, step-by-step generation with manual review points.

### 1. Initialize a Project
Create a new project workspace linked to a specific Google Sheet ID.
```bash
uv run python main_pipeline.py init "my_campaign" --sheet-id "1BxiMvs0XRX5Y..."
```
*(This creates `projects/my_campaign/` to store your images and videos).*

### 2. Generate Base Campaign (Step 1)
Generates the very first base image and video prompt. **Stop here to review the initial output.**
```bash
uv run python main_pipeline.py run-base "my_campaign"
```

### 3. Generate Location Variations (Step 2)
Uses your base image to generate consistent character images across all the new locations defined in your Google Sheet. **Stop here to review the location images.**
```bash
uv run python main_pipeline.py run-locations "my_campaign"
```

### 4. Generate Final Videos (Step 3)
Takes all the generated location images and prompts, sending them to the video AI to generate your final `.mp4` files.
```bash
uv run python main_pipeline.py run-videos "my_campaign"
```

## 📊 Dashboard Visualization

Want to watch your pipeline run in real-time? Start the UI dashboard in a separate terminal:
```bash
uv run prefect server start
```
Then visit `http://127.0.0.1:4200` in your browser.

## 🏗️ Pipeline Architecture

```mermaid
graph TD
    A[(Google Sheets)] -->|Init| B[projects/my_campaign/]
    
    B --> C(run-base)
    C -->|Gemini 3.0 Pro| D[Base Image & Video Prompt]
    
    D --> E(run-locations)
    E -->|Gemini 3.0 Pro| F[Location Image Variations]
    
    F --> G(run-videos)
    G -->|Veo / Fal.ai| H[Final MP4 Video Batch]
    
    style A fill:#0f9d58,stroke:#000,stroke-width:2px,color:#fff
    style C fill:#4285f4,stroke:#000,stroke-width:2px,color:#fff
    style E fill:#4285f4,stroke:#000,stroke-width:2px,color:#fff
    style G fill:#4285f4,stroke:#000,stroke-width:2px,color:#fff
    style D fill:#f4b400,stroke:#000,stroke-width:2px,color:#fff
    style F fill:#f4b400,stroke:#000,stroke-width:2px,color:#fff
    style H fill:#db4437,stroke:#000,stroke-width:2px,color:#fff
```
