from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from xrd_finder.finder import FinderCandidateInput, FinderInput, FinderService


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone XRD phase finder core runner")
    parser.add_argument("pattern", help="Observed XRD pattern file")
    parser.add_argument("--cif", action="append", default=[], help="Candidate CIF file. May be repeated.")
    parser.add_argument("--wavelength", type=float, default=None, help="Radiation wavelength in angstrom")
    parser.add_argument("--output", default="", help="Optional JSON result path")
    args = parser.parse_args()

    candidates = [
        FinderCandidateInput(cif_path=str(Path(path)), name=Path(path).stem, source="cli")
        for path in args.cif
    ]
    result = FinderService().run(
        FinderInput(
            pattern_path=str(Path(args.pattern)),
            candidates=candidates,
            wavelength=args.wavelength,
        )
    )
    payload = asdict(result)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
