"""Thread-safe progress and measured time estimates for the COD pipeline."""
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class LibraryProgressSnapshot:
    total: int
    available: int
    processed: int
    downloaded: int
    reused: int
    prepared: int
    skipped: int
    download_failed: int
    preparation_failed: int
    elapsed_seconds: float
    download_seconds: float | None
    processing_seconds: float | None
    remaining_seconds: float | None
    download_finished: bool
    finished: bool


class LibraryProgress:
    def __init__(self, total, *, clock=time.monotonic, batch_size=250, request_interval=10.):
        self.total = total
        self.clock = clock
        self.batch_size = batch_size
        self.request_interval = request_interval
        self.lock = threading.RLock()
        self.started = clock()
        self.download_started = self.processing_started = self.last_request_started = None
        self.downloaded = self.reused = self.prepared = self.skipped = 0
        self.download_failed = self.preparation_failed = 0
        self.scanned = self.download_finished = self.finished = False

    def start_download(self):
        with self.lock:
            self.last_request_started = self.clock()
            if self.download_started is None:
                self.download_started = self.last_request_started

    def start_processing(self):
        with self.lock:
            if self.processing_started is None:
                self.processing_started = self.clock()

    def file_available(self, reused):
        with self.lock:
            if reused:
                self.reused += 1
            else:
                self.downloaded += 1

    def card_ready(self, *, skipped=False, failed=False):
        with self.lock:
            if skipped:
                self.skipped += 1
            elif failed:
                self.preparation_failed += 1
            else:
                self.prepared += 1

    def scan_complete(self):
        with self.lock:
            self.scanned = True

    def finish_download(self, failed):
        with self.lock:
            self.download_failed = failed
            self.download_finished = True
            self.scanned = True

    def finish(self):
        with self.lock:
            self.finished = True

    @staticmethod
    def _estimate(remaining, completed, started, now):
        if remaining <= 0:
            return 0.
        if not completed or started is None or now <= started:
            return None
        return remaining * (now-started) / completed

    def snapshot(self):
        with self.lock:
            now = self.clock()
            available = self.downloaded+self.reused
            processed = self.prepared+self.skipped+self.preparation_failed+self.download_failed
            download_left = self.total-available-self.download_failed
            processing_left = self.total-processed
            download = self._estimate(download_left,self.downloaded,self.download_started,now)
            if self.download_finished:
                download = 0.
            elif download is not None and download_left > 0:
                # Even a fast first ZIP cannot bypass COD's request spacing.
                batches = (download_left+self.batch_size-1)//self.batch_size
                wait = batches*self.request_interval-(now-self.last_request_started)
                download = max(download,wait)
            processing = self._estimate(processing_left,self.prepared+self.preparation_failed,
                                        self.processing_started,now)
            remaining = max(download,processing) if self.scanned and download is not None and processing is not None else None
            if self.finished:
                download = processing = remaining = 0.
            return LibraryProgressSnapshot(self.total,available,processed,self.downloaded,self.reused,
                self.prepared,self.skipped,self.download_failed,self.preparation_failed,
                max(0.,now-self.started),download,processing,remaining,self.download_finished,self.finished)
