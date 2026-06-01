from dataclasses import dataclass

"""
src/cost_tracker.py

This file acts as the pipeline's accountant. It tracks every API call made during a run 
and calculates the estimated spend based on the pricing configurations defined in `src/config.py`. 
At the end of a step, it prints a beautiful receipt to the terminal.
"""

from loguru import logger

from .config import PRICING


@dataclass
class CostTracker:
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_images_generated: int = 0
    total_videos_generated: int = 0

    # Store specific models used to compute final cost
    text_model: str = "gemini-2.5-flash"
    image_model: str = "gemini-3.1-pro-preview"
    video_model: str = "veo-3.1-generate-preview"

    def add_tokens(self, input_tokens: int, output_tokens: int):
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

    def add_image(self):
        self.total_images_generated += 1

    def add_video(self):
        self.total_videos_generated += 1

    def calculate_cost(self) -> dict:
        text_pricing = PRICING.get(self.text_model, PRICING["gemini-2.5-flash"])
        img_pricing = PRICING.get(self.image_model, PRICING["gemini-3.1-pro-preview"])
        vid_pricing = PRICING.get(self.video_model, PRICING["veo-3.1-generate-preview"])

        text_cost = (self.total_input_tokens / 1_000_000 * text_pricing["input_per_1m"]) + (
            self.total_output_tokens / 1_000_000 * text_pricing["output_per_1m"]
        )
        img_cost = self.total_images_generated * img_pricing["per_image"]
        vid_cost = self.total_videos_generated * vid_pricing.get("per_video", 0.05)

        total_cost = text_cost + img_cost + vid_cost

        return {
            "text_cost": round(text_cost, 6),
            "image_cost": round(img_cost, 4),
            "video_cost": round(vid_cost, 4),
            "total_cost": round(total_cost, 4),
        }

    def print_receipt(self):
        costs = self.calculate_cost()
        receipt = f"""
=========================================
💸 GOD COST TRACKER - RUN RECEIPT 💸
=========================================
📝 Text Generation ({self.text_model})
   Input Tokens:  {self.total_input_tokens:,}
   Output Tokens: {self.total_output_tokens:,}
   Cost:          ${costs["text_cost"]:.6f}

🖼️ Image Generation ({self.image_model})
   Images Created: {self.total_images_generated}
   Cost:          ${costs["image_cost"]:.4f}

🎬 Video Generation ({self.video_model})
   Videos Created: {self.total_videos_generated}
   Cost:          ${costs["video_cost"]:.4f}

-----------------------------------------
💰 TOTAL ESTIMATED COST: ${costs["total_cost"]:.4f}
=========================================
"""
        logger.info(receipt)
