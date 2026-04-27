"""Hero image generation via Pollinations.ai — free, keyless, no bot detection.

Pollinations exposes a simple GET endpoint that returns image bytes directly:
    https://image.pollinations.ai/prompt/<URL-encoded prompt>?width=...&height=...
No API key, no rate limit caveats for low-volume use, no Cloudflare/DataDome
challenges. Replaces the Higgsfield Nano Banana Pro flow which was blocked
by DataDome when called from Streamlit Cloud.
"""
from __future__ import annotations

import urllib.parse

import requests

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"

ASPECT_FORMATS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "16:9": (1024, 576),
    "9:16": (576, 1024),
    "4:5": (819, 1024),
}

DEFAULT_MODEL = "flux"


class ImageGenError(RuntimeError):
    pass


def generate_hero_image(
    prompt: str,
    *,
    aspect: str = "16:9",
    model: str = DEFAULT_MODEL,
    seed: int | None = None,
    timeout_sec: int = 180,
) -> bytes:
    """Return JPEG/PNG bytes for the given prompt. Raises ImageGenError on failure."""
    width, height = ASPECT_FORMATS.get(aspect, ASPECT_FORMATS["16:9"])

    encoded = urllib.parse.quote(prompt, safe="")
    params = {
        "width": str(width),
        "height": str(height),
        "model": model,
        "nologo": "true",
        "enhance": "true",
        "safe": "false",
    }
    if seed is not None:
        params["seed"] = str(seed)

    url = f"{POLLINATIONS_BASE}/{encoded}"

    try:
        r = requests.get(url, params=params, timeout=timeout_sec)
    except requests.RequestException as exc:
        raise ImageGenError(f"Pollinations request failed: {exc}") from exc

    if not r.ok:
        raise ImageGenError(
            f"Pollinations returned {r.status_code}: {r.text[:200]}"
        )

    content_type = r.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        raise ImageGenError(
            f"Pollinations did not return an image (Content-Type={content_type})"
        )

    return r.content
