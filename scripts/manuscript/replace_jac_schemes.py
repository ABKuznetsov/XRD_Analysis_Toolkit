from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = ROOT / "manuscript_assets" / "phase_finder"

REPLACEMENTS = {
    "media/image1.png": ASSET_DIR / "fig1_workflow.png",
    "media/image3.png": ASSET_DIR / "fig4_match_gain.png",
}


def replace_schemes(source: Path, output: Path) -> None:
    document = Document(source)

    for shape in document.inline_shapes:
        blip = shape._inline.graphic.graphicData.pic.blipFill.blip
        relationship_id = blip.get(qn("r:embed"))
        relationship = document.part.rels[relationship_id]
        target = relationship.target_ref
        replacement = REPLACEMENTS.get(target)
        if replacement is None:
            continue

        image_part = relationship.target_part
        image_part._blob = replacement.read_bytes()

        width_px, height_px = _png_dimensions(replacement)
        shape.height = round(shape.width * height_px / width_px)

    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)


def _png_dimensions(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace the two generated schemes in the JAC manuscript.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    replace_schemes(args.source, args.output)


if __name__ == "__main__":
    main()
