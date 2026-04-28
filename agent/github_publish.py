"""Publish a generated landing page to a GitHub repo via the REST API.

Layout in the target repo:
    pages/<slug>/index.html
    pages/<slug>/hero.jpg

GitHub Pages is configured at the repo level to serve the `main` branch
root, so each landing is reachable at:
    https://<user>.github.io/<repo>/pages/<slug>/
or, with a custom CNAME (recommended):
    https://landing.example.com/pages/<slug>/
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass

import requests

GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class GitHubConfig:
    token: str
    username: str
    repo: str
    base_url: str  # e.g. https://landing.leonemasterschool.it

    @classmethod
    def from_env(cls) -> "GitHubConfig":
        return cls(
            token=os.getenv("GITHUB_TOKEN", "").strip(),
            username=os.getenv("GITHUB_USERNAME", "").strip(),
            repo=os.getenv("GITHUB_PAGES_REPO", "").strip(),
            base_url=os.getenv("LANDING_BASE_URL", "").strip().rstrip("/"),
        )

    def ensure_complete(self) -> None:
        missing = [k for k, v in {
            "GITHUB_TOKEN": self.token,
            "GITHUB_USERNAME": self.username,
            "GITHUB_PAGES_REPO": self.repo,
            "LANDING_BASE_URL": self.base_url,
        }.items() if not v]
        if missing:
            raise RuntimeError(f"Missing GitHub config: {', '.join(missing)}")


@dataclass(frozen=True)
class PublishResult:
    slug: str
    public_url: str
    html_commit_sha: str


def _headers(cfg: GitHubConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_existing_sha(cfg: GitHubConfig, path: str) -> str | None:
    r = requests.get(
        f"{GITHUB_API}/repos/{cfg.username}/{cfg.repo}/contents/{path}",
        headers=_headers(cfg),
        timeout=15,
    )
    if r.status_code == 200:
        return r.json().get("sha")
    return None


def _put_file(
    cfg: GitHubConfig,
    *,
    path: str,
    content_bytes: bytes,
    message: str,
) -> str:
    existing_sha = _get_existing_sha(cfg, path)
    body: dict = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
    }
    if existing_sha:
        body["sha"] = existing_sha
    r = requests.put(
        f"{GITHUB_API}/repos/{cfg.username}/{cfg.repo}/contents/{path}",
        headers=_headers(cfg),
        json=body,
        timeout=20,
    )
    if not r.ok:
        raise RuntimeError(f"GitHub PUT {path} failed: {r.status_code} {r.text[:300]}")
    return r.json()["commit"]["sha"]


def publish_landing(
    cfg: GitHubConfig,
    *,
    slug: str,
    html: str,
    images: dict[str, bytes] | None = None,
) -> PublishResult:
    """Publish HTML + optional per-slot images to the target repo.

    `images` maps slot name → image bytes. Each is committed at
    pages/<slug>/img-<slot>.jpg.
    """
    cfg.ensure_complete()
    safe_slug = slug.strip().strip("/").lower()
    if not safe_slug:
        raise ValueError("slug cannot be empty")

    base_path = f"pages/{safe_slug}"

    for slot, payload in (images or {}).items():
        if not payload:
            continue
        slot_safe = slot.strip().lower().replace(" ", "_")
        _put_file(
            cfg,
            path=f"{base_path}/img-{slot_safe}.jpg",
            content_bytes=payload,
            message=f"feat({safe_slug}): add image for slot {slot_safe}",
        )

    html_sha = _put_file(
        cfg,
        path=f"{base_path}/index.html",
        content_bytes=html.encode("utf-8"),
        message=f"feat({safe_slug}): publish landing page",
    )
    return PublishResult(
        slug=safe_slug,
        public_url=f"{cfg.base_url}/{base_path}/",
        html_commit_sha=html_sha,
    )


@dataclass(frozen=True)
class SetupResult:
    repo_existed: bool
    pages_url: str
    custom_domain: str
    cname_target: str       # what to put in the DNS CNAME (e.g. salvotrifiro96-ux.github.io)


def verify_token(token: str) -> str:
    """Return the GitHub username for this token, or raise."""
    if not token.strip():
        raise RuntimeError("GitHub token is empty")
    r = requests.get(
        f"{GITHUB_API}/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=10,
    )
    if r.status_code == 401:
        raise RuntimeError("GitHub token rejected (401). Generate a new PAT with `repo` scope.")
    if not r.ok:
        raise RuntimeError(f"GitHub /user check failed: {r.status_code} {r.text[:200]}")
    return r.json().get("login", "")


def _ensure_repo(cfg: GitHubConfig) -> bool:
    """Create the repo if it does not exist. Returns True if it already existed."""
    r = requests.get(
        f"{GITHUB_API}/repos/{cfg.username}/{cfg.repo}",
        headers=_headers(cfg),
        timeout=10,
    )
    if r.status_code == 200:
        return True
    if r.status_code != 404:
        raise RuntimeError(f"GitHub repo check failed: {r.status_code} {r.text[:200]}")

    create = requests.post(
        f"{GITHUB_API}/user/repos",
        headers=_headers(cfg),
        json={
            "name": cfg.repo,
            "private": False,        # GitHub Pages free tier requires public
            "auto_init": True,
            "has_issues": False,
            "has_wiki": False,
            "has_projects": False,
            "description": "Landing pages auto-generated by funnel-landing-agent",
        },
        timeout=15,
    )
    if not create.ok:
        raise RuntimeError(f"GitHub repo create failed: {create.status_code} {create.text[:200]}")
    return False


def setup_hosting_repo(cfg: GitHubConfig) -> SetupResult:
    """Idempotent: verify creds, create repo if missing, set CNAME, enable Pages.

    Returns a SetupResult that the UI can use to show DNS instructions.
    """
    cfg.ensure_complete()

    # custom_domain is the bare hostname (no scheme), e.g. landing.example.com
    custom_domain = cfg.base_url.replace("https://", "").replace("http://", "").strip("/")
    if not custom_domain:
        raise RuntimeError("LANDING_BASE_URL must be a valid URL/hostname")

    verify_token(cfg.token)
    repo_existed = _ensure_repo(cfg)

    # Write/update CNAME file with the custom domain
    _put_file(
        cfg,
        path="CNAME",
        content_bytes=custom_domain.encode("utf-8"),
        message="chore: set custom domain",
    )

    # Enable / update Pages
    ensure_pages_enabled(cfg, custom_domain=custom_domain)

    return SetupResult(
        repo_existed=repo_existed,
        pages_url=f"https://{custom_domain}/",
        custom_domain=custom_domain,
        cname_target=f"{cfg.username}.github.io",
    )


def ensure_pages_enabled(cfg: GitHubConfig, custom_domain: str | None = None) -> None:
    """Enable GitHub Pages on the target repo if not already enabled.

    Idempotent: if Pages is already enabled, only updates the custom domain.
    Safe to call on every deploy.
    """
    cfg.ensure_complete()
    base = f"{GITHUB_API}/repos/{cfg.username}/{cfg.repo}/pages"
    info = requests.get(base, headers=_headers(cfg), timeout=15)

    payload: dict = {
        "source": {"branch": "main", "path": "/"},
    }
    if custom_domain:
        payload["cname"] = custom_domain

    if info.status_code == 404:
        r = requests.post(base, headers=_headers(cfg), json=payload, timeout=15)
        if not r.ok:
            raise RuntimeError(f"Pages enable failed: {r.status_code} {r.text[:300]}")
    elif info.status_code == 200 and custom_domain:
        r = requests.put(base, headers=_headers(cfg), json=payload, timeout=15)
        if not r.ok and r.status_code != 204:
            raise RuntimeError(f"Pages update failed: {r.status_code} {r.text[:300]}")
