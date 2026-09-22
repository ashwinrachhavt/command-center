"""Private, immutable content-addressed bytes; Blob owns database metadata."""

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

MAX_BLOB_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    storage_key: str
    byte_size: int


class BlobStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        for directory in (self.root, self.root / "sha256"):
            if directory.is_symlink():
                raise ValueError("Blob storage cannot be a symbolic link")
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.chmod(0o700)

    def path(self, sha256: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("Invalid blob digest")
        target = self.root / "sha256" / sha256
        if any(path.is_symlink() for path in (self.root, target.parent, target)):
            raise ValueError("Blob storage cannot contain symbolic links")
        return target

    def read(self, sha256: str) -> bytes:
        target = self.path(sha256)
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as file:
            metadata = os.fstat(file.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BLOB_BYTES:
                raise ValueError("Invalid stored blob")
            data = file.read(MAX_BLOB_BYTES + 1)
        if len(data) > MAX_BLOB_BYTES or hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError("Stored blob failed its integrity check")
        return data

    def put(self, data: bytes) -> StoredBlob:
        if not data or len(data) > MAX_BLOB_BYTES:
            raise ValueError("Document must contain at most 20 MiB")
        digest = hashlib.sha256(data).hexdigest()
        target = self.path(digest)
        temporary = target.parent / f".upload-{uuid4().hex}"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            try:
                # Linking publishes a complete file without overwriting a concurrent upload.
                os.link(temporary, target, follow_symlinks=False)
            except FileExistsError:
                if self.read(digest) != data:
                    raise ValueError("Stored blob does not match uploaded content") from None
        finally:
            temporary.unlink(missing_ok=True)
        return StoredBlob(digest, f"sha256/{digest}", len(data))
