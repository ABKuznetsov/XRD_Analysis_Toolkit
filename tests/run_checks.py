"""Run active checks with real Qt and isolated, offline user data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path, help='Optional machine-readable result file')
    parser.add_argument('-q', '--quiet', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path[:0] = [str(root), str(root/'tests')]
    with tempfile.TemporaryDirectory(prefix='xrd-active-tests-') as folder:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        os.environ['XRD_FINDER_OFFLINE'] = '1'
        os.environ['XRD_FINDER_DATA_DIR'] = folder
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        suite = unittest.defaultTestLoader.discover(str(root/'tests'))
        result = unittest.TextTestRunner(verbosity=1 if args.quiet else 2).run(suite)
        summary = {'run': result.testsRun, 'failures': [(str(t), e) for t,e in result.failures],
                   'errors': [(str(t), e) for t,e in result.errors],
                   'skipped': [(str(t), e) for t,e in result.skipped]}
        if args.json is not None:
            args.json.write_text(json.dumps(summary, indent=2))
        print('Tests', result.testsRun, 'failures', len(result.failures),
              'errors', len(result.errors), 'skipped', len(result.skipped), flush=True)
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
