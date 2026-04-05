from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image


class ImageHandler:
    def __init__(self, cache_dir: Path, pixiv_call_func) -> None:
        self._cache_dir = cache_dir
        self._pixiv_call = pixiv_call_func

    @staticmethod
    def safe_filename(url: str, fallback: str) -> str:
        name = Path(urlsplit(url).path).name
        return name or fallback

    async def download_image_to_cache(
        self,
        image_url: str,
        *,
        refresh_token: str,
        access_token: str | None = None,
        file_stem: str,
    ) -> str:
        result = await self._pixiv_call(
            "image",
            {"url": image_url},
            refresh_token=refresh_token,
            access_token=access_token,
        )
        if not result.get("ok"):
            raise RuntimeError(self.format_pixiv_error(result))
        content = result.get("content")
        if not isinstance(content, (bytes, bytearray)):
            raise RuntimeError("图片下载失败：未返回二进制内容。")
        suffix = Path(self.safe_filename(image_url, "image.bin")).suffix or ".bin"
        target = self._cache_dir / f"{file_stem}_{int(time.time() * 1000)}{suffix}"
        target.write_bytes(bytes(content))
        return str(target)

    async def download_ugoira_zip_to_cache(
        self,
        zip_url: str,
        *,
        refresh_token: str,
        access_token: str | None = None,
        file_stem: str,
    ) -> str:
        result = await self._pixiv_call(
            "ugoira_zip",
            {"url": zip_url},
            refresh_token=refresh_token,
            access_token=access_token,
        )
        if not result.get("ok"):
            raise RuntimeError(self.format_pixiv_error(result))
        content = result.get("content")
        if not isinstance(content, (bytes, bytearray)):
            raise RuntimeError("动图 zip 下载失败：未返回二进制内容。")
        target = self._cache_dir / f"{file_stem}_{int(time.time() * 1000)}.zip"
        target.write_bytes(bytes(content))
        return str(target)

    def render_ugoira_to_gif(
        self,
        zip_path: str,
        frames: list[dict[str, Any]],
        output_path: str,
    ) -> None:
        delays = {frame.get("file"): int(frame.get("delay", 100)) for frame in frames}
        with zipfile.ZipFile(zip_path) as archive:
            image_names = [
                name
                for name in sorted(archive.namelist())
                if name.lower().endswith((".jpg", ".jpeg", ".png"))
            ]
            if not image_names:
                raise RuntimeError("动图 zip 中没有图像帧。")
            images: list[Image.Image] = []
            durations: list[int] = []
            for name in image_names:
                with archive.open(name) as fp:
                    image = Image.open(io.BytesIO(fp.read()))
                    images.append(image.convert("RGBA"))
                    durations.append(delays.get(name, 100))
            first = images[0]
            first.save(
                output_path,
                save_all=True,
                append_images=images[1:],
                duration=durations,
                loop=0,
                optimize=False,
            )

    @staticmethod
    def format_pixiv_error(result: dict[str, Any]) -> str:
        status = result.get("status", "?")
        error = result.get("error")
        if isinstance(error, dict):
            message = (
                error.get("message")
                or error.get("error_description")
                or error.get("user_message")
            )
            if isinstance(message, str) and message:
                return f"Pixiv 请求失败（{status}）：{message}"
        return f"Pixiv 请求失败（{status}）。"
