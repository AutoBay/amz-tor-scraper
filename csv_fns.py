import csv
import os
from typing import Any, Dict, List

def _ensure_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def export_rows_csv(path: str, rows: List[Dict[str, Any]], append: bool = False) -> None:
    if not rows:
        return
    _ensure_dir(path)
    # preserve column order based on first row
    fieldnames = list(rows[0].keys())
    mode = "a" if append and os.path.exists(path) else "w"
    with open(path, mode, newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if mode == "w":
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})