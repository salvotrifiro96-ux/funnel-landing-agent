"""Section-based image placement for landing pages.

Estrae le sezioni dell'HTML generato da Claude e permette all'operatore
di decidere ESATTAMENTE dove posizionare un'immagine per ogni sezione:

    Placement = 'none' | 'banner_top' | 'banner_bottom'
              | 'background'
              | 'inline_left' | 'inline_right' | 'inline_above' | 'inline_below'

Il flusso è:
  1. `extract_sections(html)`         -> tuple[SectionInfo]
  2. operatore sceglie un ImagePlacement per ogni sezione
  3. `apply_image_placements(html, plans, image_resolver)` -> str

`image_resolver(slot_name)` ritorna l'URL/src da usare nell'`<img>`. In
preview locale, è una data URI base64; in publish, è il filename
relativo (`img-<slot>.jpg`).

Le sezioni sono identificate dai tag `<section>...</section>` di primo
livello. Il titolo della sezione è euristicamente il primo <h1>/<h2>/<h3>
contenuto; se assente, si usa "Sezione N".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable, Literal

Placement = Literal[
    "none",
    "banner_top",
    "banner_bottom",
    "background",
    "inline_left",
    "inline_right",
    "inline_above",
    "inline_below",
]

ALL_PLACEMENTS: tuple[Placement, ...] = (
    "none",
    "banner_top",
    "banner_bottom",
    "background",
    "inline_left",
    "inline_right",
    "inline_above",
    "inline_below",
)


@dataclass(frozen=True)
class SectionInfo:
    """Una sezione `<section>...</section>` identificata nell'HTML."""

    index: int            # 1-based
    start: int            # offset del `<section` di apertura
    end: int              # offset DOPO `</section>` di chiusura
    title: str            # titolo derivato (primo h1/h2/h3) o "Sezione N"
    section_id: str       # id attribute se presente, altrimenti ""


@dataclass(frozen=True)
class ImagePlacement:
    """Scelta dell'operatore per una sezione."""

    section_index: int
    placement: Placement
    slot_name: str        # snake_case, univoco — usato per data-img-slot e src
    alt_text: str = ""    # alt per l'<img>, opzionale


# ── Section extraction ───────────────────────────────────────────────


_SECTION_OPEN = re.compile(r"<section\b", re.IGNORECASE)
_SECTION_CLOSE = re.compile(r"</section\s*>", re.IGNORECASE)
_HEADING_TAG = re.compile(
    r"<(h[1-3])\b[^>]*>(.*?)</\1>",
    re.IGNORECASE | re.DOTALL,
)
_ID_ATTR = re.compile(r'\bid=["\']([^"\']+)["\']', re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return _TAG.sub("", s).strip()


def _find_matching_close(html: str, open_idx: int) -> int:
    """Dato `<section` a `open_idx`, trova l'offset del `</section>`
    corrispondente gestendo correttamente l'annidamento (raro).
    Ritorna l'offset DOPO il `</section>`. -1 se non trovato.
    """
    depth = 0
    pos = open_idx
    while pos < len(html):
        next_open = _SECTION_OPEN.search(html, pos)
        next_close = _SECTION_CLOSE.search(html, pos)
        if next_close is None:
            return -1
        if next_open and next_open.start() < next_close.start():
            depth += 1
            pos = next_open.end()
        else:
            if depth == 0:
                return next_close.end()
            depth -= 1
            pos = next_close.end()
    return -1


def extract_sections(html: str) -> tuple[SectionInfo, ...]:
    """Trova le sezioni `<section>...</section>` di primo livello.

    Non scende dentro sezioni annidate: solo i `<section>` direttamente nel
    `<body>` (o equivalentemente, quelli non contenuti in un altro
    `<section>` già emerso).
    """
    sections: list[SectionInfo] = []
    pos = 0
    idx = 0
    while pos < len(html):
        m = _SECTION_OPEN.search(html, pos)
        if not m:
            break
        start = m.start()
        # Trova la fine del tag di apertura `<section ... >`
        tag_close = html.find(">", m.end())
        if tag_close == -1:
            break
        end = _find_matching_close(html, tag_close + 1)
        if end == -1:
            break
        idx += 1
        inner = html[tag_close + 1: end - len("</section>")]
        # Titolo: primo h1/h2/h3
        title = ""
        if (hm := _HEADING_TAG.search(inner)):
            title = _strip_tags(hm.group(2))[:120]
        if not title:
            title = f"Sezione {idx}"
        # ID attribute (opening tag only)
        open_tag = html[start: tag_close + 1]
        section_id = ""
        if (im := _ID_ATTR.search(open_tag)):
            section_id = im.group(1)
        sections.append(
            SectionInfo(
                index=idx,
                start=start,
                end=end,
                title=title,
                section_id=section_id,
            )
        )
        pos = end
    return tuple(sections)


# ── Image injection ──────────────────────────────────────────────────


_BANNER_TPL = (
    '<section class="my-12 sm:my-16" data-injected-banner="{slot}">'
    '<img src="{src}" alt="{alt}" data-img-slot="{slot}" '
    'data-img-role="banner" class="w-full h-auto block">'
    '</section>'
)


def _banner_html(slot: str, src: str, alt: str) -> str:
    return _BANNER_TPL.format(
        slot=_esc_attr(slot),
        src=_esc_attr(src),
        alt=_esc_attr(alt or ""),
    )


def _esc_attr(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace('"', "&quot;")
         .replace("'", "&#39;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


def _wrap_section_with_background(section_html: str, slot: str, src: str) -> str:
    """Modifica il tag di apertura `<section ...>` per renderlo relativo e
    inserisce SUBITO dentro un `<img>` background + un overlay scuro."""
    # Aggiungi classi necessarie
    open_match = re.match(r"<section\b([^>]*)>", section_html, flags=re.IGNORECASE)
    if not open_match:
        # Fallback: ritorna la sezione invariata
        return section_html
    attrs = open_match.group(1)
    # Estrai class esistente
    class_match = re.search(r'\bclass=["\']([^"\']*)["\']', attrs, flags=re.IGNORECASE)
    extra_classes = "relative isolate overflow-hidden"
    if class_match:
        merged = (class_match.group(1) + " " + extra_classes).strip()
        new_attrs = re.sub(
            r'\bclass=["\'][^"\']*["\']',
            f'class="{merged}"',
            attrs,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        new_attrs = f'{attrs} class="{extra_classes}"'
    new_open = (
        f'<section{new_attrs} data-injected-bg="{_esc_attr(slot)}">'
    )
    bg = (
        f'<img src="{_esc_attr(src)}" alt="" aria-hidden="true" '
        f'data-img-slot="{_esc_attr(slot)}" data-img-role="background" '
        f'class="absolute inset-0 -z-10 h-full w-full object-cover">'
        f'<div class="absolute inset-0 -z-10 bg-black/50"></div>'
    )
    body = section_html[open_match.end():]
    return f"{new_open}{bg}{body}"


_INLINE_WRAPPER_TPL = (
    '<div class="my-6 sm:my-8 {extra}" data-injected-inline="{slot}">'
    '<img src="{src}" alt="{alt}" data-img-slot="{slot}" '
    'data-img-role="inline" class="{img_class}">'
    '</div>'
)


def _inline_above_below(slot: str, src: str, alt: str, where: str) -> str:
    """`where` ∈ 'above','below' — img centrata a tutta larghezza max-w-3xl."""
    return _INLINE_WRAPPER_TPL.format(
        slot=_esc_attr(slot),
        src=_esc_attr(src),
        alt=_esc_attr(alt or ""),
        extra="flex justify-center",
        img_class="block max-w-3xl w-full h-auto rounded-xl shadow-md",
    )


def _wrap_section_with_inline_lr(
    section_html: str, slot: str, src: str, alt: str, side: str
) -> str:
    """`side` ∈ 'left','right' — converte la sezione in un layout
    flex 2-colonne con l'immagine sul lato richiesto."""
    open_match = re.match(r"<section\b([^>]*)>", section_html, flags=re.IGNORECASE)
    if not open_match:
        return section_html
    attrs = open_match.group(1)
    body = section_html[open_match.end():-len("</section>")]
    # Estrai class della section e aggiungi padding se manca
    class_match = re.search(r'\bclass=["\']([^"\']*)["\']', attrs, flags=re.IGNORECASE)
    if class_match:
        new_attrs = attrs
    else:
        new_attrs = f'{attrs} class="py-12 sm:py-16 px-4"'
    direction = "md:flex-row-reverse" if side == "right" else "md:flex-row"
    img_tag = (
        f'<img src="{_esc_attr(src)}" alt="{_esc_attr(alt or "")}" '
        f'data-img-slot="{_esc_attr(slot)}" data-img-role="inline" '
        f'class="w-full md:w-1/2 h-auto rounded-xl shadow-md object-cover">'
    )
    wrapped_body = (
        f'<div class="max-w-6xl mx-auto flex flex-col {direction} '
        f'items-center gap-8 lg:gap-12" data-injected-inline="{_esc_attr(slot)}">'
        f'{img_tag}'
        f'<div class="w-full md:w-1/2">{body}</div>'
        f'</div>'
    )
    return f'<section{new_attrs}>{wrapped_body}</section>'


def apply_image_placements(
    html: str,
    placements: tuple[ImagePlacement, ...],
    image_resolver: Callable[[str], str | None],
) -> str:
    """Ritorna il nuovo HTML con le immagini iniettate alle posizioni
    richieste. Le sezioni vengono riprocessate da quella con index più
    alto verso la più bassa per non invalidare gli offset durante
    l'inserimento."""
    if not placements:
        return html
    sections = extract_sections(html)
    if not sections:
        return html
    by_index = {s.index: s for s in sections}

    # Ordina dalla sezione più in fondo alla più in cima
    sorted_plans = sorted(
        [p for p in placements if p.placement != "none"],
        key=lambda p: p.section_index,
        reverse=True,
    )
    out = html
    for plan in sorted_plans:
        sec = by_index.get(plan.section_index)
        if sec is None:
            continue
        src = image_resolver(plan.slot_name)
        if not src:
            # Nessuna immagine effettivamente caricata: skip senza errore
            continue
        section_html = out[sec.start: sec.end]
        if plan.placement == "banner_top":
            insert = _banner_html(plan.slot_name, src, plan.alt_text)
            out = out[: sec.start] + insert + out[sec.start:]
        elif plan.placement == "banner_bottom":
            insert = _banner_html(plan.slot_name, src, plan.alt_text)
            out = out[: sec.end] + insert + out[sec.end:]
        elif plan.placement == "background":
            new_section = _wrap_section_with_background(
                section_html, plan.slot_name, src
            )
            out = out[: sec.start] + new_section + out[sec.end:]
        elif plan.placement in ("inline_left", "inline_right"):
            side = "left" if plan.placement == "inline_left" else "right"
            new_section = _wrap_section_with_inline_lr(
                section_html, plan.slot_name, src, plan.alt_text, side
            )
            out = out[: sec.start] + new_section + out[sec.end:]
        elif plan.placement in ("inline_above", "inline_below"):
            insert = _inline_above_below(
                plan.slot_name, src, plan.alt_text, plan.placement.split("_")[1]
            )
            if plan.placement == "inline_above":
                # subito dopo il tag di apertura `<section ...>`
                open_end = out.find(">", sec.start) + 1
                out = out[: open_end] + insert + out[open_end:]
            else:  # inline_below
                # subito prima del `</section>`
                close_start = sec.end - len("</section>")
                out = out[: close_start] + insert + out[close_start:]
    return out


# ── Helpers ─────────────────────────────────────────────────────────


def derive_slot_name(section_index: int, placement: Placement) -> str:
    """Naming convention dei slot generati dall'operatore via placement."""
    return f"sec{section_index:02d}_{placement}"


def with_slot_name(plan: ImagePlacement, slot_name: str) -> ImagePlacement:
    return replace(plan, slot_name=slot_name)
