"""Original-file storage.

Files are written in chunks while their SHA-256 hash is computed, so a
200 MB upload never sits in memory. They are stored under their hash, so a
user-supplied filename never reaches the file system (no path traversal)
and identical uploads share one copy.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import BinaryIO

from .config import get_settings

CHUNK = 1024 * 1024


class FileTooLarge(Exception):
    pass


@dataclass
class StoredFile:
    sha256: str
    size_bytes: int
    relative_path: str
    head: bytes  # first 8 KB, for type detection


def root() -> str:
    path = os.path.abspath(get_settings().storage_dir)
    os.makedirs(path, exist_ok=True)
    return path


def absolute(relative_path: str) -> str:
    full = os.path.abspath(os.path.join(root(), relative_path))
    if not full.startswith(root() + os.sep):
        raise ValueError("path escapes the storage directory")
    return full


def save_stream(src: BinaryIO, max_bytes: int) -> StoredFile:
    digest = hashlib.sha256()
    size = 0
    head = b""
    fd, tmp = tempfile.mkstemp(dir=root(), prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := src.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise FileTooLarge()
                if len(head) < 8192:
                    head += chunk[: 8192 - len(head)]
                digest.update(chunk)
                out.write(chunk)
        sha = digest.hexdigest()
        rel = os.path.join(sha[:2], sha)
        dest = absolute(rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            os.remove(tmp)
        else:
            shutil.move(tmp, dest)
        return StoredFile(sha, size, rel, head)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
