"""
PASSO 3A — Generazione testi redazionali in tono Logos (Claude API).

Input:  JSON strutturato del passo 2 (dati grezzi del bando).
Output: JSON "scheda_logos" coi contenuti redazionali pronti per il template
        2 pagine, allineati al tono e alla struttura delle schede Logos di
        riferimento (cartella reference/).

Le reference NON bastano a parole: quando presenti, le alleghiamo direttamente
alla request come document content (PDF base64), così il modello vede lo stile
Logos prima di scrivere. Cap a 5 PDF (archetipi) per non far esplodere il payload.

GRACEFUL DEGRADE — i PDF reference NON entrano nel repo pubblico (gitignored:
materiale Logos non distribuibile). In dev locale, se la cartella `reference/`
esiste con i PDF, vengono allegati. In produzione (Streamlit Cloud, cartella
assente), si procede COMUNQUE: le regole di stile/tono/struttura del system
prompt sono autoportanti e sufficienti, anche se la qualità senza il "few-shot"
visuale dei PDF può essere marginalmente meno precisa. Loggiamo la modalità su
stderr in modo che sia visibile nei log Streamlit.

Regole non negoziabili (nel system prompt):
  - mai inventare numeri/requisiti: dove il dato manca, "—" o "n.d.";
  - nessun giudizio su vigenza o cumulabilità reale (li mette il consulente);
  - CTA che parla al cliente-tipo; includere sempre "Tempi feedback: 48-72 ore".
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from anthropic import Anthropic

from core.estrazione import MODEL_DEFAULT

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = ROOT / "reference"

# Archetipi che coprono i casi tipici (regionale FESR, nazionale MIMIT, voucher
# CCIAA, beneficio fiscale, finanziamento SIMEST). Usati come reference di stile.
REFERENCE_PREFERITE = [
    "Scheda_Tertium_2026_Logos.pdf",
    "Scheda_MIMIT_Investimenti_Sostenibili_40_Logos.pdf",
    "Scheda_StartUp_2026_CCIAA_Bari_Logos.pdf",
    "Scheda_PatentBox_Logos.pdf",
    "Scheda_SIMEST_Inserimento_Mercati_Logos.pdf",
]
MAX_REFERENCE = 5


class ErroreRedazione(Exception):
    """Errore comprensibile da mostrare all'utente."""


_SYSTEM = """Sei il copywriter senior di Logos Advisory Services. Scrivi "schede \
bando" informative 2 pagine in tono Logos.

═══════════════════════════════════════════════════════════════════
REGOLA #1 (TASSATIVA) — SEPARAZIONE NETTA TRA STILE E CONTENUTO
═══════════════════════════════════════════════════════════════════

Le schede di riferimento allegate servono ESCLUSIVAMENTE come modello di \
STILE, TONO, STRUTTURA e FORMATTAZIONE: layout delle sezioni, ritmo delle frasi, \
taglio del lead e della CTA, livello di sintesi, lunghezza delle voci, scelta \
dei KPI come categoria. NON sono fonte di contenuto.

OGNI dato di contenuto — numeri, importi, percentuali, beneficiari, profili, \
requisiti, scadenze, regimi (de minimis, GBER…), settori, ATECO, riferimenti \
normativi, ente gestore, denominazione del bando — deve provenire \
ESCLUSIVAMENTE dal JSON del DECRETO IN ESAME passato come input.

È VIETATO introdurre concetti, termini, importi, requisiti, profili, scadenze o \
riferimenti che NON siano presenti nel JSON del decreto in esame. In particolare \
è VIETATO importare elementi visti nelle schede di riferimento: NIENTE \
terminologia SIMEST (es. "scoring MCC", "esposizione 394/81", "Balcani \
Occidentali", "Misura USA"), NIENTE regimi, NIENTE plafond, NIENTE ATECO, \
NIENTE scadenze e NIENTE ente gestore che non siano scritti nel JSON in input. \
Se un termine compare nelle reference ma NON nel JSON in input, NON va nella \
scheda.

Se un campo della scheda non è ricostruibile dal JSON del decreto: usa "—" / \
"n.d.", oppure ometti l'intera sezione (lista vuota, oggetto null). MAI \
riempire un buco con contenuto plausibile preso da altri bandi o inventato.

═══════════════════════════════════════════════════════════════════
REGOLA #2 — "A chi si rivolge": niente profili inventati per simmetria
═══════════════════════════════════════════════════════════════════

Genera i profili SOLO se e come sono descritti nel DECRETO IN ESAME.
- Decreto con UN solo tipo di beneficiario → modalita: "singolo" (un blocco).
- Decreto che descrive ESPLICITAMENTE 2 tipi distinti (es. start-up già \
costituite vs aspiranti imprenditori) → modalita: "doppio".
- È VIETATO inventare un Profilo B "per simmetria estetica" con le reference. \
Meglio un blocco singolo onesto che due profili di cui uno inventato. In caso \
di dubbio: "singolo".

═══════════════════════════════════════════════════════════════════
REGOLA #4 — Il navy bar di "A chi si rivolge" è una ETICHETTA, non un callout
═══════════════════════════════════════════════════════════════════

Il campo `a_chi_si_rivolge.blocco.callout` viene renderizzato come una BARRA \
NAVY stretta sotto i bullet, di tipo etichetta (es. "REGIONI AMMISSIBILI · \
Basilicata · Calabria · …" oppure "RICONDUCIBILITÀ AL SETTORE · verificata sul \
progetto"). Vincoli tassativi:
- MAX ~120 caratteri totali.
- Solo etichette brevi, elenchi compatti, vincoli espressi in 1 riga.
- NON usarlo per testo verboso, paragrafi, requisiti articolati, note tecniche \
estese: quel contenuto va in `callout_attenzione` (cream callout, ammette \
paragrafi più lunghi e — fondamentale — è MOBILE: l'impaginatore può spostarlo \
in P2 se P1 sfora; il navy bar invece è fisso in P1 e farebbe sforare senza \
possibilità di rifluimento).
- Se non hai una vera etichetta breve da metterci → metti `null`. Meglio assente \
che pieno di testo che non c'entra.

═══════════════════════════════════════════════════════════════════
Altre regole
═══════════════════════════════════════════════════════════════════

- NON esprimere giudizi su vigenza o cumulabilità reale: riporta la cumulabilità \
come risulta dai dati. La verifica la fa il consulente a mano.
- La CTA deve parlare al cliente-tipo del bando IN ESAME (coerente con \
beneficiari/settori del decreto, non con quelli delle reference) e includere \
sempre "Tempi feedback: 48-72 ore".
- Tono Logos: concreto, orientato all'azione, frasi brevi, mai burocratico.

═══════════════════════════════════════════════════════════════════
REGOLA #3 — Vincoli di lunghezza (la scheda DEVE stare in 2 pagine A4)
═══════════════════════════════════════════════════════════════════

Il template impagina in ESATTAMENTE 2 pagine A4 e ha cap rigidi: chi eccede \
viene troncato. Per evitare tagli, rispetta questi limiti, scegliendo le voci \
PIÙ IMPORTANTI quando il decreto ne ha di più:

- tabella_caratteristiche: max 9 righe (oltre si troncano). Voce ≤ 35 caratteri, condizione ≤ 90.
- a_chi_si_rivolge / blocco singolo: max 8 bullet (2 colonne x 4). Ogni bullet ≤ 110 caratteri.
- a_chi_si_rivolge / profili: max 6 bullet per profilo. Ogni bullet ≤ 100 caratteri.
- callout_attenzione: max 2 callout, paragrafo ≤ 220 caratteri.
- spese_ammissibili: max 8 voci. Descrizione ≤ 130 caratteri.
- cumulabilita_obblighi: max 8 voci. Descrizione ≤ 120 caratteri.
- criteri_valutazione.voci: max 4 cards.
- lead: 3-5 righe (≤ 480 caratteri).
- cta_paragrafo: 2-3 righe (≤ 320 caratteri).

Se hai più informazioni di quante ne stiano: scegli, NON allungare. Meglio \
poche voci asciutte che molte tagliate.

OBIETTIVO: una scheda che dice MENO ma VERO, mai di più ma inventato."""

_SCHEMA = """Promemoria: ogni valore qui sotto deve provenire dal JSON del DECRETO \
IN ESAME (in fondo a questo messaggio). Le schede di riferimento allegate sono \
SOLO modello di stile, NON di contenuto. Dove un dato manca: "—" / "n.d." o \
ometti la sezione.

Produci ESCLUSIVAMENTE un oggetto JSON valido (nessun testo prima/dopo, \
niente markdown) con ESATTAMENTE questa struttura:

{
  "titolo_scheda": "forma breve incisiva, es. 'Bando Tertium', 'Investimenti Sostenibili 4.0'",
  "sottotitolo": "ente + tipologia + riferimento normativo conciso",
  "categoria_tag": "ETICHETTA ROSSA UPPERCASE, es. 'FINANZA AGEVOLATA · MODA LOMBARDIA'",
  "titolo_p2": "titolo dinamico pagina 2, es. 'Spese ammissibili, timing e operatività'",
  "kpi_strip": [{"valore": "60%", "label": "FONDO PERDUTO"}],  // ESATTAMENTE 5, privilegia intensità/importi/dotazione/scadenza/finestra
  "lead": "paragrafo 3-5 righe: cos'è il bando, a chi serve, cosa offre. Tono Logos.",
  "a_chi_si_rivolge": {
    "modalita": "singolo" (DEFAULT) | "doppio",  // "doppio" SOLO se il decreto descrive ESPLICITAMENTE 2 tipi distinti di beneficiario; in caso di dubbio "singolo". NON inventare un Profilo B per simmetria.
    "blocco": {"titolo": "...", "bullet": ["...", "..."], "callout": "testo BREVE label-style (es. 'REGIONI AMMISSIBILI · Basilicata · Calabria · …'), max ~120 caratteri, o null"},   // usato se 'singolo' — NON usare il callout per testi lunghi (vedi REGOLA #4)
    "profili": [{"label": "PROFILO A", "titolo": "...", "bullet": ["..."]}, {"label": "PROFILO B", "titolo": "...", "bullet": ["..."]}]  // usato SOLO se 'doppio'; campo OMESSO se modalita="singolo"
  },
  "tabella_caratteristiche": [{"voce": "Forma agevolazione", "condizione": "..."}],  // 7-9 righe MAX (cap rigido del template; oltre si tronca)
  "callout_attenzione": [{"titolo": "...", "paragrafo": "..."}],   // 0..2; [] se nessuna criticità marcata
  "spese_ammissibili": [{"titolo": "Macchinari e attrezzature", "descrizione": "..."}],  // 6-8
  "spese_non_ammissibili": "paragrafo unico delle esclusioni",
  "criteri_valutazione": {"soglia": "min 50/100", "voci": [{"punti": "40", "titolo": "Grado di innovazione", "descrizione": "..."}], "nota": "..."} ,  // null se procedura a sportello senza punteggi
  "timeline": [{"data_o_durata": "16 giu 2026", "etichetta": "Apertura domande", "is_active": false, "is_next": false}],  // 5 step; uno is_active=true (in corso), uno is_next=true
  "procedura_paragrafo": "2-3 righe: natura procedura (sportello/graduatoria), invio, documenti chiave",
  "cumulabilita_obblighi": [{"bold": "Stabilità operazione", "descrizione": "..."}],  // 4-8
  "cta_titolo": "domanda diretta al cliente-tipo",
  "cta_paragrafo": "2-3 righe su cosa fa Logos per il cliente; includi 'Tempi feedback: 48-72 ore'",
  "disclaimer_legale": "2-3 righe stile 'Documento informativo a uso commerciale… non sostituiscono la lettura integrale… subordinata a istruttoria…'",
  "footer_meta": "riga meta normativa breve per il footer, es. 'Bando di Regione Lombardia · PR FESR 2021-2027 Azione 1.3.3'"
}

Note: se la procedura è a sportello senza griglia di punteggi, metti criteri_valutazione = null. Se non ci sono criticità operative marcate, callout_attenzione = []."""


def _carica_reference() -> list[tuple[str, str]]:
    """Restituisce [(filename, base64)] per i PDF di reference (cap MAX_REFERENCE).

    Se la cartella reference/ non c'è o è vuota (caso normale in produzione
    Cloud — i PDF sono gitignored), ritorna [] e logga la modalità "senza
    reference" su stderr: la pipeline continua con le sole istruzioni di stile
    del system prompt.
    """
    import sys as _sys

    if not REFERENCE_DIR.exists():
        print(
            f"[redazione] reference/ non presente ({REFERENCE_DIR}). "
            "Genero senza few-shot PDF: lo stile è guidato dal solo system prompt.",
            file=_sys.stderr, flush=True,
        )
        return []
    scelti: list[Path] = []
    for nome in REFERENCE_PREFERITE:
        p = REFERENCE_DIR / nome
        if p.exists():
            scelti.append(p)
    # completa con altri PDF presenti, fino al cap
    if len(scelti) < MAX_REFERENCE:
        for p in sorted(REFERENCE_DIR.glob("*.pdf")):
            if p not in scelti:
                scelti.append(p)
            if len(scelti) >= MAX_REFERENCE:
                break
    scelti = scelti[:MAX_REFERENCE]
    if not scelti:
        print(
            f"[redazione] reference/ esiste ma vuota ({REFERENCE_DIR}). "
            "Genero senza few-shot PDF.",
            file=_sys.stderr, flush=True,
        )
        return []
    out = []
    for p in scelti:
        out.append((p.name, base64.standard_b64encode(p.read_bytes()).decode()))
    return out


def _parse_json(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: s.rfind("```")]
        s = s.strip()
    if not s.startswith("{"):
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1 and j > i:
            s = s[i : j + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise ErroreRedazione(
            f"Il modello non ha prodotto un JSON valido per la scheda ({e}). Riprova."
        )


def genera_testi_scheda(dati_estratti: dict, model: str | None = None) -> dict:
    """JSON passo 2 → JSON 'scheda_logos' coi testi redazionali."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ErroreRedazione("ANTHROPIC_API_KEY non configurata.")

    model = model or os.getenv("ANTHROPIC_MODEL") or MODEL_DEFAULT
    dati_clean = {k: v for k, v in (dati_estratti or {}).items() if not k.startswith("_")}

    content: list[dict] = []
    for nome, b64 in _carica_reference():
        content.append(
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
                "title": nome,
                "context": (
                    "Scheda Logos di riferimento — USALA SOLO come modello di "
                    "STILE/struttura/tono. NON è fonte di contenuto: ogni dato "
                    "deve venire dal JSON del decreto in esame, non da qui."
                ),
            }
        )
    content.append(
        {
            "type": "text",
            "text": (
                f"{_SCHEMA}\n\n=== DATI STRUTTURATI DEL BANDO (dal decreto) ===\n"
                f"{json.dumps(dati_clean, ensure_ascii=False, indent=2)}"
            ),
        }
    )

    client = Anthropic()
    try:
        message = client.messages.create(
            model=model,
            max_tokens=8000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as e:
        raise ErroreRedazione(f"Chiamata a Claude fallita: {type(e).__name__}: {e}")

    testo = "".join(
        b.text for b in message.content if getattr(b, "type", None) == "text"
    ).strip()
    scheda = _parse_json(testo)
    scheda["_model"] = model
    return scheda


# ============================================================================
# Sintesi adattiva — usata SOLO quando il fitting statico in impaginazione.py
# non basta a far stare la scheda in 2 pagine A4. Una sola chiamata Claude.
# ============================================================================

_SYSTEM_SINTESI = """Sei il copywriter senior di Logos. Riscrivi i campi della \
scheda in forma PIÙ SINTETICA per farla stare in 2 pagine A4, MANTENENDO \
INALTERATA la sostanza.

REGOLA TASSATIVA — accorciare NON significa alterare:
- Preserva OGNI dato fattuale: numeri, percentuali, importi, scadenze, date, \
requisiti, regimi, condizioni, esclusioni, vincoli, riferimenti normativi, ATECO, \
ente gestore.
- È VIETATO: arrotondare o cambiare numeri/importi/percentuali; ammorbidire o \
omettere requisiti rilevanti; far sparire un'esclusione, un vincolo, una \
scadenza; cambiare il significato di una frase.
- Accorcia la FORMA (meno parole di servizio, frasi più dense, elimina \
ridondanze e ripetizioni), non la SOSTANZA. Se una sezione non si può accorciare \
senza perdere un dato → lasciala INVARIATA: meglio non sintetizzarla che \
amputarla.

Restituisci ESCLUSIVAMENTE un oggetto JSON con la STESSA struttura del JSON in \
input, con i campi accorciati dove possibile. Nessun testo prima/dopo, niente \
markdown. Vale sempre 'meno ma vero'."""


def sintetizza_per_fitting(scheda: dict, model: str | None = None) -> dict:
    """Riscrive i campi verbosi della scheda in forma più sintetica preservando
    OGNI dato fattuale. Una sola chiamata Claude. Restituisce un nuovo dict
    scheda con la stessa struttura, accorciato. NON inventa, NON arrotonda.

    Costo: 1 chiamata API; invocata solo se il rifluimento statico non basta.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ErroreRedazione("ANTHROPIC_API_KEY non configurata.")
    model = model or os.getenv("ANTHROPIC_MODEL") or MODEL_DEFAULT
    payload = {k: v for k, v in (scheda or {}).items() if not k.startswith("_")}

    user_msg = (
        "Riscrivi questo JSON scheda in forma più sintetica (target ~30% in meno "
        "di parole sui campi verbosi: lead, callout_attenzione.paragrafo, "
        "spese_ammissibili.descrizione, cumulabilita_obblighi.descrizione, "
        "procedura_paragrafo, spese_non_ammissibili, cta_paragrafo). LASCIA "
        "INVARIATI: titolo_scheda, sottotitolo, categoria_tag, kpi_strip, "
        "timeline, tabella_caratteristiche, estremi/numeri/scadenze. Se una "
        "voce non si può accorciare senza perdere un dato, lasciala identica.\n\n"
        "JSON da accorciare (preserva la struttura):\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )

    client = Anthropic()
    try:
        message = client.messages.create(
            model=model,
            max_tokens=8000,
            system=_SYSTEM_SINTESI,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:  # noqa: BLE001
        raise ErroreRedazione(f"Sintesi adattiva fallita: {type(e).__name__}: {e}")

    testo = "".join(
        b.text for b in message.content if getattr(b, "type", None) == "text"
    ).strip()
    scheda_short = _parse_json(testo)
    scheda_short["_model"] = model
    scheda_short["_sintetizzato"] = True
    return scheda_short
