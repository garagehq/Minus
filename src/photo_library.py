"""
Photo library for the screensaver-style ad replacement mode.

Users upload images via the web UI; during an ad block that rolled the
'photos' replacement mode we cycle through them every few seconds as the
blocking overlay's pixelated background. Fully local (no cloud) — Minus
runs offline.

Storage layout (under PHOTO_DIR):

    ~/.minus_media/photos/
        <sha256>.jpg      # JPEG payload (re-encoded on upload, quality 85)
        <sha256>.meta     # tiny JSON: {"name": "...", "uploaded": epoch}

We re-encode on upload to:
  - cap the size (PIL's thumbnail at PHOTO_MAX_DIM on the long edge)
  - normalize format (everything becomes JPEG)
  - strip EXIF and any embedded colour profile

That keeps each photo under a few hundred KB and makes the 24h memory
profile predictable.

Public API:
  - list_photos() -> list of dicts
  - add_photo(bytes, original_name) -> dict
  - remove_photo(photo_id) -> bool
  - get_photo_bytes(photo_id) -> bytes | None
  - random_photo_id() -> str | None
  - total_bytes() -> int

Zero network access. All helpers are pure-file operations.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import random
import threading
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("Minus.PhotoLibrary")

PHOTO_DIR = Path.home() / ".minus_media" / "photos"
PHOTO_MAX_DIM = 1920           # longest edge after re-encode
PHOTO_JPEG_QUALITY = 85
PHOTO_MAX_COUNT = 200          # hard cap — oldest evicted on add beyond this
PHOTO_MAX_BYTES = 200 * 1024 * 1024  # 200 MB total cap (24h-safe)
ALLOWED_MIME_PREFIXES = ("image/",)


class PhotoLibrary:
    """Singleton-ish filesystem-backed photo store.

    Concurrency: all write paths lock a single module-level mutex so two web
    requests uploading simultaneously can't corrupt the index. Reads are
    lock-free (filesystem is the source of truth).
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self._dir = Path(base_dir) if base_dir else PHOTO_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ---------------- read helpers (cheap, no lock) -------------------
    def list_photos(self) -> List[dict]:
        """Return all photos ordered newest-first. No PIL access here."""
        items: List[dict] = []
        for meta_path in self._dir.glob("*.meta"):
            photo_id = meta_path.stem
            jpeg_path = self._dir / f"{photo_id}.jpg"
            if not jpeg_path.exists():
                # Orphaned meta — clean up on next write path
                continue
            try:
                with meta_path.open("r") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
            try:
                size = jpeg_path.stat().st_size
            except OSError:
                continue
            items.append({
                "id": photo_id,
                "name": meta.get("name", photo_id[:8]),
                "uploaded": meta.get("uploaded", 0),
                "bytes": size,
            })
        items.sort(key=lambda x: x["uploaded"], reverse=True)
        return items

    def count(self) -> int:
        return len(list(self._dir.glob("*.jpg")))

    def total_bytes(self) -> int:
        total = 0
        for p in self._dir.glob("*.jpg"):
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    def get_photo_bytes(self, photo_id: str) -> Optional[bytes]:
        jpeg_path = self._dir / f"{self._sanitize(photo_id)}.jpg"
        if not jpeg_path.exists():
            return None
        try:
            return jpeg_path.read_bytes()
        except OSError:
            return None

    def random_photo_id(self) -> Optional[str]:
        ids = [p.stem for p in self._dir.glob("*.jpg")]
        if not ids:
            return None
        return random.choice(ids)

    # ---------------- write helpers -----------------------------------
    def add_photo(self, data: bytes, original_name: str = "photo") -> dict:
        """Normalize + persist `data`. Returns the stored photo's metadata.

        Raises ValueError on unusable input (bad format, too big, etc.).
        """
        if not data:
            raise ValueError("empty upload")
        if len(data) > 50 * 1024 * 1024:  # 50 MB per raw upload ceiling
            raise ValueError("upload too large (50 MB max before encode)")

        try:
            from PIL import Image
        except ImportError as e:
            raise RuntimeError("Pillow not available for photo encoding") from e

        try:
            img = Image.open(io.BytesIO(data))
            img.load()  # force decode — raises on bad payloads
        except Exception as e:
            raise ValueError(f"not a valid image: {e}")

        # Re-encode to JPEG, cap long edge at PHOTO_MAX_DIM.
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((PHOTO_MAX_DIM, PHOTO_MAX_DIM), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=PHOTO_JPEG_QUALITY, optimize=True)
        payload = buf.getvalue()

        photo_id = hashlib.sha256(payload).hexdigest()[:16]
        jpeg_path = self._dir / f"{photo_id}.jpg"
        meta_path = self._dir / f"{photo_id}.meta"

        with self._lock:
            self._enforce_caps(new_bytes=len(payload))
            jpeg_path.write_bytes(payload)
            meta = {
                "name": self._sanitize_name(original_name),
                "uploaded": int(time.time()),
                "bytes": len(payload),
                "dim": list(img.size),
            }
            meta_path.write_text(json.dumps(meta))
            logger.info(
                f"[PhotoLibrary] Added {photo_id} ({meta['name']}, "
                f"{len(payload)} bytes, {img.size[0]}x{img.size[1]})"
            )

        meta["id"] = photo_id
        return meta

    def remove_photo(self, photo_id: str) -> bool:
        photo_id = self._sanitize(photo_id)
        jpeg_path = self._dir / f"{photo_id}.jpg"
        meta_path = self._dir / f"{photo_id}.meta"
        removed = False
        with self._lock:
            if jpeg_path.exists():
                jpeg_path.unlink()
                removed = True
            if meta_path.exists():
                meta_path.unlink()
        return removed

    # ---------------- internals ---------------------------------------
    def _enforce_caps(self, new_bytes: int = 0):
        """Evict oldest photos until both count and total-bytes caps are safe.

        Caller holds self._lock.
        """
        photos = self.list_photos()
        # Count cap
        while len(photos) >= PHOTO_MAX_COUNT:
            oldest = photos.pop()
            self._delete_unlocked(oldest["id"])
        # Byte cap
        while photos and (sum(p["bytes"] for p in photos) + new_bytes) > PHOTO_MAX_BYTES:
            oldest = photos.pop()
            self._delete_unlocked(oldest["id"])

    def _delete_unlocked(self, photo_id: str):
        jpeg_path = self._dir / f"{photo_id}.jpg"
        meta_path = self._dir / f"{photo_id}.meta"
        try:
            if jpeg_path.exists():
                jpeg_path.unlink()
            if meta_path.exists():
                meta_path.unlink()
            logger.info(f"[PhotoLibrary] Evicted {photo_id} (cap)")
        except OSError as e:
            logger.warning(f"[PhotoLibrary] evict failed for {photo_id}: {e}")

    @staticmethod
    def _sanitize(photo_id: str) -> str:
        # Allow only hex so the id can't path-traverse
        return "".join(c for c in str(photo_id) if c in "0123456789abcdef")[:32]

    @staticmethod
    def _sanitize_name(name: str) -> str:
        name = os.path.basename(str(name or ""))
        name = name[:120]
        return name or "photo"


_singleton: Optional[PhotoLibrary] = None
_singleton_lock = threading.Lock()


def get_photo_library() -> PhotoLibrary:
    """Module-level singleton."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = PhotoLibrary()
        return _singleton
