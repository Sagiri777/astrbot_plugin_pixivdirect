from __future__ import annotations

import asyncio
import os
from pathlib import Path

from PIL import Image

from image_handler import ImageHandler


def _build_handler(cache_dir: Path) -> ImageHandler:
    return ImageHandler(cache_dir=cache_dir, pixiv_call_func=None)


def test_prepare_image_for_send_creates_aiocqhttp_safe_cache(tmp_path: Path) -> None:
    source = tmp_path / "oversized.png"
    image = Image.frombytes("RGB", (3000, 2500), os.urandom(3000 * 2500 * 3))
    image.save(source, format="PNG")

    handler = _build_handler(tmp_path)
    prepared = asyncio.run(
        handler.prepare_image_for_send(
            str(source),
            platform_name="aiocqhttp",
        )
    )

    assert prepared is not None
    assert prepared != str(source)
    prepared_path = Path(prepared)
    assert prepared_path.exists()
    assert prepared_path.suffix.lower() == ".jpg"
    assert prepared_path.stat().st_size <= handler._AIOCQHTTP_SEND_MAX_BYTES

    with Image.open(prepared_path) as optimized:
        assert max(optimized.size) <= handler._AIOCQHTTP_SEND_MAX_EDGE
        assert (
            optimized.size[0] * optimized.size[1]
            <= handler._AIOCQHTTP_SEND_MAX_PIXELS
        )

    prepared_again = asyncio.run(
        handler.prepare_image_for_send(
            str(source),
            platform_name="aiocqhttp",
        )
    )
    assert prepared_again == prepared


def test_prepare_image_for_send_keeps_safe_or_other_platform_images(
    tmp_path: Path,
) -> None:
    source = tmp_path / "safe.jpg"
    Image.new("RGB", (1280, 720), (120, 140, 180)).save(
        source,
        format="JPEG",
        quality=85,
    )

    handler = _build_handler(tmp_path)

    same_platform = asyncio.run(
        handler.prepare_image_for_send(
            str(source),
            platform_name="aiocqhttp",
        )
    )
    other_platform = asyncio.run(
        handler.prepare_image_for_send(
            str(source),
            platform_name="telegram",
        )
    )

    assert same_platform == str(source)
    assert other_platform == str(source)
