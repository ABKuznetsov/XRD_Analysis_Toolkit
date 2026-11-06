"""Keep Windows temporary-file locks from replacing a worker's result."""
from __future__ import annotations

import logging
import os
import tempfile
import time


class WorkerTemporaryDirectory(tempfile.TemporaryDirectory):
    """Remove an owned worker directory after its process has been reaped.

    Windows readers can briefly retain stderr or another temporary file even
    after the worker exits. Retry cleanup for at most 100 ms. If still locked,
    leave only that temporary remainder rather than discard a completed result,
    cancellation, or the original calculation error. Other errors propagate.
    """

    def cleanup(self):
        for delay in (0., .01, .03, .06):
            if delay:
                time.sleep(delay)
            try:
                return super().cleanup()
            except OSError as error:
                if os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32, 33):
                    raise
        logging.getLogger(__name__).debug('Worker temporary directory is still locked: %s', self.name)
