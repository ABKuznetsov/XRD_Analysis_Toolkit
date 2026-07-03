from __future__ import annotations

from pathlib import Path

import numpy as np


def load_xy(path: str | Path) -> np.ndarray:
    rows: list[list[float]] = []
    for raw_line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "!", "//")):
            continue

        values = _parse_numeric_columns(line)
        if len(values) >= 2:
            rows.append(values)

    if not rows:
        raise ValueError("No numeric XRD rows found")

    width = min(len(row) for row in rows)
    if width < 2:
        raise ValueError("XRD data must contain at least two numeric columns")
    return np.array([row[:width] for row in rows], dtype=float)


def _parse_numeric_columns(line: str) -> list[float]:
    if ";" in line:
        tokens = [token.strip().replace(",", ".") for token in line.split(";")]
    elif "\t" in line:
        tokens = [token.strip().replace(",", ".") for token in line.split("\t")]
    elif "," in line and " " not in line:
        tokens = [token.strip() for token in line.split(",")]
    else:
        tokens = line.replace(",", ".").split()

    values: list[float] = []
    for token in tokens:
        try:
            values.append(float(token))
        except ValueError:
            break
    return values
