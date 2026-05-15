"""Archivio Supabase delle landing prodotte dal funnel-landing-agent.

Riusa la tabella condivisa `agent_outputs`:
    agent_type = 'landing'
    subtype    = 'landing_html'
    title      = "<client_name> · <slug>"
    payload    = { html, page_title, meta_description, brief (LandingBrief dict),
                   publish_result, slot_choices, slot_prompts }

Le immagini dei body slot NON sono persistite qui — solo i prompt e le scelte.
Le env vars SUPABASE_URL e SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_KEY come
fallback legacy) devono essere settate. `LandingStore.from_env()` ritorna None
se mancano e l'app continua senza archivio.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

_TABLE = "agent_outputs"
_AGENT_TYPE = "landing"
_SUBTYPE = "landing_html"


@dataclass(frozen=True)
class LandingRow:
    id: str
    title: str
    payload: dict[str, Any]
    created_at: str


class LandingStore:
    def __init__(self, url: str, secret_key: str) -> None:
        if not url or not secret_key:
            raise ValueError("SUPABASE_URL e SUPABASE_SECRET_KEY obbligatori")
        self.url = url.rstrip("/")
        self.secret_key = secret_key
        self._rest = f"{self.url}/rest/v1"
        self._h_read = {
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
        }
        self._h_write = {
            **self._h_read,
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    @classmethod
    def from_env(cls) -> "LandingStore | None":
        try:
            import streamlit as st
            url = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL", "")
            key = (
                os.getenv("SUPABASE_SECRET_KEY")
                or os.getenv("SUPABASE_SERVICE_KEY")
                or st.secrets.get("SUPABASE_SECRET_KEY", "")
                or st.secrets.get("SUPABASE_SERVICE_KEY", "")
            )
        except Exception:
            url = os.getenv("SUPABASE_URL", "")
            key = (
                os.getenv("SUPABASE_SECRET_KEY", "")
                or os.getenv("SUPABASE_SERVICE_KEY", "")
            )
        if not url or not key:
            return None
        return cls(url=url, secret_key=key)

    @staticmethod
    def _row_to_landing(row: dict[str, Any]) -> LandingRow:
        return LandingRow(
            id=str(row["id"]),
            title=row.get("title", "") or "(senza titolo)",
            payload=row.get("payload") or {},
            created_at=row.get("created_at", ""),
        )

    def save_landing(
        self,
        *,
        client_name: str,
        slug: str,
        page_title: str,
        meta_description: str,
        html: str,
        brief_dict: dict[str, Any],
        slot_choices: dict[str, str],
        slot_prompts: dict[str, str],
        publish_result: dict[str, Any] | None,
    ) -> LandingRow:
        title = f"{client_name or '?'} · {slug or '?'}"[:200]
        body = {
            "agent_type": _AGENT_TYPE,
            "subtype": _SUBTYPE,
            "title": title,
            "payload": {
                "html": html,
                "page_title": page_title,
                "meta_description": meta_description,
                "brief": brief_dict,
                "slot_choices": slot_choices,
                "slot_prompts": slot_prompts,
                "publish_result": publish_result or {},
            },
            "preview": (page_title or meta_description or "")[:500],
            "metadata": {
                "client_name": client_name,
                "slug": slug,
                "published": bool(publish_result),
            },
        }
        r = requests.post(
            f"{self._rest}/{_TABLE}",
            data=json.dumps(body),
            headers=self._h_write,
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Insert landing fallito {r.status_code}: {r.text[:300]}")
        data = r.json()
        if not isinstance(data, list) or not data:
            raise RuntimeError(f"Risposta inattesa: {data!r}")
        return self._row_to_landing(data[0])

    def list_recent(self, limit: int = 30) -> list[LandingRow]:
        r = requests.get(
            f"{self._rest}/{_TABLE}",
            params={
                "select": "*",
                "agent_type": f"eq.{_AGENT_TYPE}",
                "subtype": f"eq.{_SUBTYPE}",
                "order": "created_at.desc",
                "limit": str(limit),
            },
            headers=self._h_read,
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"List landing fallito {r.status_code}: {r.text[:300]}")
        rows = r.json() or []
        return [self._row_to_landing(row) for row in rows]

    def get(self, landing_id: str) -> LandingRow | None:
        r = requests.get(
            f"{self._rest}/{_TABLE}",
            params={"select": "*", "id": f"eq.{landing_id}", "limit": "1"},
            headers=self._h_read,
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Get landing fallito {r.status_code}: {r.text[:300]}")
        rows = r.json() or []
        if not rows:
            return None
        return self._row_to_landing(rows[0])

    def delete(self, landing_id: str) -> None:
        r = requests.delete(
            f"{self._rest}/{_TABLE}",
            params={"id": f"eq.{landing_id}"},
            headers=self._h_read,
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Delete landing fallito {r.status_code}: {r.text[:300]}")
