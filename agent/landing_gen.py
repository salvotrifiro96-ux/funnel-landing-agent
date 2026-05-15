"""Landing page HTML generation with Claude.

Claude acts as a world-class direct-response copywriter and produces a
single self-contained `index.html` that uses Tailwind via CDN (no build
step), embeds a hero image as <img>, and includes the operator's own
form HTML verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from anthropic import Anthropic

CLAUDE_MODEL = "claude-opus-4-7"


@dataclass(frozen=True)
class BodyImageSpec:
    """One uploaded image for the page body + a hint of where to place it."""

    filename: str          # final asset filename (e.g. "body-speaker.jpg")
    position_hint: str     # operator's note (e.g. "subito dopo la promise, centrata")
    alt: str               # alt text


@dataclass(frozen=True)
class LandingBrief:
    client_name: str
    slug: str
    project_context: str
    form_html: str
    brand_colors_hex: dict[str, str]
    font_family: str
    style_keywords: str
    # Optional reference / custom-code blobs.
    references: str = ""
    custom_code_head: str = ""
    custom_code_body: str = ""
    # Logo: filename relative to the published page folder.
    logo_filename: str = ""
    # Video: filename + position hint (one of: "hero", "after_promise",
    # "before_cta", "after_cta", "section_X" or empty for none).
    video_filename: str = ""
    video_position: str = ""
    # Body images: ordered tuple of specs. The HTML references each by filename.
    body_images: tuple[BodyImageSpec, ...] = ()
    # Trustbar: filenames of small logos to render in a horizontal strip.
    trustbar_logo_filenames: tuple[str, ...] = ()


SlotRole = Literal["banner", "background", "inline"]


@dataclass(frozen=True)
class ImageSlot:
    name: str          # snake_case, e.g. "hero", "speaker", "benefit_1"
    description: str   # short visual brief — fed to gpt-image-1 if user chooses generate
    role: SlotRole = "inline"  # "banner" = full-width strip; "background" = section bg cover; "inline" = inline <img>


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
        "4. For EVERY major content section of the landing (hero, problem, "
        "solution, mechanism, proof, bonuses, CTA, FAQ, footer-cta, …) you MUST "
        "reserve an optional image slot, UNLESS the section is structurally "
        "incompatible with an image (e.g. a pure trustbar of logos or a thin "
        "divider). Each slot is one of THREE roles:\n"
        "   • role=\"banner\"     — a full-width image strip BETWEEN sections "
        "(no overlay text). Render it as a standalone <section>:\n"
        "       <section class=\"my-12 sm:my-16\">\n"
        "         <img src=\"img-<slot>.jpg\" alt=\"...\" data-img-slot=\"<slot>\" "
        "data-img-role=\"banner\" class=\"w-full h-auto block\">\n"
        "       </section>\n"
        "   • role=\"background\" — image is the SECTION background (16:9 "
        "cover with overlay text). Render with a wrapper:\n"
        "       <section class=\"relative isolate overflow-hidden\" "
        "data-section-bg=\"<slot>\">\n"
        "         <img src=\"img-<slot>.jpg\" alt=\"\" aria-hidden=\"true\" "
        "data-img-slot=\"<slot>\" data-img-role=\"background\" "
        "class=\"absolute inset-0 -z-10 h-full w-full object-cover\">\n"
        "         <div class=\"absolute inset-0 -z-10 bg-black/50\"></div>\n"
        "         <!-- section content with white text or backdrop-blur card -->\n"
        "       </section>\n"
        "   • role=\"inline\"     — image inline within a section, next to or "
        "above text (e.g. speaker portrait beside bio, mockup over feature "
        "list). Render with the existing classic <img> tag:\n"
        "       <img src=\"img-<slot>.jpg\" alt=\"...\" data-img-slot=\"<slot>\" "
        "data-img-role=\"inline\" class=\"...\">\n"
        "Choose the role per slot based on WHAT FITS the content: hero usually "
        "= background, transitions between long blocks = banner, portraits / "
        "mockups / icons-as-photo = inline. The page MUST work WITHOUT any of "
        "these images (the operator may skip any) — design fallbacks so that "
        "removing an <img> (banner or inline) or removing the background image "
        "does not break the layout. For sections with role=\"background\", "
        "fallback is the dark overlay div + brand gradient. NEVER reference "
        "any image other than img-<slot>.jpg.\n"
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
        "<one slot per line — `slot_name | role | short visual description for image gen`>\n"
        "<role MUST be exactly one of: banner, background, inline>\n"
        "<example: `hero | background | warm editorial photo of italian entrepreneur at desk, AI dashboards on screen, soft natural light`>\n"
        "<example: `between_promise_and_proof | banner | wide horizontal photo of a packed live event, audience seen from the stage, warm tungsten lighting`>\n"
        "<example: `speaker | inline | three-quarter portrait of speaker, neutral studio backdrop`>\n"
        "<list ONLY the slots you actually used in the HTML; if none, leave a single line: `(none)`>\n"
        "===HTML===\n"
        "<!DOCTYPE html>\n"
        "...full HTML document...\n"
        "===END===\n"
    )


def _format_asset_section(brief: LandingBrief) -> str:
    """Describe what concrete assets the page must reference + how to use them."""
    has_logo = bool(brief.logo_filename)
    has_video = bool(brief.video_filename) and bool(brief.video_position)
    has_body_images = bool(brief.body_images)
    has_trustbar = bool(brief.trustbar_logo_filenames)

    if not (has_logo or has_video or has_body_images or has_trustbar):
        return (
            "## Asset\n"
            "Nessun asset caricato. Costruisci l'hero e tutte le sezioni con sole "
            "risorse tipografiche, gradienti, blocchi di colore e — se utile — piccoli SVG "
            "inline puramente decorativi. NON aggiungere `<img data-img-slot=...>` se "
            "non strettamente necessario alla conversione (verranno comunque rimossi "
            "in fase di publish se senza upload)."
        )

    parts = ["## Asset reali caricati dall'operatore"]
    parts.append(
        "I file qui sotto verranno COMMITTATI nel repo accanto a `index.html`. "
        "DEVI riferirli con `src` relativo al filename indicato — niente percorsi assoluti, "
        "niente CDN, niente placeholder. Se NON li referenzi, l'asset viene caricato ma "
        "non usato."
    )
    if has_logo:
        parts.append(
            f"\n### Logo brand\n"
            f"- File: `{brief.logo_filename}`\n"
            "- DOVE: inseriscilo come <img> nell'header in alto a sinistra (h-8 sm:h-10), "
            "linkato all'home (#top). Se il design lo richiede, ripetilo nel footer "
            "(h-6, opacita-70). Tag: "
            f'`<img src="{brief.logo_filename}" alt="{brief.client_name}" class="...">`.\n'
            "- NON includere mai placeholder/Lorem-style logo se questo asset esiste."
        )
    if has_trustbar:
        names_csv = ", ".join(f"`{n}`" for n in brief.trustbar_logo_filenames)
        parts.append(
            f"\n### Trustbar (loghi 'as seen on')\n"
            f"- Files: {names_csv}\n"
            "- DOVE: aggiungi una sezione `<section id=\"trustbar\">` SUBITO sotto l'hero "
            "(o sotto la prima CTA), con grid orizzontale di <img> tutti in grayscale "
            "(`filter:grayscale(1) opacity-60`), altezza uniforme h-6 sm:h-8, "
            "spaced-around, prefisso testuale tipo \"Come visto su\" o \"Ne parlano:\" se "
            "appropriato al contesto. Ogni img: "
            "`<img src=\"<filename>\" alt=\"...\" class=\"h-6 sm:h-8 ...\">`."
        )
    if has_body_images:
        body_lines = ["\n### Body images"]
        for spec in brief.body_images:
            body_lines.append(
                f"- `{spec.filename}` — alt: \"{spec.alt}\" — DOVE: {spec.position_hint}"
            )
        body_lines.append(
            "Usa OGNI body image dove indicato. Tag: "
            '`<img src="<filename>" alt="<alt>" class="...">`. Niente '
            "`data-img-slot` su queste — sono asset gia` definitivi."
        )
        parts.append("\n".join(body_lines))
    if has_video:
        parts.append(
            f"\n### Video\n"
            f"- File: `{brief.video_filename}`\n"
            f"- DOVE: posizione \"{brief.video_position}\" "
            "(`hero` = al posto/sopra/sotto l'hero principale; `after_promise` = dopo "
            "la promise / sub-headline; `before_cta` = subito prima della CTA principale; "
            "`after_cta` = subito dopo la prima CTA; `section_X` = in una sua sezione "
            "dedicata).\n"
            "- TAG da usare: "
            f'`<video src="{brief.video_filename}" controls playsinline preload="metadata" '
            'class="w-full max-w-3xl mx-auto rounded-xl shadow-lg"></video>`.\n'
            "- NON usare iframe / YouTube embed: l'mp4 e` self-hosted."
        )
    return "\n".join(parts)


def _format_custom_code(brief: LandingBrief) -> str:
    head_blob = (brief.custom_code_head or "").strip()
    body_blob = (brief.custom_code_body or "").strip()
    if not head_blob and not body_blob:
        return ""
    parts = ["## Codice custom da embeddare VERBATIM (no modifiche, no commenti)"]
    if head_blob:
        parts.append(
            "### Da inserire DENTRO `<head>` (es. tracking pixel, schema.org, font extra)\n"
            "```\n"
            f"{head_blob}\n"
            "```"
        )
    if body_blob:
        parts.append(
            "### Da inserire IN FONDO al `<body>` prima di `</body>` "
            "(es. chat widget, script di terze parti)\n"
            "```\n"
            f"{body_blob}\n"
            "```"
        )
    parts.append(
        "Non riformattare, non commentare, non rinominare variabili. Va embeddato "
        "esattamente cosi come appare."
    )
    return "\n".join(parts)


def _user_prompt(brief: LandingBrief) -> str:
    color_lines = "\n".join(f"  - {k}: {v}" for k, v in brief.brand_colors_hex.items())
    references_block = (
        f"\n## Reference (landing/esempi che l'operatore vuole come ispirazione strutturale)\n"
        f"{brief.references.strip()}\n"
        "Studia ritmo, gerarchia, lunghezze. NON copiare testo/headline letterali.\n"
        if (brief.references or "").strip()
        else ""
    )
    custom_code_block = _format_custom_code(brief)
    asset_block = _format_asset_section(brief)

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
{references_block}
{asset_block}

{custom_code_block}

---

Sei tu il copywriter. Decidi struttura, headline, subheadline, sezioni, bullet,
testimonial style/placement (solo se il brief offre proof reale — altrimenti
salta), CTA, FAQ. Scrivi italiano persuasivo, concreto, anti-fuffa.

Restituisci SOLO l'output delimitato come da istruzioni di sistema.
"""


_PT_DELIM = "===PAGE_TITLE==="
_MD_DELIM = "===META_DESCRIPTION==="
_SLOTS_DELIM = "===IMAGE_SLOTS==="
_HTML_DELIM = "===HTML==="
_END_DELIM = "===END==="


_VALID_ROLES: set[str] = {"banner", "background", "inline"}


def _parse_image_slots(block: str) -> tuple[ImageSlot, ...]:
    """Parse the IMAGE_SLOTS block.

    Accepts either:
      - `name | role | description`   (preferred, role ∈ banner/background/inline)
      - `name | description`          (legacy, role defaults to 'inline')
    """
    slots: list[ImageSlot] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.lower() in ("(none)", "none"):
            continue
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and parts[1].lower() in _VALID_ROLES:
            name_raw, role_raw, desc_parts = parts[0], parts[1].lower(), parts[2:]
            desc = " | ".join(desc_parts).strip()
            role: SlotRole = role_raw  # type: ignore[assignment]
        else:
            name_raw = parts[0]
            desc = " | ".join(parts[1:]).strip()
            role = "inline"
        name = name_raw.lower().replace(" ", "_")
        if not name:
            continue
        slots.append(ImageSlot(name=name, description=desc, role=role))
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

    Per role:
      - banner   → rimuove l'`<img>` (Claude lo ha messo dentro un
                   `<section class="my-12">`, che resta vuoto e si collassa
                   coi margin — accettabile come fallback);
      - background → rimuove l'`<img>` ma lascia l'overlay div: la sezione
                     conserva il colore di overlay come fallback;
      - inline   → rimuove solo l'`<img>`.

    Conservative: tocca solo i tag <img>, non i loro wrapper. Claude e`
    istruito a designare layout che si compongono anche senza l'immagine.
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


def _stream_to_landing(client: Anthropic, system: str, user_msg: str) -> LandingPage:
    """Stream a single Claude call and parse the delimited landing output."""
    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=24000,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for _ in stream.text_stream:
            pass
        final = stream.get_final_message()

    text = "".join(block.text for block in final.content if block.type == "text")
    if final.stop_reason == "max_tokens":
        raise ValueError(
            "Claude hit the max_tokens limit before finishing the page. "
            "Shorten the brief, or raise max_tokens further."
        )
    return _parse_delimited(text)


def revise_landing(
    *,
    api_key: str,
    brief: LandingBrief,
    current: LandingPage,
    feedback: str,
) -> LandingPage:
    """Apply natural-language edits to an existing landing.

    Claude returns a full new version in the same delimited format. Slots
    not mentioned in the feedback should be preserved verbatim.
    """
    client = Anthropic(api_key=api_key)
    slot_names = ", ".join(s.name for s in current.image_slots) or "(none)"
    user_msg = (
        f"{_user_prompt(brief)}\n\n"
        f"## Versione corrente della landing\n"
        f"page_title: {current.page_title}\n"
        f"meta_description: {current.meta_description}\n"
        f"image_slots dichiarati: {slot_names}\n\n"
        f"HTML attuale:\n"
        f"---HTML_BEGIN---\n{current.html}\n---HTML_END---\n\n"
        f"## Modifiche richieste\n{feedback.strip()}\n\n"
        "Applica SOLO le modifiche richieste e restituisci la landing "
        "AGGIORNATA nello stesso formato di sistema "
        "(===PAGE_TITLE=== / ===META_DESCRIPTION=== / ===IMAGE_SLOTS=== / "
        "===HTML=== / ===END===). Tutto ciò che il feedback non menziona "
        "deve restare identico — testo, classi Tailwind, struttura, slot "
        "immagine. Non aggiungere sezioni che il feedback non chiede.\n\n"
        "## Linee guida specifiche per modifiche di LAYOUT/TYPOGRAFIA\n"
        "Quando l'operatore chiede modifiche al modo in cui IL TESTO E` "
        "DISPOSTO (numero di righe, dimensione, allineamento, line-height, "
        "spaziatura), NON limitarti a riformulare la frase: applica modifiche "
        "ATOMICHE all'HTML/Tailwind in modo che il risultato sia VISIBILE.\n"
        "Esempi specifici:\n"
        "  • \"metti la headline su N righe\" → due strade combinabili:\n"
        "      (a) inserisci esplicitamente uno o più tag <br> nei punti "
        "naturali di pausa (`Prima riga<br>Seconda riga`) per forzare il "
        "wrap su desktop;\n"
        "      (b) restringi la `max-w-*` dell'elemento contenitore in modo "
        "che il wrap naturale produca esattamente N righe a viewport "
        "desktop (es. h1: `max-w-3xl` per ~2 righe, `max-w-2xl` per ~3 "
        "righe, sempre con `mx-auto` se centrata);\n"
        "      (c) se serve, accorcia il testo della headline per stare in "
        "N righe — ma SOLO se l'operatore lo chiede o se senza accorciarla "
        "il wrap non funziona.\n"
        "  • \"più grande / più piccola\" → cambia `text-*` (es. da "
        "`text-4xl md:text-6xl` a `text-5xl md:text-7xl`).\n"
        "  • \"più spazio sopra/sotto\" → cambia `mt-*` / `mb-*` o `py-*` "
        "della sezione.\n"
        "  • \"centra / allinea a sinistra\" → cambia `text-center` / "
        "`text-left` (e relative `items-*` sul flex container).\n"
        "  • \"colore in X\" → cambia la classe Tailwind di colore "
        "(`text-brand-primary`, `bg-brand-accent`, ecc.) — NON usare colori "
        "inline `style=`.\n"
        "Se l'operatore dice \"non lo fa\" significa che la modifica "
        "precedente non era visibile a video: applica modifiche più "
        "decise (es. forza `<br>` invece di sperare nel wrap naturale)."
    )
    return _stream_to_landing(client, _system_prompt(), user_msg)


def generate_landing(api_key: str, brief: LandingBrief) -> LandingPage:
    """Call Claude with the brief and return a LandingPage. Raises on failure."""
    client = Anthropic(api_key=api_key)
    return _stream_to_landing(client, _system_prompt(), _user_prompt(brief))
