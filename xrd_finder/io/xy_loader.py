from __future__ import annotations

from pathlib import Path
import csv

import numpy as np


def load_xy(path: str | Path) -> np.ndarray:
    rows: list[list[float]] = []
    for raw_line in Path(path).read_text(encoding="utf-8-sig", errors="ignore").splitlines():
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
    line = line.strip()
    if ";" in line:
        delimiter = ';'
    elif "\t" in line:
        delimiter = '\t'
    elif ',' in line:
        delimiter = ','
        parts = line.split()
        if len(parts) >= 2:
            try:
                # Whitespace-separated decimal-comma data remain supported.
                float(parts[0].replace(',', '.'))
                float(parts[1].replace(',', '.'))
            except ValueError:
                pass
            else:
                delimiter = None
    else:
        delimiter = None
    tokens = (next(csv.reader([line], delimiter=delimiter, skipinitialspace=True))
              if delimiter is not None else line.split())

    values: list[float] = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        try:
            values.append(float(token if delimiter == ',' else token.replace(',', '.')))
        except ValueError:
            break
    return values
