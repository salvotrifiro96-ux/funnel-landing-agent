"""Higgsfield Nano Banana Pro — hero image generation via cookie auth.

Usage:
    bytes_ = generate_hero_image("clean editorial photo of...", aspect="16:9")

Cookies (HIGGSFIELD_CLERK_CLIENT, HIGGSFIELD_SESSION_ID) expire ~30 days;
refresh from DevTools → Application → Cookies → higgsfield.ai → __client.
"""
from __future__ import annotations

import os
import time
import urllib.request
from dataclasses import dataclass

import requests

CLERK_URL = "https://clerk.higgsfield.ai"
FNF_BASE = "https://fnf.higgsfield.ai"

ASPECT_FORMATS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "16:9": (1024, 576),
    "9:16": (576, 1024),
    "4:5": (819, 1024),
}


class HiggsfieldError(RuntimeError):
    pass


@dataclass(frozen=True)
class HiggsfieldCreds:
    clerk_client: str
    session_id: str

    @classmethod
    def from_env(cls) -> "HiggsfieldCreds":
        clerk = os.getenv("HIGGSFIELD_CLERK_CLIENT", "").strip()
        sess = os.getenv("HIGGSFIELD_SESSION_ID", "").strip()
        if not clerk or not sess:
            raise HiggsfieldError(
                "HIGGSFIELD_CLERK_CLIENT and HIGGSFIELD_SESSION_ID must be set"
            )
        return cls(clerk_client=clerk, session_id=sess)


def _fresh_jwt(creds: HiggsfieldCreds) -> str:
    r = requests.post(
        f"{CLERK_URL}/v1/client/sessions/{creds.session_id}/tokens",
        headers={"Cookie": f"__client={creds.clerk_client}"},
        timeout=10,
    )
    if not r.ok:
        raise HiggsfieldError(
            f"Clerk token refresh failed ({r.status_code}). "
            "Refresh HIGGSFIELD_CLERK_CLIENT cookie from higgsfield.ai."
        )
    return r.json()["jwt"]


def _auth_headers(creds: HiggsfieldCreds) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_fresh_jwt(creds)}",
        "Content-Type": "application/json",
    }


def generate_hero_image(
    prompt: str,
    *,
    aspect: str = "16:9",
    creds: HiggsfieldCreds | None = None,
    poll_interval_sec: float = 5.0,
    max_wait_sec: int = 300,
) -> bytes:
    """Submit a Nano Banana Pro job, wait for completion, return image bytes.

    Raises HiggsfieldError on auth/submission/polling/download failures.
    """
    creds = creds or HiggsfieldCreds.from_env()
    width, height = ASPECT_FORMATS.get(aspect, ASPECT_FORMATS["16:9"])

    body = {
        "params": {
            "prompt": prompt,
            "width": width,
            "height": height,
            "aspect_ratio": aspect,
            "resolution": "1k",
            "batch_size": 1,
            "use_unlim": True,
            "is_storyboard": False,
            "is_zoom_control": False,
            "input_images": [],
        },
        "use_unlim": True,
    }

    submit = requests.post(
        f"{FNF_BASE}/jobs/nano-banana-2",
        headers=_auth_headers(creds),
        json=body,
        timeout=15,
    )
    if not submit.ok:
        raise HiggsfieldError(f"Submit failed: {submit.status_code} {submit.text[:300]}")

    job_set_id = submit.json()["job_sets"][0]["id"]

    deadline = time.time() + max_wait_sec
    state: dict | None = None
    while time.time() < deadline:
        time.sleep(poll_interval_sec)
        try:
            poll = requests.get(
                f"{FNF_BASE}/job-sets/{job_set_id}",
                headers=_auth_headers(creds),
                timeout=10,
            )
        except requests.RequestException:
            continue
        if not poll.ok:
            continue
        state = poll.json()
        jobs = state.get("jobs", [])
        if jobs and all(j["status"] in ("completed", "failed", "error", "cancelled") for j in jobs):
            break

    if state is None:
        raise HiggsfieldError("Polling never returned a state")

    for job in state.get("jobs", []):
        if job["status"] != "completed":
            continue
        results = job.get("results") or job.get("result") or {}
        raw = results.get("raw", {}) if isinstance(results, dict) else {}
        url = raw.get("url")
        if not url:
            continue
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()

    raise HiggsfieldError("No completed job produced a downloadable URL")
