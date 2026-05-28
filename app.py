"""
Logos Schede — entry point Streamlit.

Flusso click-unico end-to-end:
  Passo 1  URL → download → PDF → testo grezzo            (core/acquisizione)
  Passo 2  testo → dati strutturati del bando (Claude)     (core/estrazione)
  Passo 3A dati → testi redazionali "scheda_logos" (Claude)(core/redazione)
  Passo 3B scheda_logos → PDF 2 pagine (HTML+Playwright)   (core/impaginazione)
  Passo 4  upload PDF + insert riga su Supabase            (core/persistenza)

La verifica di vigenza/cumulabilità reale resta MANUALE (consulente).
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

st.set_page_config(
    page_title="Logos Schede",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

load_dotenv()

ROOT = Path(__file__).resolve().parent
TMP = ROOT / "tmp"


def carica_segreti() -> dict[str, bool]:
    """Porta i segreti da .env (locale) o st.secrets (Cloud) in os.environ.

    Pattern robusto: si legge st.secrets SOLO per le variabili mancanti e dentro
    try/except (in locale senza secrets.toml accedere a st.secrets solleverebbe).
    """
    needed = [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "NEXT_PUBLIC_SUPABASE_URL",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
    ]
    for name in needed:
        if not os.getenv(name):
            try:
                val = st.secrets[name]
            except Exception:
                continue
            if val:
                os.environ[name] = str(val)
    return {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "supabase": bool(
            os.getenv("NEXT_PUBLIC_SUPABASE_URL")
            and os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        ),
    }


_stato = carica_segreti()


@st.cache_resource(show_spinner="Inizializzazione Chromium (solo al primo avvio del container)…")
def _bootstrap_chromium() -> dict:
    """Su Streamlit Cloud scarica Chromium se mancante; idempotente.

    Cache_resource garantisce 1 sola esecuzione per processo (anche tra rerun).
    Restituisce telemetria leggibile mostrata in sidebar (vedi più sotto).
    """
    from core.cloud_setup import ensure_chromium

    return ensure_chromium()


_chromium_info = _bootstrap_chromium()

# Import core dopo set_page_config / segreti / bootstrap browser
from core.acquisizione import ErroreAcquisizione, scarica_e_leggi  # noqa: E402
from core.estrazione import ErroreEstrazione, estrai_dati_bando  # noqa: E402
from core.impaginazione import (  # noqa: E402
    ErroreImpaginazione,
    genera_pdf,
    logo_placeholder_usato,
    pdf_to_pngs,
)
from core.persistenza import (  # noqa: E402
    ErrorePersistenza,
    config_presente,
    lista_schede_recenti,
    salva_scheda,
    signed_url,
)
from core.redazione import ErroreRedazione, genera_testi_scheda  # noqa: E402


# ---------------------------------------------------------------------------
# Orchestrazione passi 2→4
# ---------------------------------------------------------------------------
def genera_scheda(lettura) -> dict:
    """Esegue estrazione → redazione → impaginazione → (salvataggio). Solleva
    l'eccezione tipizzata del passo che fallisce (per identificarlo nella UI)."""
    with st.spinner("1/4 · Estrazione dati dal decreto…"):
        dati = estrai_dati_bando(lettura.testo)
    with st.spinner("2/4 · Generazione testi scheda (tono Logos)…"):
        scheda = genera_testi_scheda(dati)
    with st.spinner("3/4 · Impaginazione PDF…"):
        pdf_path, fitting_info = genera_pdf(scheda, TMP / "scheda.pdf")
        pngs = pdf_to_pngs(pdf_path, TMP)
    row = None
    if config_presente():
        with st.spinner("4/4 · Salvataggio su Supabase…"):
            row = salva_scheda(
                pdf_path=pdf_path,
                dati_estratti=dati,
                testi_redazionali=scheda,
                url_decreto=lettura.url,
                titolo=scheda.get("titolo_scheda") or "Scheda",
                ente=dati.get("ente_gestore"),
            )
    return {
        "dati": dati,
        "scheda": scheda,
        "pdf_bytes": Path(pdf_path).read_bytes(),
        "pngs": [str(p) for p in pngs],
        "row": row,
        "salvato": row is not None,
        "fitting": fitting_info,
    }


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.markdown("## Logos Schede")
st.sidebar.caption("Bandi & decreti → scheda PDF")
st.sidebar.markdown("---")
st.sidebar.caption(("✓" if _stato["anthropic"] else "⚠️") + " API Anthropic")
st.sidebar.caption(("✓" if _stato["supabase"] else "⚠️") + " Supabase")
# Chromium: ✓ se già in cache, ✱ se appena scaricato in questo cold-start, ⚠️ se fallito.
_ci = _chromium_info or {}
if _ci.get("already_installed"):
    st.sidebar.caption("✓ Chromium (cache)")
elif _ci.get("installed_now"):
    st.sidebar.caption(f"✱ Chromium installato ora ({_ci.get('elapsed_s')}s)")
else:
    st.sidebar.caption("⚠️ Chromium: stato sconosciuto")
if not _stato["supabase"]:
    st.sidebar.info("Senza chiavi Supabase la scheda viene generata ma non salvata.")
if logo_placeholder_usato():
    st.sidebar.warning("Logo placeholder in uso: aggiungi assets/logo_dark.png.")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
st.title("Logos Schede")
st.markdown(
    "Dal link di un bando/decreto alla **scheda PDF Logos**. "
    "_La verifica di vigenza e cumulabilità reale è a cura del consulente, non automatica._"
)

url = st.text_input(
    "URL del decreto/bando (link diretto al file .pdf)",
    placeholder="https://…/decreto.pdf",
)

if st.button("Scarica e leggi", type="primary"):
    if not url.strip():
        st.warning("Incolla prima un URL.")
    else:
        try:
            with st.spinner("Scarico e leggo il PDF…"):
                ris = scarica_e_leggi(url)
        except ErroreAcquisizione as e:
            st.session_state.pop("lettura", None)
            st.session_state.pop("scheda_result", None)
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            st.session_state.pop("lettura", None)
            st.session_state.pop("scheda_result", None)
            st.error(f"Errore inatteso: {type(e).__name__}: {e}")
        else:
            st.session_state["lettura"] = ris
            st.session_state.pop("scheda_result", None)

ris = st.session_state.get("lettura")
if ris:
    st.success("PDF letto correttamente.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Pagine", ris.n_pagine or "—")
    c2.metric("Dimensione", f"{ris.dimensione_kb:.0f} KB")
    c3.metric("Caratteri", f"{ris.n_caratteri:,}".replace(",", "."))
    with st.expander("Testo grezzo estratto", expanded=False):
        st.text_area("Testo", value=ris.testo, height=300, label_visibility="collapsed")

    st.markdown("---")
    if st.button(
        "Genera scheda Logos", type="primary", disabled=not _stato["anthropic"]
    ):
        try:
            st.session_state["scheda_result"] = genera_scheda(ris)
        except ErroreEstrazione as e:
            st.error(f"❌ Estrazione dati (passo 2) fallita: {e}")
        except ErroreRedazione as e:
            st.error(f"❌ Generazione testi (passo 3A) fallita: {e}")
        except ErroreImpaginazione as e:
            st.error(f"❌ Impaginazione PDF (passo 3B) fallita: {e}")
        except ErrorePersistenza as e:
            st.error(f"❌ Salvataggio Supabase (passo 4) fallito: {e}")
        except Exception as e:  # noqa: BLE001
            st.error(f"❌ Errore inatteso: {type(e).__name__}: {e}")
        else:
            st.toast("Scheda generata.")

    res = st.session_state.get("scheda_result")
    if res:
        if res["salvato"]:
            st.success("Scheda generata e salvata su Supabase.")
        else:
            st.info("Scheda generata (Supabase non configurato: PDF non salvato).")

        # ---- QA fitting: avviso visibile + telemetria espandibile -----------
        fit = res.get("fitting") or {}
        if fit.get("fitting_failed"):
            st.error(
                "⚠️ Fitting fallito: una o più pagine hanno ancora overflow "
                "dopo reflow + sintesi + P3. Contenuto potenzialmente tagliato. "
                "Apri 'QA fitting' qui sotto per la telemetria.",
                icon="🚨",
            )
        with st.expander("QA fitting (telemetria impaginazione)", expanded=False):
            of = fit.get("overflow_finale_px") or []
            st.write({
                "n_pagine": fit.get("n_pagine"),
                "overflow_finale_px": of,
                "iter_pass1 (reflow P1→P2)": fit.get("iter_pass1"),
                "iter_pass2 (reflow post-sintesi)": fit.get("iter_pass2"),
                "iter_pass3 (reflow P2→P3)": fit.get("iter_pass3"),
                "sintesi_used": fit.get("sintesi_used"),
                "sintesi_error": fit.get("sintesi_error"),
                "fitting_failed": fit.get("fitting_failed"),
            })
            if fit.get("sintesi_error"):
                st.warning(f"Sintesi adattiva fallita: {fit['sintesi_error']}")

        n_show = min(len(res["pngs"]), 3)
        if n_show:
            cols = st.columns(n_show)
            for i in range(n_show):
                png = res["pngs"][i]
                if Path(png).exists():
                    cols[i].image(png, caption=f"Pagina {i + 1}", use_container_width=True)
        st.download_button(
            "Scarica PDF",
            data=res["pdf_bytes"],
            file_name=f"{res['scheda'].get('titolo_scheda', 'scheda')}.pdf".replace("/", "-"),
            mime="application/pdf",
        )

# ---------------------------------------------------------------------------
# Schede recenti
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Schede recenti")
if not config_presente():
    st.caption("Configura Supabase per vedere e scaricare le schede salvate.")
else:
    try:
        recenti = lista_schede_recenti(10)
    except ErrorePersistenza as e:
        recenti = []
        st.warning(f"Impossibile leggere le schede recenti: {e}")
    if not recenti:
        st.caption("Nessuna scheda salvata finora.")
    for s in recenti:
        c1, c2 = st.columns([4, 1])
        created = (s.get("created_at") or "")[:16].replace("T", " ")
        c1.markdown(f"**{s.get('titolo', '—')}** · {s.get('ente') or '—'}  \n`{created}`")
        if s.get("pdf_path"):
            try:
                c2.link_button("Scarica PDF", signed_url(s["pdf_path"]))
            except ErrorePersistenza:
                c2.caption("link n.d.")
