"""
Catena di acquisizione di Logos Schede: URL → download → validazione → testo.

È il pezzo più fragile del tool (gli URL dei decreti puntano a server eterogenei),
quindi qui la priorità è il fail "con grazia": ogni cosa che può andare storta
solleva un ErroreAcquisizione con un messaggio comprensibile, da mostrare a schermo.

Riusa lo stesso approccio di lettura PDF di logos-bp-tool (pdfplumber, pagina per
pagina via extract_text), con fallback su pypdf per i PDF che pdfplumber non
digerisce. La verifica normativa (vigente/scaduto, cumulabilità) NON è qui: la fa
il consulente a mano.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pdfplumber
import requests
from pypdf import PdfReader

# Tetto di sicurezza sul download: un decreto è tipicamente pochi MB.
MAX_BYTES = 40 * 1024 * 1024  # 40 MB
TIMEOUT_DEFAULT = 30  # secondi
_UA = "Mozilla/5.0 (compatible; LogosSchede/0.1; +https://logosadvisory.it)"


class ErroreAcquisizione(Exception):
    """Errore comprensibile da mostrare all'utente (non un traceback)."""


@dataclass
class RisultatoLettura:
    url: str
    dimensione_kb: float
    n_pagine: int
    n_caratteri: int
    testo: str


def scarica_pdf(url: str, timeout: int = TIMEOUT_DEFAULT) -> bytes:
    """Scarica l'URL e restituisce i byte SOLO se sono davvero un PDF.

    Casi gestiti con messaggio chiaro: URL non valido, timeout, download fallito,
    risposta di errore HTTP, file troppo grande, pagina HTML invece di PDF,
    contenuto che non è un PDF.
    """
    url = (url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ErroreAcquisizione(
            "Inserisci un URL valido che inizi con http:// o https://."
        )

    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _UA, "Accept": "application/pdf,*/*"},
            allow_redirects=True,
        )
    except requests.Timeout:
        raise ErroreAcquisizione(
            f"Timeout: il server non ha risposto entro {timeout} secondi."
        )
    except requests.exceptions.SSLError:
        raise ErroreAcquisizione(
            "Errore SSL nel contattare il server (certificato non valido)."
        )
    except requests.RequestException as e:
        raise ErroreAcquisizione(f"Download fallito: {e}")

    if resp.status_code >= 400:
        raise ErroreAcquisizione(
            f"Il server ha risposto con codice {resp.status_code}: "
            "l'URL non è scaricabile (link errato, scaduto o protetto)."
        )

    content = resp.content
    content_type = resp.headers.get("Content-Type", "").lower()

    if len(content) > MAX_BYTES:
        mb = len(content) / 1024 / 1024
        raise ErroreAcquisizione(
            f"File troppo grande ({mb:.0f} MB, max {MAX_BYTES // 1024 // 1024} MB)."
        )
    if not content:
        raise ErroreAcquisizione("Il download è andato a buon fine ma il file è vuoto.")

    # La verifica più affidabile è il magic number, non il Content-Type
    # (molti server etichettano male). Un PDF inizia con "%PDF-".
    if content[:5] != b"%PDF-":
        head = content[:1024].lstrip().lower()
        sembra_html = (
            "html" in content_type
            or head.startswith(b"<!doctype html")
            or head.startswith(b"<html")
            or b"<head" in head
        )
        if sembra_html:
            raise ErroreAcquisizione(
                "L'URL punta a una pagina HTML, non al PDF. Spesso è la pagina di "
                "anteprima/download del decreto: apri quella pagina, copia il link "
                "DIRETTO al file .pdf e incollalo qui."
            )
        raise ErroreAcquisizione(
            "Il file scaricato non è un PDF "
            f"(Content-Type dichiarato: {content_type or 'sconosciuto'})."
        )

    return content


def _testo_pdfplumber(content: bytes) -> str:
    pagine: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for pagina in pdf.pages:
            testo = pagina.extract_text() or ""
            if testo.strip():
                pagine.append(testo)
    return "\n\n".join(pagine).strip()


def _testo_pypdf(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    pagine: list[str] = []
    for pagina in reader.pages:
        testo = pagina.extract_text() or ""
        if testo.strip():
            pagine.append(testo)
    return "\n\n".join(pagine).strip()


def _conta_pagine(content: bytes) -> int:
    try:
        return len(PdfReader(io.BytesIO(content)).pages)
    except Exception:
        return 0


def estrai_testo(content: bytes) -> str:
    """Estrae il testo dal PDF. pdfplumber primario, pypdf come fallback.

    Se entrambi non trovano testo → probabilmente è un PDF scansionato (immagini):
    lo segnaliamo, non improvvisiamo OCR.
    """
    try:
        testo = _testo_pdfplumber(content)
    except Exception:
        testo = ""

    if not testo:
        try:
            testo = _testo_pypdf(content)
        except Exception as e:
            raise ErroreAcquisizione(f"Impossibile leggere il PDF: {e}")

    if not testo:
        raise ErroreAcquisizione(
            "Il PDF non contiene testo estraibile: probabilmente è una scansione "
            "(immagini). Servirebbe un OCR, non previsto in questo passo."
        )
    return testo


def scarica_e_leggi(url: str, timeout: int = TIMEOUT_DEFAULT) -> RisultatoLettura:
    """Orchestratore: URL → byte PDF → testo grezzo + metadati."""
    content = scarica_pdf(url, timeout=timeout)
    testo = estrai_testo(content)
    return RisultatoLettura(
        url=url.strip(),
        dimensione_kb=round(len(content) / 1024, 1),
        n_pagine=_conta_pagine(content),
        n_caratteri=len(testo),
        testo=testo,
    )
