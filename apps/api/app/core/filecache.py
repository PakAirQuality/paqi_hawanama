"""Bounded on-disk cache for objects fetched from GCS (COGs, grid JSON).

Cloud Run's /tmp is memory, so an unbounded "download once per process" cache is a
memory leak, and an unbounded negative cache keyed on client input is a trivial way to
grow a process until it is killed. This keeps at most ``max_files`` downloaded files
(least recently used evicted and deleted) and at most ``max_absent`` "known missing"
keys, and serialises downloads of the same key.

Call ``get_or_download`` from a worker thread (``run_in_threadpool``): the download
callable blocks.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from typing import Callable

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class BlobMissing(Exception):
    """Raised by a downloader when the object does not exist."""


class BoundedBlobCache:
    def __init__(self, name: str, max_files: int = 32, max_absent: int = 2000) -> None:
        self.name = name
        self.max_files = max_files
        self.max_absent = max_absent
        self._files: "OrderedDict[str, str]" = OrderedDict()
        self._absent: "OrderedDict[str, None]" = OrderedDict()
        self._lock = threading.Lock()

    def get_or_download(self, key: str, download: Callable[[], str]) -> str:
        """Return a local path for ``key``; 404 if the object is known or found missing."""
        with self._lock:
            if key in self._absent:
                raise HTTPException(status_code=404, detail="Not found")
            path = self._files.get(key)
            if path is not None and os.path.exists(path):
                self._files.move_to_end(key)
                return path
            if path is not None:
                del self._files[key]
        # Download outside the lock so unrelated keys are not blocked; a second request
        # for the same key may download concurrently, which is harmless.
        try:
            path = download()
        except BlobMissing:
            with self._lock:
                self._absent[key] = None
                while len(self._absent) > self.max_absent:
                    self._absent.popitem(last=False)
            raise HTTPException(status_code=404, detail="Not found")
        except HTTPException as exc:
            if exc.status_code == 404:
                with self._lock:
                    self._absent[key] = None
                    while len(self._absent) > self.max_absent:
                        self._absent.popitem(last=False)
            raise
        with self._lock:
            existing = self._files.get(key)
            if existing is not None and existing != path:
                _unlink_quiet(path)
                self._files.move_to_end(key)
                return existing
            self._files[key] = path
            self._files.move_to_end(key)
            while len(self._files) > self.max_files:
                _, old = self._files.popitem(last=False)
                _unlink_quiet(old)
        return path

    def stats(self) -> dict:
        with self._lock:
            return {"name": self.name, "files": len(self._files), "absent": len(self._absent)}


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
