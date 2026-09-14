from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from docx import Document


DOI_RE = re.compile(r"https?://doi\.org/(10\.\d{4,9}/\S+?)(?:[.,]\s*$|\s|$)", re.IGNORECASE)


def crossref_record(doi: str) -> dict:
    encoded = urllib.parse.quote(doi.rstrip(".,").lower(), safe="")
    request = urllib.request.Request(
        f"https://api.crossref.org/works/{encoded}",
        headers={
            "Accept": "application/json",
            "User-Agent": "XRD-Phase-Finder-reference-audit/1.0 (mailto:ku.artemy@igm.nsc.ru)",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)["message"]


def first(value):
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def year(record: dict) -> int | None:
    for field in ("published-print", "published-online", "published", "issued"):
        parts = record.get(field, {}).get("date-parts", [])
        if parts and parts[0]:
            return int(parts[0][0])
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    document = Document(args.docx)
    rows = []
    for paragraph in document.paragraphs:
        text = " ".join(paragraph.text.split())
        if not text.startswith("["):
            continue
        match = DOI_RE.search(text)
        if not match:
            continue
        doi = match.group(1).rstrip(".,")
        row = {"reference": text, "doi": doi}
        try:
            record = crossref_record(doi)
            row.update(
                {
                    "status": "ok",
                    "title": first(record.get("title")),
                    "journal": first(record.get("container-title")),
                    "year": year(record),
                    "volume": record.get("volume", ""),
                    "issue": record.get("issue", ""),
                    "pages": record.get("page", "") or record.get("article-number", ""),
                    "authors": [
                        " ".join(part for part in (author.get("given", ""), author.get("family", "")) if part)
                        for author in record.get("author", [])
                    ],
                }
            )
        except Exception as exc:
            row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        rows.append(row)
        time.sleep(0.08)

    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Audited {len(rows)} DOI references: {args.out}")


if __name__ == "__main__":
    main()
