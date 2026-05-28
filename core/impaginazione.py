"""
PASSO 3B — Impaginazione scheda Logos 2 pagine: JSON scheda_logos → PDF A4.

Stack: template HTML/CSS (Jinja2) + Playwright async (Chromium) → PDF A4 margini 0.
Poi rasterizzazione PDF→PNG per la QA visiva (PyMuPDF, portabile; fallback pdftoppm).

Brand: navy #1B2E5E, red #CC1219, grey #5A5A5A, BG_LIGHT #F2F4F8, white.
Titoli Georgia italic, body Calibri/Carlito/Arial. Bullet ✓ rosso per le voci positive.

NB logo: se assets/logo_dark.png esiste lo uso (base64), altrimenti un placeholder
SVG/HTML inline (da sostituire col logo vero — segnalato a schermo).
NB Cloud: Playwright/Chromium richiede setup dedicato in deploy (packages.txt +
'playwright install'); qui il target è il funzionamento LOCALE.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import threading
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

_MESI = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


class ErroreImpaginazione(Exception):
    """Errore comprensibile da mostrare all'utente."""


def data_corrente_it() -> str:
    now = datetime.now()
    return f"{_MESI[now.month - 1]} {now.year}"


def logo_placeholder_usato() -> bool:
    return not (ASSETS / "logo_dark.png").exists()


def _logo_html() -> str:
    p = ASSETS / "logo_dark.png"
    if p.exists():
        b64 = base64.standard_b64encode(p.read_bytes()).decode()
        # height fissa, width auto → aspect ratio del PNG (~2.23) preservato;
        # display:block per evitare offset di baseline tipici delle img inline.
        return f'<img src="data:image/png;base64,{b64}" style="height:10mm;width:auto;display:block" alt="Logos">'
    # Placeholder: mark 2x2 (uno rosso) + wordmark. Da sostituire con logo_dark.png.
    return (
        '<div class="logo">'
        '<div class="mark"><span></span><span></span><span class="r"></span><span></span></div>'
        '<div class="ltext">LOGOS<br>ADVISORY<br>SERVICES</div>'
        '</div>'
    )


_TEMPLATE = r"""<!doctype html><html lang="it"><head><meta charset="utf-8"><style>
/* Strategia overflow (NON facciamo affidamento su overflow:hidden come "fix"):
   1) CSS tightening qui sotto (padding/margin/font-size leggermente più stretti)
      per dare margine di manovra in P1 senza stravolgere il look.
   2) Cap nel template (es. tabella max 9 righe, obblighi max 8, ecc.): chi
      eccede non finisce nella scheda invece di sforare. Le caps sono allineate
      ai limiti che il modello riceve nel prompt (difesa in profondità).
   3) break-inside:avoid su righe tabella, voci grid, callout: se mai si arriva
      al limite, il taglio NON sarà a metà riga ma al confine fra elementi.
   4) overflow:hidden su .page = SOLO rete di sicurezza ultima: i passi 1-3
      devono già risolvere, lui evita solo "macchie" di overflow visibile. */
@page { size: A4; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
:root{--navy:#1B2E5E;--red:#CC1219;--grey:#5A5A5A;--bg:#F2F4F8;--cream:#FCF6E3;}
html,body{width:210mm;}
body{font-family:Calibri,Carlito,Arial,sans-serif;color:var(--grey);font-size:9.2pt;line-height:1.42;}
.page{position:relative;width:210mm;height:297mm;overflow:hidden;display:flex;flex-direction:column;page-break-after:always;}
.page:last-child{page-break-after:auto;}
.serif{font-family:Georgia,'Times New Roman',serif;font-style:italic;}
.header{background:var(--navy);color:#fff;padding:10mm 14mm 6mm;}
.header.p2{padding:8mm 14mm 6mm;}
.htop{display:flex;justify-content:space-between;align-items:flex-start;}
.logo{display:flex;gap:2.5mm;align-items:center;}
.mark{display:grid;grid-template-columns:repeat(2,2.4mm);grid-gap:0.8mm;}
.mark span{width:2.4mm;height:2.4mm;background:#fff;display:block;}
.mark .r{background:var(--red);}
.ltext{font-size:6.6pt;letter-spacing:.12em;color:#fff;line-height:1.15;font-weight:bold;}
.meta-r{text-align:right;font-size:7pt;letter-spacing:.12em;text-transform:uppercase;color:#cdd4e6;}
.meta-r .d{font-family:Georgia,serif;font-style:italic;text-transform:none;letter-spacing:0;color:#aeb8d0;font-size:8pt;margin-top:1mm;}
.title{font-family:Georgia,serif;font-style:italic;font-size:28pt;color:#fff;margin-top:4mm;line-height:1.05;}
.title.p2{font-size:20pt;margin-top:2.5mm;}
.subtitle{color:#aeb8d0;font-size:10.5pt;margin-top:2mm;}
.tag{display:inline-block;background:var(--red);color:#fff;font-size:7.2pt;font-weight:bold;letter-spacing:.09em;text-transform:uppercase;padding:2.4pt 7pt;margin-top:4mm;}
.body{padding:4mm 14mm 3mm;flex:1;min-height:0;}
.kpi{display:flex;background:var(--bg);}
.kpi .cell{flex:1;text-align:center;padding:3.8mm 1mm;border-right:1px solid #d8dde8;}
.kpi .cell:last-child{border-right:0;}
.kpi .v{font-family:Georgia,serif;font-style:italic;font-size:16pt;color:var(--navy);}
.kpi .l{font-size:6.4pt;letter-spacing:.07em;text-transform:uppercase;color:var(--grey);margin-top:1.4mm;}
.lead{background:var(--bg);border-left:4px solid var(--red);padding:3mm 5mm;text-align:justify;font-size:9.2pt;color:#3a3f4a;margin:3.5mm 0;break-inside:avoid;}
.sec{font-family:Georgia,serif;font-style:italic;color:var(--navy);font-size:12.5pt;margin-top:3.5mm;}
.rule{height:2px;background:linear-gradient(to right,var(--red) 0 50px,var(--navy) 50px);margin:1mm 0 2.4mm;}
.box{background:var(--bg);padding:3mm 5mm;break-inside:avoid;}
.box .h{font-family:Georgia,serif;font-style:italic;color:var(--navy);font-size:10.5pt;margin-bottom:2mm;}
ul.sq{list-style:none;}
ul.sq li{padding-left:4.5mm;position:relative;margin:1.2mm 0;font-size:8.4pt;break-inside:avoid;}
ul.sq li::before{content:'\25AA';color:var(--red);position:absolute;left:0;}
.cols2{column-count:2;column-gap:8mm;}
.navybar{background:var(--navy);color:#fff;padding:1.8mm 4mm;font-size:8.1pt;margin-top:2.4mm;}
.navybar b{color:#fff;}
.profiles{display:flex;gap:5mm;}
.profiles .p{flex:1;background:var(--bg);padding:3mm 4mm;break-inside:avoid;}
.plabel{display:inline-block;color:#fff;font-size:6.8pt;font-weight:bold;letter-spacing:.1em;text-transform:uppercase;padding:1.8pt 6pt;margin-bottom:2mm;}
.plabel.a{background:var(--navy);}.plabel.b{background:var(--red);}
.profiles .p .h{font-family:Georgia,serif;font-style:italic;color:var(--navy);font-size:10.2pt;margin-bottom:1.8mm;}
table.car{width:100%;border-collapse:collapse;font-size:8.5pt;}
table.car th{background:var(--navy);color:#fff;text-align:left;padding:1.8mm 4mm;font-weight:normal;text-transform:uppercase;font-size:7.4pt;letter-spacing:.05em;}
table.car tr{break-inside:avoid;page-break-inside:avoid;}
table.car td{padding:1.4mm 4mm;border-bottom:1px solid #e6e9f0;}
table.car tr:nth-child(even) td{background:#f6f8fb;}
table.car td.voce{font-weight:bold;color:var(--navy);width:36%;}
.callout{background:var(--cream);padding:2.8mm 5mm;margin:2.6mm 0;break-inside:avoid;}
.callout .h{font-family:Georgia,serif;font-style:italic;color:var(--red);font-size:10.5pt;margin-bottom:1.2mm;}
.callout p{font-size:8.4pt;color:#5a5340;text-align:justify;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:2.4mm 8mm;}
.item{padding-left:5mm;position:relative;font-size:8.4pt;break-inside:avoid;}
.item::before{content:'\2713';color:var(--red);position:absolute;left:0;font-weight:bold;}
.item b{color:var(--navy);}
.muted{font-size:7.4pt;font-style:italic;color:#8a8f99;margin-top:2.4mm;text-align:justify;}
.cards{display:flex;gap:3.5mm;}
.cards .c{flex:1;background:var(--bg);border-top:2px solid var(--red);padding:2.8mm 3mm;break-inside:avoid;}
.cards .n{font-family:Georgia,serif;font-style:italic;font-size:14pt;color:var(--navy);}
.cards .t{font-weight:bold;color:var(--navy);font-size:8pt;margin:0.8mm 0;}
.cards .d{font-size:7.2pt;color:var(--grey);}
.timeline{display:flex;gap:2.6mm;}
.step{flex:1;text-align:center;padding:3mm 1.5mm;background:var(--bg);border:1px solid var(--navy);}
.step .d{font-family:Georgia,serif;font-style:italic;font-weight:bold;font-size:9.4pt;color:var(--navy);}
.step .e{font-size:6.8pt;color:var(--grey);margin-top:1.2mm;}
.step.active{background:var(--navy);border-color:var(--navy);}
.step.active .d,.step.active .e{color:#fff;}
.step.next{background:var(--red);border-color:var(--red);}
.step.next .d,.step.next .e{color:#fff;}
.para{font-size:8.3pt;color:#4a4f5a;text-align:justify;margin-top:2.4mm;font-style:italic;}
.cta{background:var(--navy);color:#fff;display:flex;gap:7mm;padding:4.5mm 6mm;margin-top:4mm;break-inside:avoid;}
.cta .l{flex:2;}
.cta .r{flex:1;text-align:right;border-left:1px solid rgba(255,255,255,.2);padding-left:6mm;}
.cta .h{font-family:Georgia,serif;font-style:italic;font-size:13pt;color:#fff;margin-bottom:1.6mm;}
.cta p{color:#cfd6e6;font-size:8.5pt;text-align:justify;}
.cta .r .lbl{font-size:6.8pt;letter-spacing:.12em;text-transform:uppercase;color:#aeb8d0;}
.cta .r .mail{font-family:Georgia,serif;font-style:italic;font-size:10pt;color:#fff;margin-top:1.2mm;}
.cta .r .web{font-size:7.2pt;letter-spacing:.05em;color:#cfd6e6;margin-top:1mm;}
.disclaimer{font-size:6.6pt;font-style:italic;color:#9aa0ab;text-align:justify;margin-top:3mm;}
.footer{background:var(--navy);color:#fff;padding:3mm 14mm;display:flex;justify-content:space-between;align-items:center;margin-top:auto;}
.footer .lt{font-family:Georgia,serif;font-style:italic;font-size:8.6pt;color:#fff;}
.footer .fm{font-size:6.4pt;color:#aeb8d0;margin-top:0.8mm;}
.footer .right{font-size:7.2pt;color:#cfd6e6;text-align:right;}
</style></head><body>
{# n_pagine dinamico: 3 se la rete finale ha attivato P3, altrimenti 2 #}
{% set _n_pagine = 3 if (s._p3_callout or s._p3_table_extra) else 2 %}

{# ===================== PAGINA 1 ===================== #}
<div class="page">
  <div class="header">
    <div class="htop">
      {{ logo_html|safe }}
      <div class="meta-r">Scheda Informativa<div class="d">{{ data_scheda }}</div></div>
    </div>
    <div class="title">{{ s.titolo_scheda }}</div>
    <div class="subtitle">{{ s.sottotitolo }}</div>
    {% if s.categoria_tag %}<div class="tag">{{ s.categoria_tag }}</div>{% endif %}
  </div>

  <div class="kpi">
    {% for k in s.kpi_strip[:5] %}
    <div class="cell"><div class="v">{{ k.valore }}</div><div class="l">{{ k.label }}</div></div>
    {% endfor %}
  </div>

  <div class="body">
    <div class="lead">{{ s.lead }}</div>

    <div class="sec">A chi si rivolge</div><div class="rule"></div>
    {% set ac = s.a_chi_si_rivolge %}
    {% if ac and ac.modalita == 'doppio' and ac.profili %}
      <div class="profiles">
        {% for pr in ac.profili[:2] %}
        <div class="p">
          <span class="plabel {{ 'a' if loop.first else 'b' }}">{{ pr.label }}</span>
          <div class="h">{{ pr.titolo }}</div>
          <ul class="sq">{% for b in pr.bullet[:6] %}<li>{{ b }}</li>{% endfor %}</ul>{# cap: max 6 bullet per profilo #}
        </div>
        {% endfor %}
      </div>
    {% elif ac and ac.blocco %}
      <div class="box">
        {% if ac.blocco.titolo %}<div class="h">{{ ac.blocco.titolo }}</div>{% endif %}
        <ul class="sq cols2">{% for b in ac.blocco.bullet[:8] %}<li>{{ b }}</li>{% endfor %}</ul>{# cap: max 8 bullet nel blocco singolo (2 col x 4) #}
        {% if ac.blocco.callout %}<div class="navybar">{{ ac.blocco.callout }}</div>{% endif %}
      </div>
    {% endif %}

    <div class="sec">Caratteristiche dell'agevolazione</div><div class="rule"></div>
    <table class="car"><tr><th>Voce</th><th>Condizione</th></tr>
      {% for r in s._p1_table %}{# righe in P1: settate dal rifluimento adattivo (5..9) #}
      <tr><td class="voce">{{ r.voce }}</td><td>{{ r.condizione }}</td></tr>
      {% endfor %}
    </table>

    {% for co in s._p1_callout %}{# callout in P1: settati dal rifluimento adattivo #}
    <div class="callout"><div class="h">{{ co.titolo }}</div><p>{{ co.paragrafo }}</p></div>
    {% endfor %}
  </div>

  <div class="footer">
    <div><div class="lt">Visione finanziaria, crescita concreta.</div><div class="fm">{{ s.footer_meta }}</div></div>
    <div class="right">Logos Advisory Services · Milano · Pescara · Bari · pag. 1 di {{ _n_pagine }}</div>
  </div>
</div>

{# ===================== PAGINA 2 ===================== #}
<div class="page">
  <div class="header p2">
    <div class="htop">
      {{ logo_html|safe }}
      <div class="meta-r">Scheda Informativa<div class="d">{{ s.titolo_scheda }}</div></div>
    </div>
    <div class="title p2">{{ s.titolo_p2 or 'Spese ammissibili, timing e operatività' }}</div>
  </div>

  <div class="body">
    {# Rifluiti da P1 quando lì non stavano: callout prima, poi righe tabella eccedenti #}
    {% for co in s._p2_callout %}
    <div class="callout"><div class="h">{{ co.titolo }}</div><p>{{ co.paragrafo }}</p></div>
    {% endfor %}
    {% if s._p2_table_extra %}
    <div class="sec">Caratteristiche (segue)</div><div class="rule"></div>
    <table class="car">
      {% for r in s._p2_table_extra %}
      <tr><td class="voce">{{ r.voce }}</td><td>{{ r.condizione }}</td></tr>
      {% endfor %}
    </table>
    {% endif %}

    <div class="sec">Spese ammissibili</div><div class="rule"></div>
    <div class="grid2">
      {% for sp in s.spese_ammissibili[:8] %}
      <div class="item"><b>{{ sp.titolo }}:</b> {{ sp.descrizione }}</div>
      {% endfor %}
    </div>
    {% if s.spese_non_ammissibili %}<div class="muted"><b>Spese NON ammissibili:</b> {{ s.spese_non_ammissibili }}</div>{% endif %}

    {% if s.criteri_valutazione %}
    <div class="sec">Criteri di valutazione · {{ s.criteri_valutazione.soglia }}</div><div class="rule"></div>
    <div class="cards">
      {% for c in s.criteri_valutazione.voci[:4] %}{# cap: 4 cards in una riga #}
      <div class="c"><div class="n">{{ c.punti }}</div><div class="t">{{ c.titolo }}</div><div class="d">{{ c.descrizione }}</div></div>
      {% endfor %}
    </div>
    {% if s.criteri_valutazione.nota %}<div class="muted">{{ s.criteri_valutazione.nota }}</div>{% endif %}
    {% endif %}

    <div class="sec">Timing operativo</div><div class="rule"></div>
    <div class="timeline">
      {% for t in s.timeline[:5] %}
      <div class="step {{ 'active' if t.is_active else ('next' if t.is_next else '') }}">
        <div class="d">{{ t.data_o_durata }}</div><div class="e">{{ t.etichetta }}</div>
      </div>
      {% endfor %}
    </div>
    {% if s.procedura_paragrafo %}<div class="para">{{ s.procedura_paragrafo }}</div>{% endif %}

    <div class="sec">Obblighi e vincoli</div><div class="rule"></div>
    <div class="grid2">
      {% for o in s.cumulabilita_obblighi[:8] %}{# cap: max 8 obblighi (4 per colonna) #}
      <div class="item"><b>{{ o.bold }}:</b> {{ o.descrizione }}</div>
      {% endfor %}
    </div>

    <div class="cta">
      <div class="l"><div class="h">{{ s.cta_titolo }}</div><p>{{ s.cta_paragrafo }}</p></div>
      <div class="r"><div class="lbl">Contatti</div><div class="mail">info@logosadvisory.it</div><div class="web">WWW.LOGOSADVISORY.IT</div></div>
    </div>

    {% if s.disclaimer_legale %}<div class="disclaimer">{{ s.disclaimer_legale }}</div>{% endif %}
  </div>

  <div class="footer">
    <div><div class="lt">Visione finanziaria, crescita concreta.</div><div class="fm">{{ s.footer_meta }}</div></div>
    <div class="right">Logos Advisory Services · Milano · Pescara · Bari · pag. 2 di {{ _n_pagine }}</div>
  </div>
</div>

{# ===================== PAGINA 3 (condizionale: rete finale di fitting) ===================== #}
{% if s._p3_callout or s._p3_table_extra %}
<div class="page">
  <div class="header p2">
    <div class="htop">
      {{ logo_html|safe }}
      <div class="meta-r">Scheda Informativa<div class="d">{{ s.titolo_scheda }}</div></div>
    </div>
    <div class="title p2">Note e dettagli (segue)</div>
  </div>

  <div class="body">
    {% if s._p3_table_extra %}
    <div class="sec">Caratteristiche (segue)</div><div class="rule"></div>
    <table class="car">
      {% for r in s._p3_table_extra %}
      <tr><td class="voce">{{ r.voce }}</td><td>{{ r.condizione }}</td></tr>
      {% endfor %}
    </table>
    {% endif %}
    {% for co in s._p3_callout %}
    <div class="callout"><div class="h">{{ co.titolo }}</div><p>{{ co.paragrafo }}</p></div>
    {% endfor %}
  </div>

  <div class="footer">
    <div><div class="lt">Visione finanziaria, crescita concreta.</div><div class="fm">{{ s.footer_meta }}</div></div>
    <div class="right">Logos Advisory Services · Milano · Pescara · Bari · pag. 3 di {{ _n_pagine }}</div>
  </div>
</div>
{% endif %}
</body></html>"""


def render_html(scheda: dict, data_scheda: str | None = None) -> str:
    env = Environment(autoescape=select_autoescape(["html", "xml"]))
    tmpl = env.from_string(_TEMPLATE)
    return tmpl.render(
        s=scheda,
        data_scheda=data_scheda or data_corrente_it(),
        logo_html=_logo_html(),
    )


# ---------------------------------------------------------------------------
# Strategia di fitting adattivo (dettaglio completo in _async_genera).
# ---------------------------------------------------------------------------

# Classificazione P1: cosa è CORE (mai mobile) e cosa è MOBILE (rifluibile P1→P2):
#   CORE   = header, kpi_strip, lead, a_chi_si_rivolge (blocco/profili coi bullet
#            E il navy bar), prime _MIN_ROWS_P1 righe di tabella_caratteristiche.
#   MOBILE = callout_attenzione[*] e righe tabella oltre la _MIN_ROWS_P1°.
# Il navy bar di a_chi_si_rivolge.blocco.callout è CORE (fisso): se il modello
# ci mette contenuto verboso il problema è A MONTE → vincolo prompt in redazione.
_MIN_ROWS_P1 = 6  # voci core che vogliamo SEMPRE in P1


def _prepare_view(scheda: dict) -> dict:
    """Distribuisce i blocchi nelle 3 "viste" rifluibili:
       P1 (core + mobile), P2 (segue + spese/timing/obblighi), P3 (fallback).

    Eccedenze (callout #3+, righe tabella oltre la 9°) già di default in P2;
    P3 parte vuota e viene popolata SOLO se sia P1 che P2 sforano.
    """
    s = copy.deepcopy(scheda) if scheda else {}
    callouts = list((scheda or {}).get("callout_attenzione") or [])
    rows = list((scheda or {}).get("tabella_caratteristiche") or [])
    s["_p1_callout"] = callouts[:2]
    s["_p2_callout"] = callouts[2:]
    s["_p3_callout"] = []  # popolato solo se P2 sfora
    s["_p1_table"] = rows[:9]
    s["_p2_table_extra"] = rows[9:]
    s["_p3_table_extra"] = []  # popolato solo se P2 sfora
    return s


def _can_reflow(s: dict) -> bool:
    """Restano blocchi mobili da spostare da P1 a P2?"""
    return bool(s.get("_p1_callout")) or len(s.get("_p1_table") or []) > _MIN_ROWS_P1


def _reflow_one(s: dict) -> None:
    """Sposta UN blocco da P1 a P2.
    Ordine deterministico: prima l'ultimo callout (più mobile), poi l'ultima riga
    di tabella eccedente. Mai sotto _MIN_ROWS_P1 righe in tabella P1.
    """
    if s.get("_p1_callout"):
        s["_p2_callout"].insert(0, s["_p1_callout"].pop())
    elif len(s.get("_p1_table") or []) > _MIN_ROWS_P1:
        s["_p2_table_extra"].insert(0, s["_p1_table"].pop())


def _can_reflow_p2_to_p3(s: dict) -> bool:
    """Restano blocchi mobili da spostare da P2 a una eventuale P3?"""
    return bool(s.get("_p2_callout")) or bool(s.get("_p2_table_extra"))


def _reflow_one_p2_to_p3(s: dict) -> None:
    """Sposta UN blocco da P2 a P3. Prima i callout rifluiti, poi le righe
    'Caratteristiche (segue)'. Le sezioni CORE di P2 (spese/timing/obblighi/CTA)
    NON vengono toccate qui."""
    if s.get("_p2_callout"):
        s["_p3_callout"].insert(0, s["_p2_callout"].pop())
    elif s.get("_p2_table_extra"):
        s["_p3_table_extra"].insert(0, s["_p2_table_extra"].pop())


_JS_MEASURE_OVERFLOW = (
    "() => [...document.querySelectorAll('.page')]"
    ".map(p => Math.max(0, p.scrollHeight - p.clientHeight))"
)


async def _render_and_measure(page, scheda: dict, data_scheda: str | None) -> list[int]:
    """Renderizza la scheda nel page Chromium e restituisce l'overflow per
    pagina in pixel: overflow[i] > 0 → la pagina i sfora l'altezza A4."""
    html = render_html(scheda, data_scheda)
    await page.set_content(html, wait_until="load")
    return await page.evaluate(_JS_MEASURE_OVERFLOW)


async def _async_genera(
    scheda: dict,
    out_path: Path,
    data_scheda: str | None,
    sintetizza_fn,
) -> dict:
    """Orchestratore async di fitting adattivo.

    ════════════════════════════════════════════════════════════════════════════
    INVARIANTE FONDAMENTALE
    ════════════════════════════════════════════════════════════════════════════
    Un elemento o entra INTERO nella pagina, o viene spostato/sintetizzato.
    `overflow:hidden` NON deve MAI tagliare contenuto visibile.
    Se a fine pipeline P1 o P2 (o P3) hanno ancora overflow>0 → è un BUG da
    SEGNALARE (log + flag fitting_failed visibile in UI), non da nascondere.
    ════════════════════════════════════════════════════════════════════════════

    Pipeline (in ordine, costo crescente):
      1) Render + misura via JS (gratuito).
      2) Rifluimento statico P1→P2 (gratuito): muove callout e righe-tabella eccedenti.
      3) Solo se ancora sfora → sintesi adattiva Claude (1 chiamata) che accorcia
         i campi verbosi preservando ogni dato fattuale; poi ri-rifluimento P1→P2.
      4) Solo se P2 sfora ancora → rete finale: rifluisce P2→P3 (creando P3) i
         blocchi mobili (callout/righe eccedenti). Meglio 3 pagine pulite che 2
         tagliate.
      5) Se a fine di tutto qualcosa sfora ancora → WARNING esplicito + flag.
    """
    import sys as _sys

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ErroreImpaginazione(
            "Playwright non installato. Esegui: pip install playwright && playwright install chromium"
        )

    info: dict = {
        "iter_pass1": 0,
        "iter_pass2": 0,
        "iter_pass3": 0,
        "sintesi_used": False,
        "sintesi_error": None,
        "overflow_iniziale_px": [0, 0],
        "overflow_finale_px": [0, 0],
        "n_pagine": 2,
        "fitting_failed": False,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()

            scheda = _prepare_view(scheda)
            overflow = await _render_and_measure(page, scheda, data_scheda)
            info["overflow_iniziale_px"] = list(overflow) if overflow else [0, 0]

            # ── PASS 1 — rifluimento statico P1→P2 (gratuito) ────────────────
            while (
                overflow and overflow[0] > 0
                and _can_reflow(scheda)
                and info["iter_pass1"] < 20
            ):
                _reflow_one(scheda)
                overflow = await _render_and_measure(page, scheda, data_scheda)
                info["iter_pass1"] += 1

            # ── PASS 2 — sintesi adattiva (1 chiamata Claude) se ancora sfora ─
            ancora_sfora = bool(overflow) and (
                overflow[0] > 0 or (len(overflow) >= 2 and overflow[1] > 0)
            )
            if ancora_sfora and sintetizza_fn:
                scheda_short = None
                try:
                    scheda_short = sintetizza_fn(
                        {k: v for k, v in scheda.items() if not k.startswith("_")}
                    )
                except Exception as _se:  # noqa: BLE001
                    # Niente più fallimento silenzioso: registriamo l'errore reale
                    # in modo VISIBILE (info + stderr → log Streamlit).
                    info["sintesi_error"] = f"{type(_se).__name__}: {_se}"
                    print(
                        f"[FITTING] sintesi adattiva FALLITA: {info['sintesi_error']}",
                        file=_sys.stderr,
                    )
                    scheda_short = None
                if scheda_short:
                    scheda = _prepare_view(scheda_short)
                    overflow = await _render_and_measure(page, scheda, data_scheda)
                    while (
                        overflow and overflow[0] > 0
                        and _can_reflow(scheda)
                        and info["iter_pass2"] < 20
                    ):
                        _reflow_one(scheda)
                        overflow = await _render_and_measure(page, scheda, data_scheda)
                        info["iter_pass2"] += 1
                    info["sintesi_used"] = True

            # ── PASS 3 — rete finale: rifluimento P2→P3 (crea P3) ─────────────
            # Se P2 sfora ancora dopo tutto, meglio 3 pagine pulite che 2 tagliate.
            # P1 non dovrebbe più sforare a questo punto, ma se sfora continuiamo
            # a spostare i suoi mobili in P2 (e poi P2 in P3) finché serve.
            while (
                overflow and overflow[0] > 0
                and _can_reflow(scheda)
                and info["iter_pass3"] < 10
            ):
                _reflow_one(scheda)
                overflow = await _render_and_measure(page, scheda, data_scheda)
                info["iter_pass3"] += 1
            while (
                overflow and len(overflow) >= 2 and overflow[1] > 0
                and _can_reflow_p2_to_p3(scheda)
                and info["iter_pass3"] < 25
            ):
                _reflow_one_p2_to_p3(scheda)
                overflow = await _render_and_measure(page, scheda, data_scheda)
                info["iter_pass3"] += 1

            # n_pagine: 3 se P3 ha contenuto, altrimenti 2
            n_pag = 3 if (scheda.get("_p3_callout") or scheda.get("_p3_table_extra")) else 2
            info["n_pagine"] = n_pag
            info["overflow_finale_px"] = list(overflow) if overflow else [0, 0]

            # Warning esplicito se la rete finale non ha risolto
            if any(o > 0 for o in info["overflow_finale_px"]):
                info["fitting_failed"] = True
                print(
                    f"[FITTING] WARNING — fitting FALLITO: overflow finale "
                    f"{info['overflow_finale_px']}px su {n_pag} pagine. "
                    "Contenuto potenzialmente tagliato da overflow:hidden.",
                    file=_sys.stderr,
                )

            # PDF finale (corrisponde 1:1 all'ultimo stato misurato)
            await page.pdf(
                path=str(out_path),
                format="A4",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            await browser.close()

    return info


def _run_async(coro):
    """Esegue una coroutine in un thread con loop dedicato (sicuro dentro Streamlit)."""
    box: dict = {}

    def runner():
        loop = asyncio.new_event_loop()
        try:
            box["v"] = loop.run_until_complete(coro)
        except BaseException as e:  # noqa: BLE001
            box["e"] = e
        finally:
            loop.close()

    t = threading.Thread(target=runner)
    t.start()
    t.join()
    if "e" in box:
        raise box["e"]
    return box.get("v")


def genera_pdf(
    scheda: dict, out_path: Path, data_scheda: str | None = None
) -> tuple[Path, dict]:
    """scheda_logos → (PDF A4 2-3 pagine, telemetria_fitting).

    Telemetria restituita (dict): iter_pass1/2/3, sintesi_used, sintesi_error,
    overflow_iniziale_px, overflow_finale_px, n_pagine, fitting_failed. La UI
    mostra questi valori in un expander "QA fitting" e, se fitting_failed=True,
    un avviso rosso visibile.

    Chiamate API nel caso peggiore = 1 (sintesi adattiva). 0 nel caso normale.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Import "lazy" per evitare ciclo redazione↔impaginazione.
    try:
        from core.redazione import sintetizza_per_fitting as _sint
    except Exception:  # noqa: BLE001
        _sint = None

    try:
        info = _run_async(_async_genera(scheda, out_path, data_scheda, _sint))
    except ErroreImpaginazione:
        raise
    except Exception as e:  # noqa: BLE001
        raise ErroreImpaginazione(f"Render PDF fallito: {type(e).__name__}: {e}")
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise ErroreImpaginazione("PDF non generato (file vuoto).")
    return out_path, info


def pdf_to_pngs(pdf_path: Path, out_dir: Path, dpi: int = 110) -> list[Path]:
    """Rasterizza ogni pagina del PDF in PNG per la QA / anteprima.

    Primario: PyMuPDF (pip, nessuna dipendenza di sistema → ok anche su Cloud).
    Fallback: pdftoppm (poppler) se PyMuPDF non c'è.
    """
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # --- PyMuPDF ---
    try:
        import fitz  # PyMuPDF

        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        paths = []
        with fitz.open(pdf_path) as doc:
            for i, page in enumerate(doc, start=1):
                p = out_dir / f"preview_p{i}.png"
                page.get_pixmap(matrix=mat).save(str(p))
                paths.append(p)
        if paths:
            return paths
    except Exception:
        pass
    # --- fallback pdftoppm ---
    import shutil
    import subprocess

    if shutil.which("pdftoppm"):
        prefix = out_dir / "preview_p"
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", str(pdf_path), str(prefix)],
            check=False,
        )
        return sorted(out_dir.glob("preview_p*.png"))
    return []
