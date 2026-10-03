"""Convert uploaded photos to resized WebP."""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 60_000_000  # guard against decompression bombs


class InvalidImage(ValueError):
    pass


def to_webp(data: bytes, max_size: int, quality: int) -> tuple[bytes, int, int]:
    """Return (webp_bytes, width, height). Fixes EXIF rotation, strips metadata."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImage("too large")
    try:
        with Image.open(io.BytesIO(data)) as source:
            img: Image.Image = ImageOps.exif_transpose(source)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, "WEBP", quality=quality, method=6)
            return out.getvalue(), img.width, img.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidImage("unreadable") from exc
