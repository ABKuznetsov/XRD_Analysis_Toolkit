from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

cristma = types.ModuleType("cristma")
cristma.__path__ = []
chemistry = types.ModuleType("cristma.chemistry")
composition = types.ModuleType("cristma.chemistry.composition")
composition.Composition = object
symmetry = types.ModuleType("cristma.symmetry")
affine = types.ModuleType("cristma.symmetry.affine")
affine.format_xyz_operation = lambda operation: str(operation)
sys.modules.setdefault("cristma", cristma)
sys.modules.setdefault("cristma.chemistry", chemistry)
sys.modules.setdefault("cristma.chemistry.composition", composition)
sys.modules.setdefault("cristma.symmetry", symmetry)
sys.modules.setdefault("cristma.symmetry.affine", affine)

from xrd_finder.services.candidate_search_service import CandidateSearchOptions, CandidateSearchService
from xrd_finder.services.cod_online_service import CodEntry, CodOnlineService
import xrd_finder.services.cod_online_service as cod_online_module


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


class FakeLocalPhaseCache:
    def __init__(self, *, fresh: bool = False):
        self.fresh = fresh
        self.root = Path("cache")
        self.cif_dir = self.root / "cif"

    def search_is_fresh(self, source, key):
        return self.fresh

    def upsert_cod_entries(self, entries):
        self.cod_entries = list(entries)

    def mark_search(self, source, key):
        self.marked = (source, key)

    def record_search_attempt(self, *args, **kwargs):
        self.recorded = (args, kwargs)

    def get(self, source, entry_id):
        return None

    def cif_path(self, source, entry_id):
        return None


class FakeCcdcStatus:
    installed = False


class FakeCcdc:
    def search_text(self, *args, **kwargs):
        return []

    def status(self):
        return FakeCcdcStatus()


class FakeCodOnline:
    def __init__(self):
        self.element_calls = []
        self.entries = [
            CodEntry(
                cod_id="1000034",
                formula="- Al2 Ca O8 Si2 -",
                mineral="Anorthite",
                spacegroup="P -1",
                source="COD test",
            )
        ]

    def search_elements(self, elements, excluded_elements=None, limit=100, timeout=15.0):
        self.element_calls.append(list(elements))
        return self.entries[:limit]

    def search_text(self, query, limit=100, timeout=15.0):
        return self.entries[:limit]

    def search_formula(self, formula, limit=100, timeout=15.0):
        return self.entries[:limit]


class CandidateSearchCodTests(unittest.TestCase):
    def make_service(self, *, cache_fresh: bool = False):
        cod_online = FakeCodOnline()
        service = CandidateSearchService(
            local_phase_cache=FakeLocalPhaseCache(fresh=cache_fresh),
            cod_online=cod_online,
            ccdc=FakeCcdc(),
            rruff=None,
            match_pdf2=None,
            materials_project=None,
        )
        service.queue_background_cod_downloads = lambda entries, session_token=None: len(entries)
        return service

    def options(self):
        return CandidateSearchOptions(
            local_sources=[],
            excluded_elements=[],
            cod_online_enabled=True,
            rruff_enabled=False,
            match_pdf2_enabled=False,
            materials_project_enabled=False,
            aflow_enabled=False,
            oqmd_enabled=False,
            structural_data_enabled=True,
            reference_patterns_enabled=False,
            material_class_allowed=lambda formula: True,
            required_elements=["Al", "Ca", "O", "Si"],
            optional_elements=[],
        )

    def test_cod_element_search_returns_online_rows_before_background_indexing(self):
        rows = self.make_service().search_elements(["Al", "Ca", "O", "Si"], self.options())

        self.assertEqual(rows[0][0], "COD")
        self.assertEqual(rows[0][1], "1000034")
        self.assertIn("Al2", rows[0][2])

    def test_cod_text_search_returns_online_rows_before_background_indexing(self):
        rows = self.make_service().search_text("Anorthite", self.options())

        self.assertEqual(rows[0][0], "COD")
        self.assertEqual(rows[0][1], "1000034")

    def test_cod_optional_elements_query_specific_system_first(self):
        service = self.make_service()
        options = self.options()
        options.required_elements = ["Ca", "Si", "O"]
        options.optional_elements = ["Al"]

        rows = service.search_elements(["Ca", "Si", "O"], options)

        self.assertEqual(rows[0][0], "COD")
        self.assertEqual(service.cod_online.element_calls[0], ["Al", "Ca", "O", "Si"])

    def test_cod_retries_fresh_search_when_local_cod_rows_are_absent(self):
        service = self.make_service(cache_fresh=True)

        rows = service.search_elements(["Al", "Ca", "O", "Si"], self.options())

        self.assertEqual(rows[0][0], "COD")
        self.assertTrue(service.cod_online.element_calls)

    def test_element_discovery_can_defer_cif_downloads_until_user_confirms(self):
        service = self.make_service()
        queued = []
        service.queue_background_cod_downloads = (
            lambda entries, session_token=None: queued.extend(entries) or len(entries)
        )
        base = self.options()
        options = SimpleNamespace(
            **{
                name: getattr(base, name)
                for name in base.__slots__
                if name != "defer_candidate_preparation"
            },
            defer_candidate_preparation=True,
        )

        rows = service.search_elements(["O"], options)

        self.assertTrue(rows)
        self.assertEqual(queued, [])

    def test_confirmed_rows_are_queued_once_for_candidate_preparation(self):
        service = self.make_service()
        submitted = []
        service._queue_candidate_preparation = lambda **kwargs: submitted.append(kwargs) or True
        rows = [
            ["COD", "1000034", "Al2 Ca O8 Si2", "Anorthite", "P -1", "", "", ""],
            ["COD", "1000034", "Al2 Ca O8 Si2", "Anorthite", "P -1", "", "", ""],
        ]

        queued = service.queue_candidate_rows(rows, session_token=12)

        self.assertEqual(queued, 1)
        self.assertEqual(submitted[0]["source"], "COD")
        self.assertEqual(submitted[0]["entry_id"], "1000034")
        self.assertEqual(submitted[0]["session_token"], 12)

    def test_primary_cod_failover_is_status_only(self):
        statuses = []
        alerts = []
        service = CodOnlineService(
            status_callback=statuses.append,
            alert_callback=alerts.append,
        )

        responses = [URLError("primary unavailable"), _Response(b"[]")]
        with patch.object(cod_online_module, "ensure_online_allowed"), patch.object(
            cod_online_module,
            "urlopen",
            side_effect=responses,
        ):
            self.assertEqual(service.search_text("quartz"), [])

        self.assertEqual(alerts, [])
        self.assertTrue(any("mirror" in message.casefold() for message in statuses))

    def test_complete_cod_outage_is_status_only(self):
        statuses = []
        alerts = []
        service = CodOnlineService(
            status_callback=statuses.append,
            alert_callback=alerts.append,
        )

        with patch.object(cod_online_module, "ensure_online_allowed"), patch.object(
            cod_online_module,
            "urlopen",
            side_effect=URLError("offline"),
        ):
            with self.assertRaises(URLError):
                service.search_text("quartz")

        self.assertEqual(alerts, [])
        self.assertTrue(any("local data" in message.casefold() for message in statuses))


if __name__ == "__main__":
    unittest.main()
