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


@dataclass(frozen=True)
class ImageSlot:
    name: str          # snake_case, e.g. "hero", "speaker", "benefit_1"
    description: str   # short visual brief — fed to gpt-image-1 if user chooses generate


@dataclass(frozen=True)
class LandingPage:
    html: str
    page_title: str
    meta_description: str
    image_slots: tuple[ImageSlot, ...] = ()


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
        "4. Identifies up to 6 sections where an image would meaningfully boost "
        "conversion (hero, speaker portrait, top benefits, testimonial avatar, "
        "bonus visual, etc.) and includes for each one an <img> tag of the form:\n"
        "   <img src=\"img-<slot>.jpg\" alt=\"...\" data-img-slot=\"<slot>\" class=\"...\">\n"
        "where <slot> is a short snake_case name. The page must also work "
        "WITHOUT those images (the operator may skip any slot) — so size and "
        "position the <img>s so that removing them does not break the layout. "
        "Use `bg-gradient-to-*` / color blocks as graceful fallback in case the "
        "image is skipped. NEVER reference any image other than img-<slot>.jpg.\n"
        "5. Configures Tailwind with an inline `tailwind.config` mapping the "
        "provided primary/secondary/accent colors to `brand-primary`, etc.\n"
        "6. Loads the chosen Google Font and applies it as the body font.\n"
        "7. Is mobile-first: every section reads cleanly at 360px width.\n"
        "8. Includes a complete <head>: charset, viewport, title, description, "
        "og:title, og:description, og:image (set to img-hero.jpg if a hero slot "
        "exists, else omit), twitter:card.\n"
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
        "helps conversion.\n"
        "13. NEVER truncate or leave a section half-written. If you start a "
        "section (FAQ, speaker bio, testimonials, bonuses, …), finish it fully. "
        "If you are running out of room, drop a section entirely rather than "
        "leaving it incomplete. The output must end with a properly closed "
        "</body></html> followed by ===END===.\n\n"
        "OUTPUT FORMAT — return EXACTLY this structure, with the literal "
        "delimiter lines, in this order, and NOTHING ELSE (no preamble, no "
        "markdown fences, no trailing commentary):\n\n"
        "===PAGE_TITLE===\n"
        "<page title, ≤ 60 chars, written for click-through>\n"
        "===META_DESCRIPTION===\n"
        "<meta description, ≤ 155 chars, written for click-through>\n"
        "===IMAGE_SLOTS===\n"
        "<one slot per line — `slot_name | short visual description for image gen`>\n"
        "<example: `hero | warm editorial photo of italian entrepreneur at desk, AI dashboards on screen, soft natural light`>\n"
        "<list ONLY the slots you actually used in the HTML; if none, leave a single line: `(none)`>\n"
        "===HTML===\n"
        "<!DOCTYPE html>\n"
        "...full HTML document...\n"
        "===END===\n"
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

## Asset
Nessuna immagine disponibile. Costruisci l'hero e tutte le sezioni con sole
risorse tipografiche, gradienti, blocchi di colore e — se utile — piccoli SVG
inline puramente decorativi.

---

Sei tu il copywriter. Decidi struttura, headline, subheadline, sezioni, bullet,
testimonial style/placement (solo se il brief offre proof reale — altrimenti
salta), CTA, FAQ. Scrivi italiano persuasivo, concreto, anti-fuffa.

Restituisci SOLO il JSON come da istruzioni di sistema.
"""


_PT_DELIM = "===PAGE_TITLE==="
_MD_DELIM = "===META_DESCRIPTION==="
_SLOTS_DELIM = "===IMAGE_SLOTS==="
_HTML_DELIM = "===HTML==="
_END_DELIM = "===END==="


def _parse_image_slots(block: str) -> tuple[ImageSlot, ...]:
    """Parse the IMAGE_SLOTS block: one `name | description` per line."""
    slots: list[ImageSlot] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.lower() in ("(none)", "none"):
            continue
        if "|" not in line:
            continue
        name_raw, desc = line.split("|", 1)
        name = name_raw.strip().lower().replace(" ", "_")
        if not name:
            continue
        slots.append(ImageSlot(name=name, description=desc.strip()))
    # Dedupe while preserving order.
    seen: set[str] = set()
    unique: list[ImageSlot] = []
    for s in slots:
        if s.name in seen:
            continue
        seen.add(s.name)
        unique.append(s)
    return tuple(unique)


def _parse_delimited(text: str) -> LandingPage:
    """Parse Claude's delimited output into a LandingPage.

    Robust to leading/trailing whitespace and to a stray markdown fence.
    Tolerates a missing IMAGE_SLOTS section for backwards compatibility.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith(("json", "html", "text")):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.strip().rstrip("`").strip()

    pt_idx = cleaned.find(_PT_DELIM)
    md_idx = cleaned.find(_MD_DELIM)
    slots_idx = cleaned.find(_SLOTS_DELIM)
    html_idx = cleaned.find(_HTML_DELIM)
    end_idx = cleaned.find(_END_DELIM)

    if not (pt_idx != -1 and md_idx > pt_idx and html_idx > md_idx):
        raise ValueError(
            "Claude output did not contain expected delimiters "
            f"(PAGE_TITLE/META_DESCRIPTION/HTML). Got: {cleaned[:300]}"
        )

    page_title = cleaned[pt_idx + len(_PT_DELIM): md_idx].strip()

    if slots_idx > md_idx and slots_idx < html_idx:
        meta_description = cleaned[md_idx + len(_MD_DELIM): slots_idx].strip()
        slots_block = cleaned[slots_idx + len(_SLOTS_DELIM): html_idx].strip()
        slots = _parse_image_slots(slots_block)
    else:
        meta_description = cleaned[md_idx + len(_MD_DELIM): html_idx].strip()
        slots = ()

    html_end = end_idx if end_idx > html_idx else len(cleaned)
    html = cleaned[html_idx + len(_HTML_DELIM): html_end].strip()

    if not html.lstrip().lower().startswith("<!doctype"):
        raise ValueError("HTML section does not start with <!DOCTYPE html>")

    return LandingPage(
        html=html,
        page_title=page_title,
        meta_description=meta_description,
        image_slots=slots,
    )


def strip_skipped_image_slots(html: str, kept_slots: set[str]) -> str:
    """Remove `<img ... data-img-slot="X" ...>` tags whose slot is not kept.

    Conservative: only touches the <img> tag itself, leaves surrounding
    markup intact. Claude is instructed to size sections so removal does
    not break the layout.
    """
    import re

    pattern = re.compile(
        r'<img\b[^>]*\bdata-img-slot=["\']([^"\']+)["\'][^>]*/?>',
        flags=re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        slot = match.group(1).strip().lower()
        return match.group(0) if slot in kept_slots else ""

    return pattern.sub(replace, html)


def generate_landing(api_key: str, brief: LandingBrief) -> LandingPage:
    """Call Claude with the brief and return a LandingPage. Raises on failure."""
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=24000,
        system=_system_prompt(),
        messages=[{"role": "user", "content": _user_prompt(brief)}],
    )

    text = "".join(block.text for block in response.content if block.type == "text")
    if response.stop_reason == "max_tokens":
        raise ValueError(
            "Claude hit the max_tokens limit before finishing the page. "
            "Shorten the brief, or raise max_tokens further."
        )
    return _parse_delimited(text)
