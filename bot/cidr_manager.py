"""
cidr_manager.py – Manage offline CIDR lists for the DNS Tunnel Scanner.

Stores named CIDR groups (e.g. "Iran – Irancell", "Germany – Hetzner")
in a JSON file so users can re‑use them across scans without re‑typing.
"""

import io
import json
import os
import logging

log = logging.getLogger(__name__)

CIDRS_FILE = "/etc/passwall_telegram/cidrs.json"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_dir():
    d = os.path.dirname(CIDRS_FILE)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _load() -> dict:
    """Return the full {name: cidr_text, …} dictionary."""
    if not os.path.isfile(CIDRS_FILE):
        return {}
    try:
        with open(CIDRS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        msg = f"ERROR LOADING CIDR JSON: {exc}"
        log.error(msg)
        print("\n\n" + "="*50)
        print(msg)
        print("="*50 + "\n\n")
        # Return a fake list so the UI displays the exact error!
        return {"⚠️ ERROR READING FILE": f"# The file cidrs.json is corrupted or invalid!\n# Error: {exc}\n# Please delete /etc/passwall_telegram/cidrs.json"}



def _save(data: dict):
    _ensure_dir()
    with open(CIDRS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_all() -> list:
    """Return list of {name, cidr_count, preview} dicts (lightweight)."""
    data = _load()
    result = []
    for name, text in data.items():
        if not isinstance(text, str):
            continue
        lines_count = 0
        preview = []
        for line in io.StringIO(text):
            s = line.strip()
            if s and not s.startswith("#"):
                lines_count += 1
                if len(preview) < 5:
                    preview.append(s)
        result.append({
            "name": name,
            "cidr_count": lines_count,
            "preview": "\n".join(preview) + ("\n…" if lines_count > 5 else ""),
        })
    return result


def get_one(name: str) -> str:
    """Return raw CIDR text for a given list name, or empty string."""
    return _load().get(name, "")


def add_or_update(name: str, cidr_text: str) -> tuple:
    """Create or overwrite a named CIDR list. Returns (ok, msg)."""
    if not name or not name.strip():
        return False, "Name is required"
    name = name.strip()
    data = _load()
    is_new = name not in data
    data[name] = cidr_text
    _save(data)
    action = "created" if is_new else "updated"
    return True, f"CIDR list '{name}' {action}"


def delete(name: str) -> tuple:
    """Delete a named CIDR list. Returns (ok, msg)."""
    data = _load()
    if name not in data:
        return False, f"CIDR list '{name}' not found"
    del data[name]
    _save(data)
    return True, f"CIDR list '{name}' deleted"
