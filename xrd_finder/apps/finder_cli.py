from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path

from xrd_finder.finder import FinderCandidateInput, FinderInput, FinderService
from xrd_finder.instrument.models import InstrumentProfile, RadiationProfile
from xrd_finder.instrument.profile_io import load_instrument_profile


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone XRD phase finder core runner")
    parser.add_argument("pattern", help="Observed XRD pattern file")
    parser.add_argument("--cif", action="append", default=[], help="Candidate CIF file. May be repeated.")
    instrument = parser.add_mutually_exclusive_group()
    instrument.add_argument("--wavelength", type=float, default=None, help="Monochromatic wavelength in angstrom")
    instrument.add_argument("--instrument-profile", help="Instrument profile JSON file (default: built-in Cu K-alpha)")
    parser.add_argument("--output", default="", help="Optional JSON result path")
    args = parser.parse_args()

    for value in args.cif:
        path = Path(value)
        try:
            if not path.is_file():
                raise FileNotFoundError("CIF file does not exist or is not a regular file")
            with path.open('rb') as stream:
                stream.read(1)
        except OSError as exc:
            parser.error(f"Cannot read CIF '{path}': {exc}")

    try:
        if args.instrument_profile:
            profile = load_instrument_profile(args.instrument_profile)
        elif args.wavelength is not None:
            profile = InstrumentProfile(radiation=RadiationProfile.custom_monochromatic(args.wavelength))
        else:
            profile = InstrumentProfile.default_cu_kalpha()
        if any(not math.isfinite(component.wavelength_angstrom)
               or not math.isfinite(component.weight) for component in profile.radiation.components):
            raise ValueError("Radiation wavelengths and weights must be finite")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.error(f"Invalid instrument profile: {exc}")

    candidates = [
        FinderCandidateInput(cif_path=str(Path(path)), name=Path(path).stem, source="cli")
        for path in args.cif
    ]
    result = FinderService().run(
        FinderInput(
            pattern_path=str(Path(args.pattern)),
            candidates=candidates,
            wavelength=profile.radiation.components[0].wavelength_angstrom,
            include_kalpha2=len(profile.radiation.components) > 1,
            instrument_profile=profile,
        )
    )
    completed = {candidate.candidate_key for candidate in result.candidates}
    skipped = [candidate.cif_path for candidate in candidates if candidate.cif_path not in completed]
    if skipped:
        parser.error("Could not calculate CIF candidates: " + ", ".join(skipped))
    payload = asdict(result)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
