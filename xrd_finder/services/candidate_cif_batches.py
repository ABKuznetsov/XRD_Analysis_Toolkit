"""Lazy, bounded CIF downloads shared by manual and background preparation."""
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CifBatchDownloadResult:
    paths: dict[str, Path] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    downloaded: int = 0
    reused: int = 0


class CandidateCifDownloads:
    """The serial worker fetches a batch, then indexes each card independently."""
    BATCH_SIZE = 100

    def __init__(self, service, entry_ids, target_dir, *, active, cancelled=None):
        self.service = service
        self.target_dir = target_dir
        self.active = active
        self.cancelled = cancelled or (lambda: False)
        ids = list(dict.fromkeys(entry_ids))
        self.batches = {key: tuple(ids[offset:offset + self.BATCH_SIZE])
                        for offset in range(0, len(ids), self.BATCH_SIZE)
                        for key in ids[offset:offset + self.BATCH_SIZE]}
        self.results = {}

    def fetch(self, entry_id):
        batch = self.batches.get(entry_id, (entry_id,))
        cancelled = lambda: self.cancelled() or not self.active(batch)
        if cancelled():
            raise CancelledError('Candidate download cancelled')
        if batch not in self.results:
            try:
                result = self.service.download_cifs(batch, self.target_dir,
                    batch_size=self.BATCH_SIZE, cancelled=cancelled)
            except CancelledError:
                raise
            except Exception as error:
                result = CifBatchDownloadResult(errors={key: str(error) for key in batch})
            self.results[batch] = result
        if cancelled():
            raise CancelledError('Candidate download cancelled')
        result = self.results[batch]
        if entry_id not in result.paths:
            raise ValueError(result.errors.get(entry_id, 'Database returned no CIF for this card'))
        return result.paths[entry_id]
