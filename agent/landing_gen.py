"""Landing page HTML generation with Claude.

Claude acts as a world-class direct-response copywriter and produces a
single self-contained `index.html` that uses Tailwind via CDN (no build
step), embeds a hero image as <img>, and includes the operator's own
form HTML verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass

from anthropic import Anthropic

CLAUDE_MODEL = "claude-opus-4-7"


@dataclass(frozen=True)
class LandingBrief:
    client_name: str
    slug: str
    project_context: str
    form_html: str
    brand_colors_hex: dict[str, str]
    font_family: str
    style_keywords: str
    hero_image_path: str = "hero.jpg"


@dataclass(frozen=True)
class LandingPage:
    html: str
    page_title: str
    meta_description: str


def _system_prompt() -> str:
    return (
        "You are a world-class direct-response copywriter and conversion-focused "
        "landing-page designer. You write copy at the level of David Ogilvy, "
        "Gary Halbert, Eugene Schwartz, Dan Kennedy, and Joe Sugarman — applying "
        "their principles: clear awareness-level targeting, single dominant "
        "emotion per page, specific numbers over vague claims, AIDA structure, "
        "social proof when warranted, scarcity/urgency only when legitimate, "
        "objection handling, and a CTA that pairs an action verb with a concrete "
        "benefit. You decide the headline, subheadline, body sections, bullet "
        "points, and CTA copy based on the brief — the operator does not "
        "pre-write copy.\n\n"
        "OUTPUT — a single complete `index.html` that:\n"
        "1. Loads Tailwind via CDN: <script src=\"https://cdn.tailwindcss.com\"></script>\n"
        "2. Has no build step, no external CSS files, no JS frameworks. Inline "
        "minimal vanilla JS only if needed (e.g., FAQ accordion, smooth scroll).\n"
        "3. Embeds the operator's form HTML EXACTLY as provided — never change "
        "field names, action, method, hidden inputs, or button text.\n"
        "4. Uses <img src=\"hero.jpg\" alt=\"...\"> for the hero image with a "
        "meaningful alt text and responsive sizing.\n"
        "5. Configures Tailwind with an inline `tailwind.config` mapping the "
        "provided primary/secondary/accent colors to `brand-primary`, etc.\n"
        "6. Loads the chosen Google Font and applies it as the body font.\n"
        "7. Is mobile-first: every section reads cleanly at 360px width.\n"
        "8. Includes a complete <head>: charset, viewport, title, description, "
        "og:title, og:description, og:image (use hero.jpg), twitter:card.\n"
        "9. Writes copy in Italian unless the brief explicitly says otherwise.\n"
        "10. NEVER uses placeholder/Lorem Ipsum copy. Every word must be "
        "intentional and aligned with the brief.\n"
        "11. Decides which sections to include based on what the project needs "
        "to convert: typical patterns are Hero → Promise → Proof/Authority → "
        "Problem & Agitation → Solution & Mechanism → Outcome → Bonuses/"
        "Guarantee → CTA → FAQ → Final CTA. Skip sections that have no real "
        "supporting content from the brief — never fabricate testimonials, "
        "fake numbers, or invented credentials.\n"
        "12. Uses the form section as the primary conversion point. Place the "
        "form prominently above the fold AND repeated lower on the page if it "
        "helps conversion.\n\n"
        "OUTPUT FORMAT — return ONLY a valid JSON object (no markdown, no "
        "preamble) with these keys:\n"
        '  {"html": "<!DOCTYPE html>...", "page_title": "...", "meta_description": "..."}\n'
        "page_title ≤ 60 chars, meta_description ≤ 155 chars, both written for "
        "click-through, not just SEO."
    )


def _user_prompt(brief: LandingBrief) -> str:
    color_lines = "\n".join(f"  - {k}: {v}" for k, v in brief.brand_colors_hex.items())
    return f"""# Brief

## Cliente
{brief.client_name}

## Slug (URL path)
{brief.slug}

## Contesto del progetto (libero — qui c'è tutto quello che serve sapere)
{brief.project_context}

## Form HTML (embed VERBATIM — non modificare action, method, name, value, hidden, button)
```html
{brief.form_html}
```

## Branding
- Style keywords: {brief.style_keywords}
- Font family (Google Fonts): {brief.font_family}
- Brand colors (HEX):
{color_lines}

## Hero image
Path relativo: hero.jpg (già salvato accanto a index.html). Aspect 16:9, da usare nel hero.

---

Sei tu il copywriter. Decidi struttura, headline, subheadline, sezioni, bullet,
testimonial style/placement (solo se il brief offre proof reale — altrimenti
salta), CTA, FAQ. Scrivi italiano persuasivo, concreto, anti-fuffa.

Restituisci SOLO il JSON come da istruzioni di sistema.
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
