"""Hero image generation via OpenAI gpt-image-1.

Uses the same paid API as the funnel-refresher-agent, so no new service.
gpt-image-1 supports 16:9 (1536x1024 landscape) which fits the landing hero.
"""
from __future__ import annotations

import base64

from openai import OpenAI

IMAGE_MODEL = "gpt-image-1"

# gpt-image-1 supported sizes (Nov 2025): 1024x1024, 1024x1536, 1536x1024.
ASPECT_TO_SIZE: dict[str, str] = {
    "1:1": "1024x1024",
    "16:9": "1536x1024",   # landscape
    "9:16": "1024x1536",   # portrait
}


class ImageGenError(RuntimeError):
    pass


def generate_hero_image(
    prompt: str,
    *,
    api_key: str,
    aspect: str = "16:9",
    quality: str = "high",
) -> bytes:
    """Return PNG bytes for the hero image. Raises ImageGenError on failure."""
    if not api_key:
        raise ImageGenError("OPENAI_API_KEY is missing")

    size = ASPECT_TO_SIZE.get(aspect, ASPECT_TO_SIZE["16:9"])
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
