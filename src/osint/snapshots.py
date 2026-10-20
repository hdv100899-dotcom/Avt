"""Content-addressed, write-once store for evidence (feed entries, article pages).

Posts get edited and deleted; what we saw at collection time must stay fixed.
"""

import gzip
import hashlib
import os
import tempfile
from pathlib import Path


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def put(self, data: bytes, ext: str) -> str:
        """Store ``data`` gzip-compressed and return its reference (path relative to root)."""
        digest = hashlib.sha256(data).hexdigest()
        ref = f"{digest[:2]}/{digest}.{ext}.gz"
        path = self.root / ref
        if path.exists():
            return ref
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(gzip.compress(data, mtime=0))
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return ref

    def get(self, ref: str) -> bytes:
        return gzip.decompress((self.root / ref).read_bytes())
