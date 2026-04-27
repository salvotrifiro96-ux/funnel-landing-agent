"""Landing page HTML generation with Claude.

Produces a single self-contained `index.html` that uses Tailwind via CDN
(no build step), embeds a hero image as <img>, and includes the operator's
own form HTML verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass

from anthropic import Anthropic

CLAUDE_MODEL = "claude-opus-4-7"


@dataclass(frozen=True)
class LandingBrief:
    client_name: str
    slug: str
    objective: str
    target_audience: str
    headline_hint: str
    subheadline_hint: str
    value_props: str
    sections: tuple[str, ...]
    primary_cta_label: str
    secondary_info: str
    form_html: str
    brand_colors_hex: dict[str, str]
    font_family: str
    style_keywords: str
    hero_image_path: str
    favicon_url: str = ""


@dataclass(frozen=True)
class LandingPage:
    html: str
    page_title: str
    meta_description: str


def _system_prompt() -> str:
    return (
        "You are a senior landing-page designer + copywriter. "
        "Output a single complete `index.html` that uses Tailwind CSS via CDN "
        "(`<script src=\"https://cdn.tailwindcss.com\"></script>`). "
        "No build step, no external CSS files, no JS frameworks. "
        "Inline minimal vanilla JS only if necessary (e.g., FAQ accordion).\n\n"
        "HARD CONSTRAINTS:\n"
        "1. Embed the operator's form HTML EXACTLY as provided — never modify "
        "field names, action, method, hidden inputs, or button text.\n"
        "2. Use the provided hero image path as <img src='hero.jpg'> with "
        "responsive width and a meaningful alt.\n"
        "3. Use the provided brand colors and font family. Configure Tailwind "
        "with a small inline `tailwind.config` for primary/secondary/accent.\n"
        "4. Mobile-first. Test mentally that everything reads on 360px width.\n"
        "5. Single file. No external assets except hero.jpg, the favicon (if "
        "provided), Tailwind CDN, and Google Fonts CDN for the chosen font.\n"
        "6. Include <meta> tags: charset, viewport, title, description, og:title, "
        "og:description, og:image (use hero.jpg), twitter:card.\n"
        "7. Write copy in Italian unless the brief explicitly says otherwise.\n"
        "8. Do not include placeholder Lorem Ipsum — invent concrete copy aligned "
        "with the brief.\n\n"
        "OUTPUT FORMAT — return ONLY a JSON object with these keys (no markdown):\n"
        '  {"html": "<!DOCTYPE html>...", "page_title": "...", "meta_description": "..."}\n'
        "page_title ≤ 60 chars, meta_description ≤ 155 chars."
    )


def _user_prompt(brief: LandingBrief) -> str:
    color_lines = "\n".join(f"  - {k}: {v}" for k, v in brief.brand_colors_hex.items())
    sections_block = "\n".join(f"  - {s}" for s in brief.sections) if brief.sections else "  (no extra sections)"
    return f"""# Brief

**Client**: {brief.client_name}
**Slug** (URL path): {brief.slug}
**Objective**: {brief.objective}
**Target audience**: {brief.target_audience}

## Copy direction
- Headline hint: {brief.headline_hint or '(free)'}
- Subheadline hint: {brief.subheadline_hint or '(free)'}
- Value props / benefits to cover:
{brief.value_props}

## Required sections (in order)
{sections_block}

## Primary CTA label
{brief.primary_cta_label}

## Secondary info / footer notes
{brief.secondary_info or '(none)'}

## Form HTML (embed VERBATIM, do not modify)
```html
{brief.form_html}
```

## Branding
- Style keywords: {brief.style_keywords}
- Font family (Google Fonts): {brief.font_family}
- Brand colors:
{color_lines}

## Hero image
Path: hero.jpg (already saved next to index.html)
Aspect: 16:9, used in the hero section.

Return ONLY the JSON object as instructed.
"""


def generate_landing(api_key: str, brief: LandingBrief) -> LandingPage:
    """Call Claude with the brief and return a LandingPage. Raises on failure."""
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        system=_system_prompt(),
        messages=[{"role": "user", "content": _user_prompt(brief)}],
    )

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()

    import json

    data = json.loads(text)
    return LandingPage(
        html=data["html"],
        page_title=data["page_title"],
        meta_description=data["meta_description"],
    )
