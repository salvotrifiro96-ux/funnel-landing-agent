"""Funnel Landing Agent — Streamlit UI for generating + publishing landing pages.

Flow:
  0. Brief (sidebar)            → client, slug, branding
  1. Content                    → headline, value props, sections, form HTML
  2. Hero image                 → prompt → Higgsfield Nano Banana Pro
  3. Generate                   → Claude HTML/Tailwind
  4. Preview                    → iframe
  5. Publish                    → push to GitHub → live on landing.<domain>/pages/<slug>/
"""
from __future__ import annotations

import os
import traceback

import streamlit as st
from dotenv import load_dotenv

from agent.github_publish import GitHubConfig, publish_landing
from agent.higgsfield import HiggsfieldCreds, HiggsfieldError, generate_hero_image
from agent.landing_gen import LandingBrief, LandingPage, generate_landing
from agent.usage_log import ensure_schema as _ensure_usage_schema, log_event as _log_event

load_dotenv()


def _secret(key: str, default: str = "") -> str:
    val = os.getenv(key)
    if val:
        return val
    try:
        return st.secrets.get(key, default)
    except (FileNotFoundError, AttributeError):
        return default


ANTHROPIC_API_KEY = _secret("ANTHROPIC_API_KEY")
APP_PASSWORD = _secret("APP_PASSWORD")

st.set_page_config(page_title="Funnel Landing Agent", layout="wide", page_icon="🛬")

if not st.session_state.get("_usage_schema_ready"):
    _ensure_usage_schema()
    st.session_state["_usage_schema_ready"] = True


def _password_gate() -> None:
    if not APP_PASSWORD:
        return
    if st.session_state.get("authed"):
        return
    st.title("Funnel Landing Agent")
    pw = st.text_input("Password", type="password", key="pw_input")
    if st.button("Enter"):
        if pw == APP_PASSWORD:
            st.session_state.authed = True
            _log_event("login_success")
            st.rerun()
        else:
            _log_event("login_failed")
            st.error("Wrong password")
    st.stop()


_password_gate()


DEFAULT_STATE: dict[str, object] = {
    "step": "brief",
    "brief": None,
    "hero_prompt": "",
    "hero_image_bytes": None,
    "landing": None,
    "publish_result": None,
    "error": None,
}
for k, v in DEFAULT_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v


def _set_step(s: str) -> None:
    st.session_state.step = s
    st.session_state.error = None


def _show_error_if_any() -> None:
    err = st.session_state.get("error")
    if err:
        st.error(err)


def _sidebar() -> None:
    st.sidebar.title("🛬 Brief")
    with st.sidebar.form("brief_form"):
        client_name = st.text_input("Cliente", placeholder="Leone Master School")
        slug = st.text_input(
            "Slug URL (a-z, 0-9, trattini)",
            placeholder="corso-meta-ads",
            help="L'URL finale sarà https://landing.tuodominio.it/pages/<slug>/",
        )
        objective = st.text_input(
            "Obiettivo della landing",
            placeholder="Raccogliere lead per il corso Meta Ads di novembre",
        )
        target_audience = st.text_area(
            "Target audience",
            placeholder="Donne 30-45 in cerca di una svolta professionale dopo i figli",
            height=80,
        )
        st.markdown("**Branding**")
        primary = st.color_picker("Colore primario", value="#0A2540")
        secondary = st.color_picker("Colore secondario", value="#F4A261")
        accent = st.color_picker("Colore accent (CTA)", value="#E76F51")
        font_family = st.selectbox(
            "Font (Google Fonts)",
            ["Inter", "Poppins", "Montserrat", "Roboto", "Playfair Display", "Lora", "DM Sans"],
            index=0,
        )
        style_keywords = st.text_input(
            "Stile (keyword separate da virgola)",
            value="modern, conversion-focused, clean",
        )
        submitted = st.form_submit_button("💾 Save brief", use_container_width=True)

    if submitted:
        required = {
            "Cliente": client_name,
            "Slug": slug,
            "Obiettivo": objective,
            "Target": target_audience,
        }
        missing = [k for k, v in required.items() if not v.strip()]
        if missing:
            st.sidebar.error(f"Mancano: {', '.join(missing)}")
            return
        st.session_state.brief_partial = {
            "client_name": client_name.strip(),
            "slug": slug.strip().lower().replace(" ", "-"),
            "objective": objective.strip(),
            "target_audience": target_audience.strip(),
            "brand_colors_hex": {"primary": primary, "secondary": secondary, "accent": accent},
            "font_family": font_family,
            "style_keywords": style_keywords.strip(),
        }
        if st.session_state.step == "brief":
            _set_step("content")
        st.rerun()

    if st.sidebar.button("🔄 Reset session", use_container_width=True):
        for k, v in DEFAULT_STATE.items():
            st.session_state[k] = v
        st.session_state.pop("brief_partial", None)
        st.rerun()


def _step_brief() -> None:
    st.title("🛬 Funnel Landing Agent")
    st.markdown(
        "Compila il **brief** nella sidebar, poi premi **Save brief**. "
        "Procederai con i contenuti, l'immagine hero e infine la pubblicazione."
    )


def _step_content() -> None:
    partial = st.session_state.get("brief_partial")
    if not partial:
        _set_step("brief")
        st.rerun()
        return

    st.title("Step 1 · Contenuti & Form")
    st.caption(f"Cliente: **{partial['client_name']}** · Slug: `{partial['slug']}`")

    with st.form("content_form"):
        headline_hint = st.text_area(
            "Headline guida (l'agente la raffinerà)",
            height=60,
            placeholder="Diventa Meta Ads Specialist in 8 settimane",
        )
        subheadline_hint = st.text_area(
            "Sottotitolo guida",
            height=60,
            placeholder="Dal primo pixel al primo cliente fatturato — in italiano, senza fuffa.",
        )
        value_props = st.text_area(
            "Bullet points / value props (uno per riga)",
            height=140,
            placeholder=(
                "8 settimane di formazione live\n"
                "Ti seguiamo fino al tuo primo cliente\n"
                "Material e replay illimitati\n"
                "Community privata da 200+ studenti"
            ),
        )
        sections_raw = st.multiselect(
            "Sezioni opzionali da includere",
            ["FAQ", "Testimonial", "Bonus / garanzia", "Chi siamo", "Programma dettagliato", "Video"],
            default=["FAQ", "Testimonial"],
        )
        primary_cta = st.text_input("Etichetta CTA primaria", value="Iscriviti ora")
        secondary_info = st.text_area(
            "Info aggiuntive / disclaimer footer (opzionale)",
            height=60,
        )
        st.markdown("**Form HTML** — incolla qui il codice del tuo form (rimane intatto):")
        form_html = st.text_area(
            "Codice HTML del form",
            height=200,
            placeholder='<form action="https://hooks.example.com/lead" method="POST">...</form>',
        )

        submitted = st.form_submit_button("➡️ Avanti: hero image", type="primary")

    if submitted:
        if not value_props.strip() or not form_html.strip():
            st.error("Value props e form HTML sono obbligatori.")
            return
        st.session_state.brief_partial = {
            **partial,
            "headline_hint": headline_hint.strip(),
            "subheadline_hint": subheadline_hint.strip(),
            "value_props": value_props.strip(),
            "sections": tuple(sections_raw),
            "primary_cta_label": primary_cta.strip(),
            "secondary_info": secondary_info.strip(),
            "form_html": form_html.strip(),
        }
        _set_step("hero")
        st.rerun()


def _step_hero() -> None:
    st.title("Step 2 · Immagine hero")
    partial = st.session_state.get("brief_partial", {})
    st.caption(f"Cliente: **{partial.get('client_name','?')}** · Slug: `{partial.get('slug','?')}`")

    default_prompt = (
        f"editorial hero image for a landing page about {partial.get('objective','')}, "
        f"target: {partial.get('target_audience','')}. "
        f"Style: {partial.get('style_keywords','')}, photographic, soft natural light, "
        "no text, 16:9, professional, optimistic mood."
    )
    st.session_state.hero_prompt = st.text_area(
        "Prompt per Higgsfield Nano Banana Pro",
        value=st.session_state.hero_prompt or default_prompt,
        height=120,
        help="L'immagine viene generata in 16:9. Niente testo nell'immagine.",
    )

    cols = st.columns([1, 1, 4])
    if cols[0].button("⬅️ Contenuti"):
        _set_step("content")
        st.rerun()
    if cols[1].button("🎨 Genera hero", type="primary"):
        with st.spinner("Higgsfield sta generando l'immagine (1-2 min)…"):
            try:
                creds = HiggsfieldCreds(
                    clerk_client=_secret("HIGGSFIELD_CLERK_CLIENT"),
                    session_id=_secret("HIGGSFIELD_SESSION_ID"),
                )
                img_bytes = generate_hero_image(
                    st.session_state.hero_prompt,
                    aspect="16:9",
                    creds=creds,
                )
                st.session_state.hero_image_bytes = img_bytes
                _log_event(
                    "hero_generated",
                    payload={
                        "slug": partial.get("slug"),
                        "client_name": partial.get("client_name"),
                        "image_kb": len(img_bytes) // 1024,
                    },
                )
            except HiggsfieldError as e:
                st.session_state.error = f"Higgsfield error: {e}"
            except Exception as e:
                st.session_state.error = f"Unexpected error: {e}\n\n{traceback.format_exc()}"

    if st.session_state.hero_image_bytes:
        st.image(st.session_state.hero_image_bytes, caption="Hero generata", use_container_width=True)
        if st.button("➡️ Avanti: genera HTML", type="primary"):
            _set_step("generate")
            st.rerun()


def _build_brief() -> LandingBrief:
    p = st.session_state.brief_partial
    return LandingBrief(
        client_name=p["client_name"],
        slug=p["slug"],
        objective=p["objective"],
        target_audience=p["target_audience"],
        headline_hint=p.get("headline_hint", ""),
        subheadline_hint=p.get("subheadline_hint", ""),
        value_props=p.get("value_props", ""),
        sections=p.get("sections", ()),
        primary_cta_label=p.get("primary_cta_label", "Iscriviti"),
        secondary_info=p.get("secondary_info", ""),
        form_html=p.get("form_html", ""),
        brand_colors_hex=p["brand_colors_hex"],
        font_family=p["font_family"],
        style_keywords=p["style_keywords"],
        hero_image_path="hero.jpg",
    )


def _step_generate() -> None:
    st.title("Step 3 · Genera HTML")
    if not st.session_state.hero_image_bytes:
        st.error("Genera prima l'immagine hero.")
        if st.button("⬅️ Hero"):
            _set_step("hero")
            st.rerun()
        return

    brief = _build_brief()
    st.caption(f"Cliente: **{brief.client_name}** · Slug: `{brief.slug}` · Stile: {brief.style_keywords}")

    if st.session_state.landing is None:
        if st.button("✨ Generate landing HTML", type="primary"):
            with st.spinner("Claude sta scrivendo la landing… (30-60s)"):
                try:
                    landing = generate_landing(api_key=ANTHROPIC_API_KEY, brief=brief)
                    st.session_state.landing = landing
                    _log_event(
                        "landing_generated",
                        payload={
                            "slug": brief.slug,
                            "client_name": brief.client_name,
                            "page_title": landing.page_title,
                            "html_kb": len(landing.html) // 1024,
                        },
                    )
                    st.rerun()
                except Exception as e:
                    st.session_state.error = f"Generation failed: {e}\n\n{traceback.format_exc()}"
        return

    landing: LandingPage = st.session_state.landing
    st.success(f"HTML generato — {len(landing.html):,} caratteri")
    st.markdown(f"**Page title**: {landing.page_title}")
    st.markdown(f"**Meta description**: {landing.meta_description}")

    cols = st.columns([1, 1, 3])
    if cols[0].button("⬅️ Hero"):
        _set_step("hero")
        st.rerun()
    if cols[1].button("🔁 Re-generate"):
        st.session_state.landing = None
        st.rerun()
    if cols[2].button("👁 Anteprima → Pubblica", type="primary"):
        _set_step("preview")
        st.rerun()


def _step_preview() -> None:
    st.title("Step 4 · Anteprima")
    landing: LandingPage = st.session_state.landing
    if not landing:
        _set_step("generate")
        st.rerun()
        return

    st.components.v1.html(landing.html, height=800, scrolling=True)

    with st.expander("HTML sorgente"):
        st.code(landing.html, language="html")

    cols = st.columns([1, 1, 3])
    if cols[0].button("⬅️ Generate"):
        _set_step("generate")
        st.rerun()
    if cols[1].button("🔁 Re-generate"):
        st.session_state.landing = None
        _set_step("generate")
        st.rerun()
    if cols[2].button("🚀 Pubblica su GitHub Pages", type="primary"):
        _publish()


def _publish() -> None:
    brief = _build_brief()
    landing: LandingPage = st.session_state.landing
    image_bytes: bytes = st.session_state.hero_image_bytes

    cfg = GitHubConfig(
        token=_secret("GITHUB_TOKEN"),
        username=_secret("GITHUB_USERNAME"),
        repo=_secret("GITHUB_PAGES_REPO"),
        base_url=_secret("LANDING_BASE_URL"),
    )

    with st.spinner("Pubblicazione su GitHub Pages in corso…"):
        try:
            result = publish_landing(
                cfg,
                slug=brief.slug,
                html=landing.html,
                image_bytes=image_bytes,
            )
            st.session_state.publish_result = result
            _log_event(
                "landing_published",
                payload={
                    "slug": brief.slug,
                    "client_name": brief.client_name,
                    "public_url": result.public_url,
                    "html_commit_sha": result.html_commit_sha,
                },
            )
            _set_step("done")
            st.rerun()
        except Exception as e:
            st.session_state.error = f"Publish failed: {e}\n\n{traceback.format_exc()}"


def _step_done() -> None:
    st.title("✅ Landing pubblicata")
    result = st.session_state.publish_result
    st.success(f"Live a breve su: {result.public_url}")
    st.info(
        "GitHub Pages può impiegare 30-90 secondi prima di servire la nuova "
        "landing. Se ricevi 404 al primo tentativo, ricarica dopo un minuto."
    )
    st.code(result.public_url, language=None)
    st.caption(f"Commit HTML: `{result.html_commit_sha[:8]}` · Hero: `{result.image_commit_sha[:8]}`")

    if st.button("🔄 Nuova landing"):
        for k, v in DEFAULT_STATE.items():
            st.session_state[k] = v
        st.session_state.pop("brief_partial", None)
        st.rerun()


_sidebar()
_show_error_if_any()

step = st.session_state.step
if step == "brief":
    _step_brief()
elif step == "content":
    _step_content()
elif step == "hero":
    _step_hero()
elif step == "generate":
    _step_generate()
elif step == "preview":
    _step_preview()
elif step == "done":
    _step_done()
