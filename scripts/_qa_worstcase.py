"""QA worst-case fitting test.

Costruisce a mano una scheda "estrema" (tabella lunga, molti callout, navy bar
pieno deliberatamente in violazione del vincolo) e mostra:

  PRIMA  → overflow misurato sul render statico (nessun fitting, nessuna sintesi)
  DOPO   → telemetria della pipeline reale `genera_pdf` (PASS1+2+3)

Obiettivo: dimostrare che `overflow_finale_px = 0` su tutte le pagine, senza
che `overflow:hidden` debba tagliare contenuto visibile.

NON modifica codice di produzione, NON committa, NON tocca Supabase.
Salva PDF/PNG in tmp/ (gitignored). Eseguire da repo root:
  python scripts/_qa_worstcase.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from core.impaginazione import (  # noqa: E402
    _prepare_view,
    _render_and_measure,
    _run_async,
    data_corrente_it,
    genera_pdf,
    pdf_to_pngs,
)

OUT = ROOT / "tmp"
OUT.mkdir(exist_ok=True)

# ────────────────────────────────────────────────────────────────────────────
# WORST-CASE MOCK
# ────────────────────────────────────────────────────────────────────────────
# Tutto è volutamente sopra-soglia: tabella di 14 righe, 6 callout con paragrafi
# lunghi, navy bar di ~280 char (in violazione del vincolo dei 120) per
# verificare che la pipeline gestisca anche input fuori specifica.
SCHEDA_WORST: dict = {
    "titolo_scheda": "Worst-Case Test · Bando Manifatturiero Avanzato 2026",
    "sottotitolo": "Decreto pilota per stress test del fitting adattivo",
    "categoria_tag": "MISE · STRESS TEST",
    "kpi_strip": [
        {"valore": "€ 250M", "label": "Dotazione complessiva"},
        {"valore": "50%", "label": "Intensità massima aiuto"},
        {"valore": "€ 5M", "label": "Contributo per progetto"},
        {"valore": "36 mesi", "label": "Durata progetto"},
        {"valore": "12/2026", "label": "Scadenza domande"},
    ],
    "lead": (
        "Il bando finanzia, nell'ambito della transizione 4.0, progetti di "
        "investimento in tecnologie abilitanti, ricerca industriale e sviluppo "
        "sperimentale promossi da imprese manifatturiere localizzate sull'intero "
        "territorio nazionale, con un focus particolare sulle aree del "
        "Mezzogiorno (Abruzzo, Molise, Campania, Puglia, Basilicata, Calabria, "
        "Sicilia, Sardegna) per le quali è riconosciuta una maggiorazione "
        "dell'intensità di aiuto."
    ),
    "a_chi_si_rivolge": {
        "modalita": "singolo",
        "blocco": {
            "titolo": "Imprese manifatturiere e centri di ricerca",
            "bullet": [
                "PMI manifatturiere con sede operativa in Italia da almeno 24 mesi",
                "Grandi imprese in partnership con almeno una PMI o un OdR",
                "Reti d'impresa con contratto registrato",
                "Centri di ricerca pubblici e privati accreditati",
                "Spin-off universitari con almeno 12 mesi di operatività",
                "Consorzi e società consortili che includano almeno 3 PMI",
                "Start-up innovative iscritte nella sezione speciale del RI",
                "Imprese agro-industriali con codice ATECO 10.x o 11.x",
            ],
            # NAVY BAR DELIBERATAMENTE FUORI SPECIFICA (>120 char)
            "callout": (
                "TECNOLOGIE ABILITANTI · IoT industriale · Robotica collaborativa · "
                "Big data analytics · Cloud edge computing · Cybersecurity OT · "
                "Realtà aumentata e virtuale · Manifattura additiva · Simulazione "
                "avanzata · Integrazione orizzontale e verticale · Intelligenza "
                "artificiale applicata ai processi produttivi"
            ),
        },
    },
    "tabella_caratteristiche": [
        {"voce": "Forma agevolazione", "condizione": "Contributo a fondo perduto fino al 50% delle spese ammissibili, integrabile con finanziamento agevolato a tasso zero fino a un ulteriore 20%."},
        {"voce": "Soglia minima progetto", "condizione": "€ 500.000 di spese complessive, di cui almeno il 40% in ricerca industriale o sviluppo sperimentale."},
        {"voce": "Soglia massima progetto", "condizione": "€ 10.000.000 di spese complessive per singolo progetto, € 25.000.000 per progetti in partenariato pubblico-privato."},
        {"voce": "Regime di aiuto", "condizione": "Reg. UE 651/2014 art. 25 (R&S), in alternativa de minimis ex Reg. UE 2023/2831 per spese di consulenza."},
        {"voce": "Cumulo", "condizione": "Cumulabile con crediti d'imposta R&S e Industria 4.0 nei limiti di intensità del regime applicato."},
        {"voce": "Anticipazione", "condizione": "Fino al 40% del contributo concesso, previa fideiussione bancaria o assicurativa."},
        {"voce": "Modalità erogazione", "condizione": "SAL a stato avanzamento lavori, fino a 3 quote intermedie più saldo a rendicontazione finale."},
        {"voce": "Tempistica istruttoria", "condizione": "120 giorni dalla chiusura dello sportello, valutazione a graduatoria con punteggio minimo di 60/100."},
        {"voce": "Variazioni progetto", "condizione": "Ammesse variazioni non sostanziali entro il 20% del costo; oltre tale soglia serve nuova istruttoria."},
        {"voce": "Maggiorazioni Sud", "condizione": "+15% per progetti localizzati in Basilicata, Calabria, Campania, Puglia, Sicilia; +10% per Abruzzo, Molise, Sardegna."},
        {"voce": "Brevetti", "condizione": "Spese di deposito brevetti ammissibili fino al 5% del totale, con tetto di € 100.000."},
        {"voce": "Personale dedicato", "condizione": "Costo del personale dipendente o assimilato calcolato su base oraria standard secondo tabelle UCS approvate."},
        {"voce": "Rendicontazione", "condizione": "Sistema telematico dedicato, documenti firmati digitalmente, audit certificato per importi > € 2M."},
        {"voce": "Obbligo mantenimento", "condizione": "Mantenimento del bene/risultato per almeno 5 anni dalla conclusione del progetto."},
    ],
    "callout_attenzione": [
        {
            "titolo": "Vincolo localizzazione unità produttiva",
            "paragrafo": (
                "L'unità produttiva oggetto dell'intervento deve essere localizzata "
                "in Italia e operativa per l'intero periodo di mantenimento. "
                "Eventuali trasferimenti fuori dall'Italia o dall'UE entro 5 anni "
                "comportano la revoca totale del contributo e l'obbligo di "
                "restituzione maggiorato degli interessi legali."
            ),
        },
        {
            "titolo": "Esclusioni settoriali tassative",
            "paragrafo": (
                "Sono escluse le imprese operanti nei settori pesca e acquacoltura "
                "(Reg. UE 717/2014), produzione primaria di prodotti agricoli "
                "(allegato I TFUE), siderurgia, carbone, costruzione navale, fibre "
                "sintetiche, trasporti e relative infrastrutture, produzione e "
                "distribuzione di energia e di infrastrutture energetiche."
            ),
        },
        {
            "titolo": "DNSH e tagging climatico",
            "paragrafo": (
                "Tutti i progetti devono rispettare il principio Do No Significant "
                "Harm ai sensi del Reg. UE 2020/852 e contribuire per almeno il 37% "
                "del valore agli obiettivi climatici secondo la tassonomia europea. "
                "Asseverazione richiesta in fase di domanda e verificata in sede di "
                "rendicontazione."
            ),
        },
        {
            "titolo": "Limitazioni cumulo Industria 4.0",
            "paragrafo": (
                "Il cumulo con crediti d'imposta Industria 4.0 e Transizione 5.0 è "
                "ammesso solo se le spese sono distinte e tracciabili separatamente. "
                "Per le medesime voci di costo non è ammessa doppia agevolazione: la "
                "verifica avviene tramite cross-check con cassetto fiscale."
            ),
        },
        {
            "titolo": "Procedura graduatoria e ribasso",
            "paragrafo": (
                "In caso di esaurimento risorse, le domande ammissibili oltre la "
                "soglia di copertura vengono inserite in lista d'attesa con priorità "
                "in caso di rinunce o revoche. Non è previsto ribasso d'asta sui "
                "costi dichiarati: i SAL vengono parametrati al costo effettivamente "
                "sostenuto e documentato."
            ),
        },
        {
            "titolo": "Pubblicità e trasparenza",
            "paragrafo": (
                "Obbligo di pubblicazione del contributo nel Registro Nazionale "
                "Aiuti di Stato entro 30 giorni dalla concessione e nel sito web "
                "aziendale (sezione Trasparenza ex L. 124/2017) per importi > € 10k."
            ),
        },
    ],
    "titolo_p2": "Spese ammissibili, criteri e operatività",
    "spese_ammissibili": [
        {"titolo": "Personale ricerca", "descrizione": "Ricercatori, tecnici e personale ausiliario dedicati al progetto, in base alle UCS approvate."},
        {"titolo": "Strumenti e attrezzature", "descrizione": "Quota ammortamento per l'effettivo utilizzo nel progetto, max 30% del totale."},
        {"titolo": "Servizi consulenza R&S", "descrizione": "Consulenza specialistica acquisita da OdR o consulenti qualificati, max 20%."},
        {"titolo": "Materiali", "descrizione": "Materiali di consumo, prototipi, componentistica strettamente funzionale al progetto."},
        {"titolo": "Brevetti e licenze", "descrizione": "Acquisizione brevetti, licenze d'uso, know-how di terzi, max 10% del totale."},
        {"titolo": "Spese generali", "descrizione": "Calcolate forfettariamente al 15% delle spese di personale ammesse."},
        {"titolo": "Industrializzazione", "descrizione": "Solo per sviluppo sperimentale: prototipazione pre-industriale e pilot line."},
        {"titolo": "Audit e certificazioni", "descrizione": "Spese audit obbligatorio per progetti > € 2M, max € 30.000 per progetto."},
    ],
    "spese_non_ammissibili": "IVA recuperabile, oneri finanziari, ammende, sanzioni, spese sostenute prima della data di presentazione della domanda.",
    "criteri_valutazione": {
        "soglia": "punteggio minimo 60/100",
        "voci": [
            {"punti": "30", "titolo": "Qualità tecnico-scientifica", "descrizione": "Innovatività, rigore metodologico, stato dell'arte."},
            {"punti": "25", "titolo": "Impatto economico", "descrizione": "Mercato target, scalabilità, occupazione generata."},
            {"punti": "25", "titolo": "Sostenibilità ambientale", "descrizione": "Allineamento DNSH, tassonomia UE, KPI climatici."},
            {"punti": "20", "titolo": "Solidità proponente", "descrizione": "Rating creditizio, equity, esperienza R&S pregressa."},
        ],
        "nota": "I criteri vengono pesati con coefficiente Sud (+0.15) per progetti nelle regioni del Mezzogiorno.",
    },
    "timeline": [
        {"data_o_durata": "01/07/2026", "etichetta": "Apertura sportello", "is_active": False, "is_next": True},
        {"data_o_durata": "31/12/2026", "etichetta": "Chiusura presentazione", "is_active": False, "is_next": False},
        {"data_o_durata": "120 gg", "etichetta": "Istruttoria e graduatoria", "is_active": False, "is_next": False},
        {"data_o_durata": "Q2 2027", "etichetta": "Decreti di concessione", "is_active": False, "is_next": False},
        {"data_o_durata": "36 mesi", "etichetta": "Realizzazione progetto", "is_active": False, "is_next": False},
    ],
    "procedura_paragrafo": (
        "Presentazione domande esclusivamente per via telematica tramite la "
        "piattaforma dedicata, previa registrazione del legale rappresentante con "
        "SPID o CNS. La procedura è valutativa a graduatoria: le domande "
        "ammissibili vengono ordinate per punteggio decrescente fino a esaurimento "
        "delle risorse disponibili."
    ),
    "cumulabilita_obblighi": [
        {"bold": "Cumulo de minimis", "descrizione": "fino a soglia 300k per impresa unica in 3 anni"},
        {"bold": "Cumulo crediti Industria 4.0", "descrizione": "ammesso su spese distinte e tracciabili"},
        {"bold": "Mantenimento occupazione", "descrizione": "ULA medie del biennio post-progetto non inferiori al pre-progetto"},
        {"bold": "Mantenimento bene", "descrizione": "5 anni dalla data di conclusione del progetto"},
        {"bold": "Rendicontazione annuale", "descrizione": "stato avanzamento attività entro 60 gg dalla chiusura esercizio"},
        {"bold": "Monitoraggio fisico", "descrizione": "KPI di realizzazione misurati a 12, 24, 36 mesi"},
        {"bold": "Audit certificato", "descrizione": "obbligatorio per importi superiori a € 2M"},
        {"bold": "Pubblicità contributo", "descrizione": "pubblicazione su Registro RNA e sito aziendale"},
    ],
    "cta_titolo": "Vuoi candidare un progetto su questo bando?",
    "cta_paragrafo": (
        "Logos Advisory Services affianca l'impresa nello screening di "
        "ammissibilità, nella costruzione del business plan, nella redazione "
        "della domanda telematica e nella rendicontazione SAL."
    ),
    "disclaimer_legale": (
        "Le informazioni di questa scheda hanno finalità divulgativa e non "
        "sostituiscono la lettura integrale del decreto e dei suoi allegati. "
        "Per valutazioni puntuali contattare il team Logos."
    ),
    "footer_meta": "Worst-case · QA fitting · v2026.05",
    "meta_riferimenti": "Decreto pilota interno · simulazione QA",
}


# ────────────────────────────────────────────────────────────────────────────
# Helper: misura overflow "naive" (render statico, ZERO fitting, ZERO sintesi)
# ────────────────────────────────────────────────────────────────────────────
async def _misura_prima(scheda: dict) -> list[int]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            s = _prepare_view(scheda)
            return await _render_and_measure(page, s, data_corrente_it())
        finally:
            await browser.close()


def main() -> int:
    print("=" * 78)
    print("QA WORST-CASE FITTING — telemetria PRIMA vs DOPO la pipeline")
    print("=" * 78)
    print(
        f"  Input worst-case: "
        f"{len(SCHEDA_WORST['tabella_caratteristiche'])} righe tabella, "
        f"{len(SCHEDA_WORST['callout_attenzione'])} callout_attenzione, "
        f"navy bar = {len(SCHEDA_WORST['a_chi_si_rivolge']['blocco']['callout'])} char "
        "(>>120, fuori spec)."
    )

    print("\n[PRIMA] Render statico senza fitting né sintesi:")
    prima = _run_async(_misura_prima(SCHEDA_WORST))
    for i, ov in enumerate(prima):
        flag = "  ←  SFORA" if ov > 0 else "  ok"
        print(f"  pagina {i + 1}: overflow = {ov:>4} px{flag}")

    print("\n[DOPO] Pipeline reale (genera_pdf, PASS1+2+3):")
    out_pdf = OUT / "qa_worstcase.pdf"
    pdf_path, info = genera_pdf(SCHEDA_WORST, out_pdf)
    print(json.dumps(info, ensure_ascii=False, indent=2))

    # Verdetto
    over_finale = info.get("overflow_finale_px") or []
    n_pag = info.get("n_pagine")
    ok = all(o == 0 for o in over_finale) and not info.get("fitting_failed")
    verdict = "✅ PASS" if ok else "❌ FAIL"
    print(f"\nVERDETTO: {verdict}  ({n_pag} pagine, overflow_finale_px={over_finale})")
    if info.get("sintesi_error"):
        print(f"  ⚠️ sintesi_error: {info['sintesi_error']}")
        print("  (Il fix prevede che anche senza sintesi, PASS 3 risolva l'overflow.)")

    # PNG anteprime
    print(f"\nPDF: {pdf_path}")
    try:
        pngs = pdf_to_pngs(pdf_path, OUT)
        for p in pngs:
            print(f"PNG: {p}")
    except Exception as e:  # noqa: BLE001
        print(f"(pdf_to_pngs non disponibile: {e})")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
