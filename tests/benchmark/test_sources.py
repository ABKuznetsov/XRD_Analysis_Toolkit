from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from benchmarks.match.sources import SourceSpec, fetch_pinned_source


class SourceTests(unittest.TestCase):
    def test_fetches_and_verifies_pinned_local_source_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xye"
            source.write_bytes(b"10 100 1\n11 80 1\n")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()

            fetched = fetch_pinned_source(
                SourceSpec("sample", source.as_uri(), digest, "sample.xye"),
                root / "cache",
            )

            self.assertEqual(fetched.read_bytes(), source.read_bytes())
            self.assertFalse((root / "cache" / "sample.xye.part").exists())

    def test_bad_hash_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xye"
            source.write_bytes(b"unexpected")
            cache = root / "cache"

            with self.assertRaises(ValueError):
                fetch_pinned_source(
                    SourceSpec("sample", source.as_uri(), "0" * 64, "sample.xye"),
                    cache,
                )

            self.assertFalse((cache / "sample.xye").exists())
            self.assertFalse((cache / "sample.xye.part").exists())


if __name__ == "__main__":
    unittest.main()
