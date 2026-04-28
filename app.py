"""Funnel Landing Agent — Streamlit UI for generating + publishing landing pages.

Flow:
  0. Brief (sidebar)            → client, slug, branding
  1. Content                    → project context + form HTML
  2. Generate                   → Claude HTML/Tailwind (no images)
  3. Preview                    → iframe
  4. Publish                    → push to GitHub → live on landing.<domain>/pages/<slug>/
"""
from __future__ import annotations

import os
import traceback

import streamlit as st
from dotenv import load_dotenv

from agent.github_publish import (
    GitHubConfig,
    SetupResult,
    publish_landing,
    setup_hosting_repo,
)
from agent.image_gen import (
    ImageGenError,
    aspect_for_slot,
    generate_image,
)
from agent.landing_gen import (
    LandingBrief,
    LandingPage,
    generate_landing,
    revise_landing,
    strip_skipped_image_slots,
)
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
OPENAI_API_KEY = _secret("OPENAI_API_KEY")
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
    "landing": None,
    "slot_choices": {},   # {slot_name: 'skip' | 'upload' | 'generate'}
    "slot_images": {},    # {slot_name: bytes}
    "slot_prompts": {},   # {slot_name: prompt str}
    "publish_result": None,
    "error": None,
    "hosting_mode": "quick",     # 'quick' or 'custom'
    "hosting_custom": None,      # dict when mode='custom' and verified
    "hosting_setup_result": None,  # SetupResult when 'custom' verified
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


def _hosting_sidebar() -> None:
    st.sidebar.title("🌐 Hosting")
    mode = st.sidebar.radio(
        "Dove pubblichi la landing?",
        options=["quick", "custom"],
        index=0 if st.session_state.get("hosting_mode", "quick") == "quick" else 1,
        format_func=lambda m: {
            "quick": "🚀 Link veloce (consigliato)",
            "custom": "🌍 Dominio personalizzato",
        }[m],
        key="hosting_mode_radio",
        help=(
            "**Link veloce**: la landing va sul mio dominio "
            "(landing.leonemasterschool.it/pages/<slug>/) — zero setup.\n\n"
            "**Dominio personalizzato**: configura il TUO dominio "
            "(es. landing.tuobrand.com). Serve un GitHub PAT e accesso DNS."
        ),
    )
    st.session_state.hosting_mode = mode

    if mode == "quick":
        base = _secret("LANDING_BASE_URL", "")
        if base:
            st.sidebar.success(f"Le landing finiranno su `{base}/pages/<slug>/`")
        return

    # mode == "custom"
    saved = st.session_state.get("hosting_custom") or {}
    with st.sidebar.expander("⚙️ Setup dominio personalizzato", expanded=not saved):
        st.markdown(
            "1. Crea un GitHub Personal Access Token con scope `repo` "
            "[qui](https://github.com/settings/tokens/new) (durata 90gg, "
            "spunta `repo`).\n"
            "2. Compila i campi qui sotto e clicca **Verifica & setup**.\n"
            "3. Configura il DNS sul provider del tuo dominio "
            "(istruzioni dopo la verifica)."
        )
        with st.form("hosting_custom_form"):
            gh_token = st.text_input(
                "GitHub PAT",
                type="password",
                value=saved.get("token", ""),
            )
            gh_user = st.text_input(
                "GitHub username",
                value=saved.get("username", ""),
                placeholder="es. mario-rossi",
            )
            gh_repo = st.text_input(
                "Nome repo per le landing",
                value=saved.get("repo", "landing-pages"),
                help="Verrà creato se non esiste (pubblico, richiesto da GitHub Pages free).",
            )
            base_url = st.text_input(
                "URL base del dominio (con https://)",
                value=saved.get("base_url", ""),
                placeholder="https://landing.tuobrand.com",
            )
            submit = st.form_submit_button("✅ Verifica & setup", use_container_width=True)

        if submit:
            cfg = GitHubConfig(
                token=gh_token.strip(),
                username=gh_user.strip(),
                repo=gh_repo.strip() or "landing-pages",
                base_url=base_url.strip().rstrip("/"),
            )
            with st.spinner("Verifico credenziali e configuro il repo…"):
                try:
                    result: SetupResult = setup_hosting_repo(cfg)
                    st.session_state.hosting_custom = {
                        "token": cfg.token,
                        "username": cfg.username,
                        "repo": cfg.repo,
                        "base_url": cfg.base_url,
                    }
                    st.session_state.hosting_setup_result = result
                    _log_event(
                        "hosting_custom_setup",
                        payload={
                            "username": cfg.username,
                            "repo": cfg.repo,
                            "domain": result.custom_domain,
                            "repo_existed": result.repo_existed,
                        },
                    )
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Setup fallito: {e}")

    result = st.session_state.get("hosting_setup_result")
    if result and st.session_state.hosting_custom:
        st.sidebar.success(f"Repo `{st.session_state.hosting_custom['repo']}` pronto.")
        with st.sidebar.expander("📡 Istruzioni DNS", expanded=False):
            st.markdown(
                f"Sul provider DNS del dominio `{result.custom_domain}` "
                "aggiungi questo record:\n\n"
                f"- **Tipo**: `CNAME`\n"
                f"- **Nome / Host**: `{result.custom_domain.split('.')[0]}` "
                "(o lascia vuoto / `@` se il dominio è già esattamente quello)\n"
                f"- **Valore / Punta a**: `{result.cname_target}`\n"
                "- **TTL**: default\n\n"
                "Propagazione DNS: 5–30 minuti. Dopo la prima pubblicazione "
                "GitHub abilita HTTPS automaticamente."
            )
        if st.sidebar.button("🔄 Ricomincia setup hosting"):
            st.session_state.hosting_custom = None
            st.session_state.hosting_setup_result = None
            st.rerun()


def _sidebar() -> None:
    _hosting_sidebar()
    st.sidebar.divider()
    st.sidebar.title("🛬 Brief")
    with st.sidebar.form("brief_form"):
        client_name = st.text_input("Cliente", placeholder="Leone Master School")
        slug = st.text_input(
            "Slug URL (a-z, 0-9, trattini)",
            placeholder="corso-meta-ads",
            help="L'URL finale sarà https://landing.tuodominio.it/pages/<slug>/",
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
        required = {"Cliente": client_name, "Slug": slug}
        missing = [k for k, v in required.items() if not v.strip()]
        if missing:
            st.sidebar.error(f"Mancano: {', '.join(missing)}")
            return
        st.session_state.brief_partial = {
            "client_name": client_name.strip(),
            "slug": slug.strip().lower().replace(" ", "-"),
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

    st.title("Step 1 · Brief progetto & form")
    st.caption(f"Cliente: **{partial['client_name']}** · Slug: `{partial['slug']}`")
    st.markdown(
        "Racconta il progetto in modo libero. Più contesto fornisci "
        "(target reale, problemi che risolve, social proof, prezzi, deadline, "
        "vincoli, tono di voce, risultati documentati), migliore sarà la "
        "landing. Claude scrive headline, sottotitolo, bullet, struttura e "
        "CTA basandosi su questo testo."
    )

    with st.form("content_form"):
        project_context = st.text_area(
            "Contesto del progetto (libero, scrivi tutto quello che ti viene in mente)",
            height=380,
            placeholder=(
                "Esempio:\n"
                "Workshop online di 90 minuti per imprenditori e freelance "
                "che vogliono automatizzare il proprio lavoro con l'AI. "
                "Si tiene il 15 maggio alle 19:00 in diretta su Zoom. "
                "Costo: gratis, ma posti limitati a 200.\n\n"
                "Target: imprenditori 35-55, fatturato 100k-1M, lavorano 60h/settimana, "
                "perdono tempo in task ripetitivi (email, preventivi, fatture, "
                "post social).\n\n"
                "Obiettivo: lead per il follow-up commerciale del corso completo "
                "(corso da 1497€ che parte a giugno).\n\n"
                "Cosa imparano nel workshop:\n"
                "- come riconoscere i task automatizzabili nel proprio business\n"
                "- 5 tool AI gratuiti che usiamo internamente\n"
                "- demo live di un'automazione email + lead scoring\n\n"
                "Tono di voce: diretto, anti-fuffa, niente promesse di miracoli. "
                "Diciamo apertamente che l'AI non sostituisce le persone ma le libera "
                "dal lavoro morto.\n\n"
                "Social proof disponibile: abbiamo formato 1200+ imprenditori dal 2022, "
                "case study di Marco (architetto) che ha risparmiato 12 ore/settimana, "
                "+47 testimonianze video sul sito principale.\n\n"
                "Garanzia: nessuna, è gratis. Replay disponibile per 48h.\n\n"
                "Vincoli: la landing deve essere mobile-first (80% del traffico viene da Meta Ads), "
                "deve caricare in <2s, e il form deve avere solo nome + email + numero whatsapp."
            ),
        )
        st.markdown("**Form HTML** — incolla qui il codice del tuo form (rimane intatto):")
        form_html = st.text_area(
            "Codice HTML del form",
            height=200,
            placeholder='<form action="https://hooks.example.com/lead" method="POST">...</form>',
        )

        submitted = st.form_submit_button("➡️ Avanti: hero image", type="primary")

    if submitted:
        if not project_context.strip() or not form_html.strip():
            st.error("Contesto del progetto e form HTML sono entrambi obbligatori.")
            return
        st.session_state.brief_partial = {
            **partial,
            "project_context": project_context.strip(),
            "form_html": form_html.strip(),
        }
        _set_step("generate")
        st.rerun()


def _build_brief() -> LandingBrief:
    p = st.session_state.brief_partial
    return LandingBrief(
        client_name=p["client_name"],
        slug=p["slug"],
        project_context=p["project_context"],
        form_html=p["form_html"],
        brand_colors_hex=p["brand_colors_hex"],
        font_family=p["font_family"],
        style_keywords=p["style_keywords"],
    )


def _step_generate() -> None:
    st.title("Step 2 · Genera HTML")
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
    if cols[0].button("⬅️ Contenuti"):
        _set_step("content")
        st.rerun()
    if cols[1].button("🔁 Re-generate"):
        st.session_state.landing = None
        st.session_state.slot_choices = {}
        st.session_state.slot_images = {}
        st.session_state.slot_prompts = {}
        st.rerun()
    next_label = "👁 Avanti" if not landing.image_slots else "🖼 Aggiungi immagini"
    next_target = "preview" if not landing.image_slots else "images"
    if cols[2].button(next_label, type="primary"):
        _set_step(next_target)
        st.rerun()


def _step_images() -> None:
    st.title("Step 3 · Immagini (opzionali)")
    landing: LandingPage = st.session_state.landing
    if not landing or not landing.image_slots:
        _set_step("preview")
        st.rerun()
        return

    st.markdown(
        "Per ogni slot puoi: **saltarlo** (l'`<img>` viene rimosso, "
        "il design si adatta), **caricare** un file dal tuo computer, oppure "
        "**generarlo** con gpt-image-1 (~€0.02-0.25 a immagine)."
    )

    choices: dict[str, str] = dict(st.session_state.slot_choices)
    images: dict[str, bytes] = dict(st.session_state.slot_images)
    prompts: dict[str, str] = dict(st.session_state.slot_prompts)

    for slot in landing.image_slots:
        with st.container(border=True):
            st.markdown(f"### Slot: `{slot.name}`")
            st.caption(slot.description)

            choice = st.radio(
                "Cosa vuoi fare?",
                ["skip", "upload", "generate"],
                index=["skip", "upload", "generate"].index(choices.get(slot.name, "skip")),
                horizontal=True,
                key=f"choice_{slot.name}",
                format_func=lambda x: {"skip": "🚫 Salta", "upload": "📤 Carica", "generate": "✨ Genera"}[x],
            )
            choices[slot.name] = choice

            if choice == "upload":
                uploaded = st.file_uploader(
                    "Carica immagine (jpg/png)",
                    type=["jpg", "jpeg", "png"],
                    key=f"upload_{slot.name}",
                )
                if uploaded is not None:
                    images[slot.name] = uploaded.getvalue()
                    st.image(images[slot.name], use_container_width=True)
                elif slot.name in images:
                    st.image(images[slot.name], use_container_width=True)
                    st.caption("(immagine già caricata)")

            elif choice == "generate":
                prompt_default = prompts.get(slot.name) or slot.description
                prompt_value = st.text_area(
                    "Prompt gpt-image-1",
                    value=prompt_default,
                    height=100,
                    key=f"prompt_{slot.name}",
                )
                prompts[slot.name] = prompt_value
                quality = st.selectbox(
                    "Qualità",
                    ["high", "medium", "low"],
                    index=1,
                    key=f"quality_{slot.name}",
                    help="**high** ≈ €0.25 · **medium** ≈ €0.07 · **low** ≈ €0.02",
                )
                aspect = aspect_for_slot(slot.name)
                st.caption(f"Aspect ratio: `{aspect}` (auto)")

                if st.button(f"✨ Genera `{slot.name}`", key=f"gen_{slot.name}"):
                    if not OPENAI_API_KEY:
                        st.error("OPENAI_API_KEY non configurata nei secrets.")
                    else:
                        with st.spinner(f"gpt-image-1 → {slot.name} ({quality})…"):
                            try:
                                img_bytes = generate_image(
                                    prompt_value,
                                    api_key=OPENAI_API_KEY,
                                    aspect=aspect,
                                    quality=quality,
                                )
                                images[slot.name] = img_bytes
                                _log_event(
                                    "slot_image_generated",
                                    payload={
                                        "slot": slot.name,
                                        "quality": quality,
                                        "image_kb": len(img_bytes) // 1024,
                                    },
                                )
                            except ImageGenError as e:
                                st.session_state.error = f"Image generation error: {e}"
                            except Exception as e:
                                st.session_state.error = (
                                    f"Unexpected error: {e}\n\n{traceback.format_exc()}"
                                )

                if slot.name in images:
                    st.image(images[slot.name], use_container_width=True)
            else:
                images.pop(slot.name, None)

    st.session_state.slot_choices = choices
    st.session_state.slot_images = images
    st.session_state.slot_prompts = prompts

    cols = st.columns([1, 4])
    if cols[0].button("⬅️ Genera HTML"):
        _set_step("generate")
        st.rerun()
    if cols[1].button("👁 Anteprima → Pubblica", type="primary"):
        _set_step("preview")
        st.rerun()


def _kept_slots() -> set[str]:
    """Return the names of slots that have a real image attached."""
    images: dict[str, bytes] = st.session_state.get("slot_images") or {}
    return {name for name, payload in images.items() if payload}


def _compiled_html() -> str:
    """Return the HTML with `<img>` tags for skipped slots removed."""
    landing: LandingPage = st.session_state.landing
    return strip_skipped_image_slots(landing.html, _kept_slots())


def _compiled_html_for_preview() -> str:
    """Like _compiled_html but inlines kept images as data: URIs.

    Streamlit's iframe cannot resolve `src="img-xxx.jpg"` (files only
    exist after publish). For the local preview we replace those src
    attributes with base64 data URIs so the operator actually sees the
    images they uploaded/generated.
    """
    import base64
    import re

    html = _compiled_html()
    images: dict[str, bytes] = st.session_state.get("slot_images") or {}
    if not images:
        return html

    encoded: dict[str, str] = {
        slot: "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")
        for slot, payload in images.items()
        if payload
    }

    pattern = re.compile(
        r'(<img\b[^>]*\bdata-img-slot=["\']([^"\']+)["\'][^>]*>)',
        flags=re.IGNORECASE,
    )

    def rewrite(match: re.Match[str]) -> str:
        tag, slot = match.group(1), match.group(2).strip().lower()
        data_uri = encoded.get(slot)
        if not data_uri:
            return tag
        return re.sub(
            r'src=["\'][^"\']*["\']',
            f'src="{data_uri}"',
            tag,
            count=1,
            flags=re.IGNORECASE,
        )

    return pattern.sub(rewrite, html)


def _step_preview() -> None:
    st.title("Step 4 · Anteprima")
    landing: LandingPage = st.session_state.landing
    if not landing:
        _set_step("generate")
        st.rerun()
        return

    preview_html = _compiled_html_for_preview()

    cols_top = st.columns([1, 3])
    device = cols_top[0].radio(
        "Anteprima",
        ["🖥 Desktop", "📱 Mobile"],
        horizontal=True,
        key="preview_device",
    )

    if device == "📱 Mobile":
        framed = (
            '<div style="display:flex;justify-content:center;background:#1c1c1e;padding:24px 0;">'
            '<div style="width:390px;height:780px;border:8px solid #111;border-radius:36px;'
            'overflow:hidden;background:white;box-shadow:0 12px 40px rgba(0,0,0,.25);">'
            f'<iframe style="width:100%;height:100%;border:none;" srcdoc="{preview_html.replace(chr(34), "&quot;")}"></iframe>'
            '</div></div>'
        )
        st.components.v1.html(framed, height=820, scrolling=False)
    else:
        st.components.v1.html(preview_html, height=800, scrolling=True)

    n_kept = len(_kept_slots())
    n_total = len(landing.image_slots)
    if n_total:
        st.caption(f"Immagini attive: {n_kept}/{n_total}")

    with st.expander("HTML sorgente (compilato, senza data-uri)"):
        st.code(_compiled_html(), language="html")

    st.divider()
    st.subheader("✏️ Modifiche")
    st.markdown(
        "Scrivi cosa vuoi cambiare in linguaggio naturale. Claude applica "
        "solo quello che chiedi e lascia il resto invariato. Le immagini "
        "già caricate per gli slot che restano vengono preservate."
    )
    feedback = st.text_area(
        "Cosa vuoi modificare?",
        key="revision_feedback_input",
        height=120,
        placeholder=(
            "Es.\n"
            "- rendi la headline più aggressiva e specifica sui risultati\n"
            "- togli la sezione 'Chi siamo'\n"
            "- aggiungi una sezione bonus subito sopra il form\n"
            "- cambia il colore del bottone CTA in giallo brillante\n"
            "- cambia tutta la copy della FAQ rendendola meno tecnica"
        ),
    )
    if st.button("🔧 Applica modifiche", disabled=not feedback.strip(), type="primary"):
        with st.spinner("Claude sta applicando le modifiche…"):
            try:
                updated = revise_landing(
                    api_key=ANTHROPIC_API_KEY,
                    brief=_build_brief(),
                    current=landing,
                    feedback=feedback,
                )
                # Preserve image bytes/choices for slots that still exist.
                new_slot_names = {s.name for s in updated.image_slots}
                st.session_state.slot_images = {
                    k: v
                    for k, v in (st.session_state.slot_images or {}).items()
                    if k in new_slot_names
                }
                st.session_state.slot_choices = {
                    k: v
                    for k, v in (st.session_state.slot_choices or {}).items()
                    if k in new_slot_names
                }
                st.session_state.slot_prompts = {
                    k: v
                    for k, v in (st.session_state.slot_prompts or {}).items()
                    if k in new_slot_names
                }
                st.session_state.landing = updated
                _log_event(
                    "landing_revised",
                    payload={
                        "feedback_chars": len(feedback),
                        "kept_slot_count": len(new_slot_names),
                        "page_title": updated.page_title,
                        "html_kb": len(updated.html) // 1024,
                    },
                )
                st.rerun()
            except Exception as e:
                st.session_state.error = (
                    f"Revision failed: {e}\n\n{traceback.format_exc()}"
                )

    st.divider()

    back_label = "⬅️ Immagini" if landing.image_slots else "⬅️ Generate"
    back_target = "images" if landing.image_slots else "generate"
    cols = st.columns([1, 1, 1, 2])
    if cols[0].button(back_label):
        _set_step(back_target)
        st.rerun()
    if cols[1].button("🔁 Re-generate"):
        st.session_state.landing = None
        st.session_state.slot_choices = {}
        st.session_state.slot_images = {}
        st.session_state.slot_prompts = {}
        _set_step("generate")
        st.rerun()
    if landing.image_slots:
        if cols[2].button("🖼 Gestisci immagini"):
            _set_step("images")
            st.rerun()
    if cols[3].button("🚀 Pubblica su GitHub Pages", type="primary"):
        _publish()


def _resolve_publish_config() -> GitHubConfig:
    """Pick the GitHub config based on the user's hosting choice in the sidebar."""
    if st.session_state.get("hosting_mode") == "custom":
        custom = st.session_state.get("hosting_custom") or {}
        if not custom:
            raise RuntimeError(
                "Hai scelto 'Dominio personalizzato' ma non hai completato il "
                "setup nella sidebar. Verifica & setup, poi riprova."
            )
        return GitHubConfig(
            token=custom["token"],
            username=custom["username"],
            repo=custom["repo"],
            base_url=custom["base_url"].rstrip("/"),
        )
    return GitHubConfig(
        token=_secret("GITHUB_TOKEN"),
        username=_secret("GITHUB_USERNAME"),
        repo=_secret("GITHUB_PAGES_REPO"),
        base_url=_secret("LANDING_BASE_URL").rstrip("/"),
    )


def _publish() -> None:
    brief = _build_brief()

    try:
        cfg = _resolve_publish_config()
    except RuntimeError as e:
        st.session_state.error = str(e)
        return

    html_compiled = _compiled_html()
    images: dict[str, bytes] = {
        name: payload for name, payload in (st.session_state.slot_images or {}).items() if payload
    }

    with st.spinner("Pubblicazione su GitHub Pages in corso…"):
        try:
            result = publish_landing(
                cfg,
                slug=brief.slug,
                html=html_compiled,
                images=images,
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
    st.caption(f"Commit HTML: `{result.html_commit_sha[:8]}`")

    if st.button("🔄 Nuova landing"):
        for k, v in DEFAULT_STATE.items():
            st.session_state[k] = v
        st.session_state.pop("brief_partial", None)
        st.rerun()


_sidebar()
_show_error_if_any()

step = st.session_state.step
if step == "hero":  # legacy state from older sessions
    step = "generate"
    st.session_state.step = step

if step == "brief":
    _step_brief()
elif step == "content":
    _step_content()
elif step == "generate":
    _step_generate()
elif step == "images":
    _step_images()
elif step == "preview":
    _step_preview()
elif step == "done":
    _step_done()
