"""Bootstrap Playwright Chromium su Streamlit Community Cloud.

Streamlit Cloud installa solo `requirements.txt` (pip) e `packages.txt` (apt).
NON esegue `playwright install <browser>`, quindi il binario Chromium non viene
scaricato e Playwright fallirebbe alla prima `chromium.launch()`.

Strategia robusta:
1. `packages.txt` fornisce le librerie di sistema necessarie a Chromium headless.
2. Questo modulo, chiamato all'avvio dell'app, controlla se il binario Chromium
   è già in cache (`~/.cache/ms-playwright/chromium-*`); se manca, lancia
   `python -m playwright install chromium` UNA SOLA VOLTA per processo.

`@st.cache_resource` in `app.py` garantisce idempotenza tra rerun: il download
(~170MB) avviene solo al primo cold start del container Cloud. In locale,
se il binario c'è già (dopo `playwright install chromium` da terminale), questa
funzione è no-op.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def _candidate_cache_dirs() -> list[Path]:
    """Possibili posizioni della cache browser di Playwright.

    Ordine di precedenza:
      1. `PLAYWRIGHT_BROWSERS_PATH` se settato (override esplicito).
      2. Linux/Cloud: `~/.cache/ms-playwright` (default su Streamlit Cloud).
      3. macOS: `~/Library/Caches/ms-playwright` (default su Mac dev).
      4. Windows: `%LOCALAPPDATA%\\ms-playwright`.

    Controlliamo tutte le posizioni plausibili così la stessa logica funziona
    sia in dev locale (qualsiasi OS) sia su Cloud (Linux).
    """
    out: list[Path] = []
    custom = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
    if custom:
        out.append(Path(custom))
    home = Path.home()
    out.append(home / ".cache" / "ms-playwright")
    out.append(home / "Library" / "Caches" / "ms-playwright")
    localappdata = os.getenv("LOCALAPPDATA")
    if localappdata:
        out.append(Path(localappdata) / "ms-playwright")
    # Dedup mantenendo ordine.
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
    return uniq


def _cache_dir() -> Path:
    """Prima cartella esistente fra i candidati, altrimenti il primo (default)."""
    for p in _candidate_cache_dirs():
        if p.exists():
            return p
    return _candidate_cache_dirs()[0]


def _chromium_present() -> bool:
    """True se almeno una cache contiene una directory `chromium-*` (o
    `chromium_headless_shell-*`) con il marker `INSTALLATION_COMPLETE`.

    Usiamo il sentinella scritto da Playwright al termine del download, così
    siamo indipendenti dai cambi di layout interno tra versioni
    (`chrome-mac` vs `chrome-mac-x64`, `chrome-linux` vs `chrome-linux64`,
    binario `chrome` vs `headless_shell`, etc.).
    """
    for root in _candidate_cache_dirs():
        if not root.exists():
            continue
        for sub in root.iterdir():
            if not sub.is_dir():
                continue
            name = sub.name
            if not (
                name.startswith("chromium-")
                or name.startswith("chromium_headless_shell-")
            ):
                continue
            if (sub / "INSTALLATION_COMPLETE").exists():
                return True
    return False


def ensure_chromium(verbose: bool = True) -> dict:
    """Garantisce che Chromium sia installato; ritorna dict di telemetria.

    Sicuro da chiamare a ogni avvio: se il binario c'è, è no-op (~µs).
    Solleva RuntimeError con messaggio leggibile se l'installazione fallisce
    (così l'errore appare nei log Streamlit Cloud invece di crashare il render).
    """
    info: dict = {
        "cache_dir": str(_cache_dir()),
        "already_installed": False,
        "installed_now": False,
        "elapsed_s": 0.0,
        "stderr_tail": None,
    }

    if _chromium_present():
        info["already_installed"] = True
        return info

    if verbose:
        print(
            "[cloud_setup] Chromium non trovato in "
            f"{info['cache_dir']} → eseguo `playwright install chromium`…",
            file=sys.stderr, flush=True,
        )

    t0 = time.time()
    try:
        # `--with-deps` NON va usato qui: su Streamlit Cloud non abbiamo sudo per
        # apt; le dipendenze di sistema le risolve packages.txt.
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.CalledProcessError as e:
        info["elapsed_s"] = round(time.time() - t0, 1)
        info["stderr_tail"] = (e.stderr or "")[-800:]
        msg = (
            "Installazione Chromium fallita (`playwright install chromium`). "
            "Verifica packages.txt e i log Streamlit Cloud. "
            f"stderr (tail): {info['stderr_tail']}"
        )
        raise RuntimeError(msg) from e
    except subprocess.TimeoutExpired as e:
        info["elapsed_s"] = round(time.time() - t0, 1)
        raise RuntimeError(
            "Timeout in `playwright install chromium` (>10 min). "
            "Container Cloud probabilmente lento; ritenta riavviando l'app."
        ) from e

    info["elapsed_s"] = round(time.time() - t0, 1)
    info["installed_now"] = True
    if verbose:
        tail = (proc.stdout or "").strip().splitlines()[-3:]
        print(
            f"[cloud_setup] Chromium installato in {info['elapsed_s']}s. "
            f"stdout (tail): {tail}",
            file=sys.stderr, flush=True,
        )
    return info
