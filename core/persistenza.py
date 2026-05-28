"""
PASSO 4 — Persistenza su Supabase (progetto logos-flow-prod).

Upload del PDF nel bucket privato `schede-pdf` + insert della riga in `schede`,
entrambi via service_role (Schede non ha ancora auth Supabase). Più: lista delle
schede recenti e signed URL temporanea per il download.

Le credenziali si leggono da os.getenv (popolate da .env in locale, da st.secrets
su Cloud — vedi app.py). Mai stampate.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from supabase import create_client

BUCKET = "schede-pdf"


class ErrorePersistenza(Exception):
    """Errore comprensibile da mostrare all'utente."""


def config_presente() -> bool:
    return bool(
        os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        and os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )


def _client():
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ErrorePersistenza(
            "Config Supabase mancante (NEXT_PUBLIC_SUPABASE_URL / "
            "SUPABASE_SERVICE_ROLE_KEY) in .env o nei Secrets."
        )
    try:
        return create_client(url, key)
    except Exception as e:  # noqa: BLE001
        raise ErrorePersistenza(f"Connessione a Supabase fallita: {e}")


def salva_scheda(
    pdf_path: Path,
    dati_estratti: dict,
    testi_redazionali: dict,
    url_decreto: str,
    titolo: str,
    ente: str | None,
) -> dict:
    """Carica il PDF su Storage e inserisce la riga. Ritorna la riga creata."""
    sb = _client()
    sid = str(uuid.uuid4())
    storage_path = f"{sid}.pdf"
    contenuto = Path(pdf_path).read_bytes()

    try:
        sb.storage.from_(BUCKET).upload(
            storage_path,
            contenuto,
            {"content-type": "application/pdf", "upsert": "true"},
        )
    except Exception as e:  # noqa: BLE001
        raise ErrorePersistenza(f"Upload PDF su Storage fallito: {e}")

    riga = {
        "id": sid,
        "titolo": titolo or "Scheda",
        "ente": ente,
        "dati_estratti": dati_estratti,
        "testi_redazionali": testi_redazionali,
        "pdf_path": storage_path,
        "url_decreto_originale": url_decreto,
        "generata_da": None,
    }
    try:
        res = sb.table("schede").insert(riga).execute()
    except Exception as e:  # noqa: BLE001
        # cleanup best-effort del file caricato se l'insert fallisce
        try:
            sb.storage.from_(BUCKET).remove([storage_path])
        except Exception:
            pass
        raise ErrorePersistenza(f"Insert della scheda fallito: {e}")

    return (res.data or [riga])[0]


def lista_schede_recenti(limit: int = 10) -> list[dict]:
    sb = _client()
    try:
        res = (
            sb.table("schede")
            .select("id, titolo, ente, created_at, pdf_path")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        raise ErrorePersistenza(f"Lettura schede recenti fallita: {e}")
    return res.data or []


def signed_url(storage_path: str, expires: int = 3600) -> str:
    """URL temporaneo firmato per scaricare un PDF dal bucket privato."""
    sb = _client()
    try:
        res = sb.storage.from_(BUCKET).create_signed_url(storage_path, expires)
    except Exception as e:  # noqa: BLE001
        raise ErrorePersistenza(f"Creazione signed URL fallita: {e}")
    if isinstance(res, dict):
        return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url") or ""
    return str(res)
