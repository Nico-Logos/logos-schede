"""Diagnostica del fitting sul DM MIMIT 18 marzo 2026 (URL reale).
NON modifica il codice di produzione. Esegue la pipeline reale, stampa la
telemetria effettiva e localizza il blocco 'Tecnologie abilitanti' nel JSON.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from core.acquisizione import scarica_e_leggi  # noqa: E402
from core.estrazione import estrai_dati_bando  # noqa: E402
from core.impaginazione import (  # noqa: E402
    _can_reflow,
    _prepare_view,
    _reflow_one,
    _run_async,
    pdf_to_pngs,
    render_html,
)
from core.redazione import genera_testi_scheda  # noqa: E402

URL_MIMIT = "https://www.mimit.gov.it/images/stories/normativa/dm_18_marzo_2026_signed-nf.pdf"
OUT = ROOT / "tmp"
OUT.mkdir(exist_ok=True)


def trova(scheda: dict, query: str) -> list[tuple[str, str]]:
    """Cerca query (case-insensitive) in tutti i valori stringa di scheda."""
    found: list[tuple[str, str]] = []

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, str) and query.lower() in obj.lower():
            found.append((path, obj[:140] + ("…" if len(obj) > 140 else "")))

    walk(scheda, "")
    return found


_JS_MISURA = """() => [...document.querySelectorAll('.page')].map(p => ({
    clientHeight: p.clientHeight,
    scrollHeight: p.scrollHeight,
    overflow: Math.max(0, p.scrollHeight - p.clientHeight)
}))"""


async def _diag(scheda: dict) -> dict:
    from playwright.async_api import async_playwright

    log: list[str] = []
    out_pdf = OUT / "diag_mimit.pdf"

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            s = _prepare_view(scheda)

            html = render_html(s, None)
            await page.set_content(html, wait_until="load")
            misure = await page.evaluate(_JS_MISURA)

            log.append("== STATO INIZIALE ==")
            log.append(f"  P1 client/scroll/over (px): {misure[0]['clientHeight']} / {misure[0]['scrollHeight']} / {misure[0]['overflow']}")
            log.append(f"  P2 client/scroll/over (px): {misure[1]['clientHeight']} / {misure[1]['scrollHeight']} / {misure[1]['overflow']}")
            log.append(f"  _p1_callout (titoli): {[c.get('titolo', '')[:70] for c in s.get('_p1_callout', [])]}")
            log.append(f"  _p2_callout (titoli): {[c.get('titolo', '')[:70] for c in s.get('_p2_callout', [])]}")
            log.append(f"  _p1_table righe: {len(s.get('_p1_table') or [])}")
            log.append(f"  _p2_table_extra (voci): {[r.get('voce', '')[:60] for r in s.get('_p2_table_extra', [])]}")

            log.append("\n== RIFLUIMENTO (iter-by-iter, sintesi OFF) ==")
            overflow = [m["overflow"] for m in misure]
            it = 0
            while overflow and overflow[0] > 0 and _can_reflow(s) and it < 15:
                # Cosa sta per essere spostato?
                if s.get("_p1_callout"):
                    nxt = s["_p1_callout"][-1].get("titolo", "(no title)")[:70]
                    azione = f"sposto callout '{nxt}' da P1 a P2"
                elif len(s.get("_p1_table") or []) > 5:
                    nxt = s["_p1_table"][-1].get("voce", "(no voce)")[:60]
                    azione = f"sposto riga tabella '{nxt}' da P1 a P2"
                else:
                    azione = "(niente da spostare?)"
                _reflow_one(s)
                html = render_html(s, None)
                await page.set_content(html, wait_until="load")
                misure = await page.evaluate(_JS_MISURA)
                overflow = [m["overflow"] for m in misure]
                it += 1
                log.append(f"  iter {it}: {azione}  → P1 overflow={overflow[0]}px, P2 overflow={overflow[1]}px")

            log.append("\n== STATO FINALE (sintesi OFF) ==")
            log.append(f"  iterazioni: {it}")
            log.append(f"  P1 client/scroll/over (px): {misure[0]['clientHeight']} / {misure[0]['scrollHeight']} / {misure[0]['overflow']}")
            log.append(f"  P2 client/scroll/over (px): {misure[1]['clientHeight']} / {misure[1]['scrollHeight']} / {misure[1]['overflow']}")
            log.append(f"  _p1_callout finale: {[c.get('titolo', '')[:70] for c in s.get('_p1_callout', [])]}")
            log.append(f"  _p2_callout finale: {[c.get('titolo', '')[:70] for c in s.get('_p2_callout', [])]}")
            log.append(f"  _p1_table righe: {len(s.get('_p1_table') or [])}")

            # PDF finale del rifluito-static-only (lo stesso page che ho misurato)
            await page.pdf(
                path=str(out_pdf),
                format="A4",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            await browser.close()

    return {"log": log, "pdf": out_pdf, "scheda_dopo_reflow": s}


def main():
    print("=" * 78)
    print("FASE A — Scarico decreto MIMIT (URL reale)")
    print("=" * 78)
    lettura = scarica_e_leggi(URL_MIMIT)
    print(f"  PDF: {lettura.n_pagine} pagine, {lettura.n_caratteri} caratteri")

    print("\nFASE B — Estrazione (Claude call #1)…")
    dati = estrai_dati_bando(lettura.testo)
    (OUT / "diag_dati.json").write_text(json.dumps(dati, ensure_ascii=False, indent=2))
    print("  salvato: tmp/diag_dati.json")

    print("\nFASE C — Redazione testi scheda (Claude call #2)…")
    scheda = genera_testi_scheda(dati)
    (OUT / "diag_scheda.json").write_text(json.dumps(scheda, ensure_ascii=False, indent=2))
    print("  salvato: tmp/diag_scheda.json")

    print("\n" + "=" * 78)
    print('CACCIA: dove vive "Tecnologie abilitanti" / "tecnolog" nel JSON scheda?')
    print("=" * 78)
    for q in ("Tecnologie abilitanti", "abilitanti", "Transizione 4.0", "tecnolog"):
        m = trova(scheda, q)
        if m:
            print(f"\n  query: '{q}' → {len(m)} match")
            for path, snippet in m:
                print(f"    • [{path}]")
                print(f"        {snippet}")
        else:
            print(f"\n  query: '{q}' → 0 match")

    # struttura "alta" del JSON: quante callout_attenzione? quante righe tabella?
    print("\nSTRUTTURA SCHEDA (alto livello):")
    print(f"  callout_attenzione: {len(scheda.get('callout_attenzione') or [])} item(s)")
    for i, c in enumerate(scheda.get("callout_attenzione") or []):
        print(f"    [{i}] titolo: {c.get('titolo', '(no)')[:80]}")
    print(f"  tabella_caratteristiche: {len(scheda.get('tabella_caratteristiche') or [])} righe")
    print(f"  a_chi_si_rivolge.modalita: {(scheda.get('a_chi_si_rivolge') or {}).get('modalita', '?')}")
    blocco = (scheda.get("a_chi_si_rivolge") or {}).get("blocco")
    if blocco:
        print(f"    blocco.callout: {(blocco.get('callout') or '(none)')[:120]}")

    print("\n" + "=" * 78)
    print("FASE D — Rifluimento adattivo (sintesi OFF) + telemetria per-iter")
    print("=" * 78)
    info = _run_async(_diag(scheda))
    for ln in info["log"]:
        print(ln)
    print(f"\nPDF diagnostico: {info['pdf']}")
    pngs = pdf_to_pngs(info["pdf"], OUT)
    for p in pngs:
        print(f"PNG: {p}")


if __name__ == "__main__":
    main()
