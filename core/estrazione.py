"""
PASSO 2 — Estrazione strutturata dei dati del bando/decreto via Claude API.

Prende il testo grezzo (dal PASSO 1) e ne ricava un JSON con i campi del
workflow "scheda bando" Logos. Regole non negoziabili, imposte nel prompt:
  - estrae SOLO ciò che è scritto nel testo; campi assenti → "non specificato",
    mai inventati;
  - NESSUN giudizio su vigenza o cumulabilità reale (li mette il consulente);
  - la cumulabilità è riportata COME scritta nel testo, non interpretata.

Modello: legge ANTHROPIC_MODEL da env (default Sonnet 4.5, context 200k token).
Un decreto da ~107k caratteri ≈ ~30k token: ci sta in UNA sola chiamata, niente
chunking. Guard di sicurezza: oltre MAX_CARATTERI il testo viene troncato e lo
segnaliamo (meglio un'estrazione parziale dichiarata che un errore di context).

Riusa lo stesso pattern del BP Tool: client Anthropic() che legge la chiave da
os.getenv (popolata da .env in locale, da st.secrets su Cloud — vedi app.py).
"""

from __future__ import annotations

import json
import os

from anthropic import Anthropic

MODEL_DEFAULT = "claude-sonnet-4-5-20250929"  # context 200k token
MAX_CARATTERI = 450_000  # ~130k token: oltre, tronchiamo con avviso


class ErroreEstrazione(Exception):
    """Errore comprensibile da mostrare all'utente."""


_SYSTEM = (
    "Sei un analista di finanza agevolata di Logos Advisory Services. "
    "Estrai i dati ESCLUSIVAMENTE dal testo del bando/decreto fornito, senza "
    "inventare nulla. NON esprimere giudizi sulla vigenza del provvedimento né "
    "sulla cumulabilità reale: quella verifica la fa un consulente a mano. "
    "Riporta la cumulabilità SOLTANTO come è scritta nel testo."
)

# Schema dei campi (allineato al workflow scheda bando Logos).
_ISTRUZIONI = """Dal testo qui sotto estrai i campi e restituisci ESCLUSIVAMENTE \
un oggetto JSON valido, senza testo prima o dopo e senza markdown.

Per ogni campo NON presente nel testo usa esattamente la stringa "non \
specificato". Per le liste vuote usa []. Riporta importi, percentuali e date \
come scritti nel testo.

Schema JSON da produrre:
{
  "titolo_provvedimento": "string",
  "estremi_normativi": {"tipo": "string", "numero": "string", "data": "string"},
  "ente_gestore": "string",
  "dotazione_finanziaria": "string",
  "beneficiari": {"dimensione_impresa": "string", "settori_ateco": "string"},
  "spese_ammissibili": [{"voce": "string", "cap_percentuale": "string"}],
  "intensita_forma_aiuto": "string",
  "scadenze_finestre": "string",
  "cumulabilita": "string",
  "regimi_citati": ["string"]
}

Note sui campi:
- estremi_normativi: tipo (es. Decreto/Legge/DM), numero e data del provvedimento.
- beneficiari.settori_ateco: settori e/o codici ATECO se indicati, altrimenti "non specificato".
- spese_ammissibili: una voce per ciascuna categoria di spesa ammessa; "cap_percentuale" solo se il testo indica un tetto in % per quella voce, altrimenti "non specificato".
- intensita_forma_aiuto: intensità dell'aiuto (%) e forma (contributo a fondo perduto, credito d'imposta, finanziamento agevolato, garanzia, ecc.) come da testo.
- cumulabilita: trascrivi fedelmente cosa dice il testo sulla cumulabilità (NON valutare se è realmente cumulabile).
- regimi_citati: regimi di aiuto citati (es. "de minimis", "GBER", "Temporary Framework"); [] se nessuno."""


def _estrai_testo_blocchi(message) -> str:
    parti = []
    for blocco in message.content:
        if getattr(blocco, "type", None) == "text":
            parti.append(blocco.text)
    return "".join(parti).strip()


def _parse_json(raw: str) -> dict:
    s = raw.strip()
    # Toglie eventuali recinti markdown ```json ... ```
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: s.rfind("```")]
        s = s.strip()
    # Isola il primo oggetto JSON, se il modello avesse aggiunto testo
    if not s.startswith("{"):
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1 and j > i:
            s = s[i : j + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise ErroreEstrazione(
            f"Il modello non ha restituito un JSON valido ({e}). "
            "Riprova; se persiste, il testo del decreto potrebbe essere anomalo."
        )


def estrai_dati_bando(testo: str, model: str | None = None) -> dict:
    """Testo grezzo → dict strutturato dei campi del bando.

    Restituisce anche i meta `_model` e `_troncato` per trasparenza nella UI.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ErroreEstrazione(
            "ANTHROPIC_API_KEY non configurata: impossibile chiamare Claude."
        )
    testo = (testo or "").strip()
    if not testo:
        raise ErroreEstrazione("Nessun testo da analizzare.")

    model = model or os.getenv("ANTHROPIC_MODEL") or MODEL_DEFAULT

    troncato = False
    if len(testo) > MAX_CARATTERI:
        testo = testo[:MAX_CARATTERI]
        troncato = True

    client = Anthropic()
    try:
        message = client.messages.create(
            model=model,
            max_tokens=4096,
            system=_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"{_ISTRUZIONI}\n\n=== TESTO DEL BANDO/DECRETO ===\n{testo}",
                }
            ],
        )
    except Exception as e:  # errori SDK/rete/quota
        raise ErroreEstrazione(f"Chiamata a Claude fallita: {type(e).__name__}: {e}")

    dati = _parse_json(_estrai_testo_blocchi(message))
    dati["_model"] = model
    dati["_troncato"] = troncato
    return dati
