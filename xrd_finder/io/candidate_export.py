"""Portable, atomic CSV export of a prepared candidate-list snapshot."""
import csv
import os
from pathlib import Path
import tempfile


def write_candidate_csv(path, headers, rows):
    target = Path(path)
    descriptor, name = tempfile.mkstemp(prefix=f'.{target.name}.', suffix='.tmp', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
