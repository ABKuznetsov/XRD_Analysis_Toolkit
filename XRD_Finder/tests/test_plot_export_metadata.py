from __future__ import annotations

import re
import unittest

from xrd_finder.plot_export.metadata import (
    CANVAS_LAYER_ORDER,
    CanvasItemTag,
    CanvasLayer,
    canvas_item_tag,
    stable_svg_id,
    tag_canvas_item,
)


class _CanvasItem:
    pass


class PlotExportMetadataTests(unittest.TestCase):
    def test_layer_order_follows_xrd_painting_semantics(self):
        self.assertEqual(
            CANVAS_LAYER_ORDER,
            (
                CanvasLayer.BACKGROUND,
                CanvasLayer.GRID,
                CanvasLayer.AXES,
                CanvasLayer.OBSERVED,
                CanvasLayer.CALCULATED_TOTAL,
                CanvasLayer.PHASE_PROFILES,
                CanvasLayer.PHYSICAL_BACKGROUND,
                CanvasLayer.DIFFERENCE,
                CanvasLayer.CANDIDATE_PREVIEW,
                CanvasLayer.PHASE_TICKS,
                CanvasLayer.ASSIGNMENT_MARKERS,
                CanvasLayer.UNKNOWN_PEAKS,
                CanvasLayer.LABELS,
                CanvasLayer.CURSOR,
                CanvasLayer.LEGENDS,
            ),
        )

    def test_tag_round_trip_preserves_owner_object_and_exportability(self):
        item = _CanvasItem()

        returned = tag_canvas_item(
            item,
            layer=CanvasLayer.PHASE_PROFILES,
            owner_id="pattern-1/phase-2",
            object_id="profile-main",
            exportable=False,
        )

        self.assertIs(returned, item)
        self.assertEqual(
            canvas_item_tag(item),
            CanvasItemTag(
                layer=CanvasLayer.PHASE_PROFILES,
                owner_id="pattern-1/phase-2",
                object_id="profile-main",
                exportable=False,
            ),
        )
        self.assertEqual(item._xrd_export_layer, "phase_profiles")
        self.assertEqual(item._xrd_export_owner_id, "pattern-1/phase-2")
        self.assertEqual(item._xrd_export_object_id, "profile-main")

    def test_string_layer_is_normalized_to_canvas_layer(self):
        item = _CanvasItem()

        tag_canvas_item(item, layer="observed")

        self.assertEqual(canvas_item_tag(item).layer, CanvasLayer.OBSERVED)

    def test_untagged_item_has_no_export_metadata(self):
        self.assertIsNone(canvas_item_tag(_CanvasItem()))

    def test_stable_svg_id_is_safe_and_collision_resistant(self):
        first = stable_svg_id("phase", "BaSiO3 / pattern 1")
        second = stable_svg_id("phase", "BaSiO3 : pattern 1")

        self.assertRegex(first, r"^[a-z][a-z0-9-]*$")
        self.assertNotEqual(first, second)

    def test_stable_svg_id_handles_unicode_and_digit_prefixes(self):
        value = stable_svg_id("2theta", "Фаза №1")

        self.assertTrue(re.fullmatch(r"[a-z][a-z0-9-]*", value))
        self.assertEqual(value, stable_svg_id("2theta", "Фаза №1"))


if __name__ == "__main__":
    unittest.main()
