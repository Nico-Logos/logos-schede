# Logos Schede

Tool interno di Logos Advisory Services. App **Streamlit** separata (come il BP
Tool), pensata per il deploy su Streamlit Community Cloud.

**Obiettivo finale**: da un link a un bando/decreto → scarica il PDF → estrae i
dati strutturati → genera una scheda PDF brand Logos a 2 pagine → la salva su
Supabase. La verifica normativa (vigente/scaduto, cumulabilità) resta **manuale**,
a carico del consulente.

## Stato: PASSO 1 — Acquisizione

Implementato solo l'anello più fragile della catena: **URL → download → PDF →
testo grezzo**, con gestione esplicita degli errori (URL non valido, timeout,
download fallito, pagina HTML invece del PDF, PDF scansionato senza testo).
Non ancora: estrazione strutturata, impaginazione scheda, Supabase.

- `app.py` — UI Streamlit (input URL + bottone, mostra testo o errore).
- `core/acquisizione.py` — download + validazione PDF + estrazione testo
  (pdfplumber, fallback pypdf), come in `logos-bp-tool`.

## Avvio in locale

```bash
cd ~/logos-schede
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # poi incolla la chiave reale in .env (non committato)

streamlit run app.py
```
→ si apre su http://localhost:8501

La chiave Anthropic non serve per il PASSO 1 (lettura PDF); servirà dal passo 2.
Viene letta da `.env` in locale e da `st.secrets` su Cloud.

## Deploy su Streamlit Cloud (più avanti)

- Selezionare **Python 3.12** nelle advanced settings del deploy (Cloud non legge
  `.python-version`; quel file serve al pyenv locale).
- Mettere `ANTHROPIC_API_KEY` (e `ANTHROPIC_MODEL`) nei **Secrets** del dashboard,
  come chiavi top-level.
- Il `.streamlit/config.toml` è già compatibile con Streamlit Cloud recente.
