"""Per-slot image generation via OpenAI gpt-image-1.

Each slot has its own optimal aspect:
  - hero       → 16:9 landscape (1536x1024)
  - speaker    → 1:1 square (1024x1024)
  - everything else → 1:1 square by default
"""
from __future__ import annotations

import base64

from openai import OpenAI

IMAGE_MODEL = "gpt-image-1"

ASPECT_TO_SIZE: dict[str, str] = {
    "1:1": "1024x1024",
    "16:9": "1536x1024",
    "9:16": "1024x1536",
}

DEFAULT_ASPECT_BY_SLOT: dict[str, str] = {
    "hero": "16:9",
    "background": "16:9",
    "speaker": "1:1",
    "team": "1:1",
}


class ImageGenError(RuntimeError):
    pass


def aspect_for_slot(slot_name: str) -> str:
    """Pick a default aspect ratio based on slot name; falls back to 1:1."""
    return DEFAULT_ASPECT_BY_SLOT.get(slot_name.lower(), "1:1")


def generate_image(
    prompt: str,
    *,
    api_key: str,
    aspect: str = "1:1",
    quality: str = "high",
) -> bytes:
    """Return PNG bytes from gpt-image-1. Raises ImageGenError on failure."""
    if not api_key:
        raise ImageGenError("OPENAI_API_KEY is missing")

    size = ASPECT_TO_SIZE.get(aspect, ASPECT_TO_SIZE["1:1"])
    client = OpenAI(api_key=api_key)

    try:
        result = client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )
    except Exception as exc:
        raise ImageGenError(f"gpt-image-1 call failed: {exc}") from exc

    b64 = result.data[0].b64_json
    if not b64:
        raise ImageGenError("gpt-image-1 returned empty b64_json")
    return base64.b64decode(b64)
