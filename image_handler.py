from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image

from astrbot.api import logger


class ImageHandler:
    """Handles image downloading and processing for the Pixiv plugin."""

    def __init__(
        self,
        cache_dir: Path,
        pixiv_call_func,
    ) -> None:
        self._cache_dir = cache_dir
        self._pixiv_call = pixiv_call_func

    @staticmethod
    def safe_filename_from_url(url: str, fallback: str) -> str:
        """Generate a safe filename from a URL."""
        raw = Path(urlsplit(url).path).name
        name = raw if raw else fallback
        return re.sub(r"[^a-zA-Z0-9._-]+", "_", name) or fallback

    async def download_image_to_cache(
        self,
        image_url: str,
        *,
        access_token: str | None,
        refresh_token: str,
        name_prefix: str,
    ) -> str:
        """Download an image to the cache directory and return the local path."""
        image_result = await self._pixiv_call(
            "image",
            {"url": image_url},
            access_token=access_token,
            refresh_token=refresh_token,
        )
        if not image_result.get("ok"):
            raise RuntimeError(self.format_pixiv_error(image_result))

        content = image_result.get("content")
        if not isinstance(content, (bytes, bytearray)):
            raise RuntimeError("Pixiv 图片响应未返回二进制内容。")

        safe_name = self.safe_filename_from_url(image_url, f"{name_prefix}.bin")
        target = (
            self._cache_dir / f"{name_prefix}_{int(time.time() * 1000)}_{safe_name}"
        )
        target.write_bytes(bytes(content))
        return str(target)

    async def download_ugoira_zip_to_cache(
        self,
        zip_url: str,
        *,
        access_token: str | None,
        refresh_token: str,
        name_prefix: str,
    ) -> str:
        """Download an ugoira zip file to the cache directory."""
        zip_result = await self._pixiv_call(
            "ugoira_zip",
            {"url": zip_url},
            access_token=access_token,
            refresh_token=refresh_token,
        )
        if not zip_result.get("ok"):
            raise RuntimeError(self.format_pixiv_error(zip_result))

        content = zip_result.get("content")
        if not isinstance(content, (bytes, bytearray)):
            raise RuntimeError("Pixiv 动图 zip 响应未返回二进制内容。")

        safe_name = self.safe_filename_from_url(zip_url, f"{name_prefix}.zip")
        target = (
            self._cache_dir / f"{name_prefix}_{int(time.time() * 1000)}_{safe_name}"
        )
        target.write_bytes(bytes(content))
        return str(target)

    def render_ugoira_to_gif(
        self,
        zip_path: str,
        frames: list[dict[str, Any]],
        output_path: str,
    ) -> None:
        """Render ugoira zip to GIF, fallback to ffmpeg if PIL fails."""
        try:
            self._render_ugoira_with_pil(zip_path, frames, output_path)
        except Exception as pil_exc:
            logger.warning(
                "[pixivdirect] PIL GIF render failed: %s, trying ffmpeg", pil_exc
            )
            self._render_ugoira_with_ffmpeg(zip_path, frames, output_path)

    def _render_ugoira_with_pil(
        self,
        zip_path: str,
        frames: list[dict[str, Any]],
        output_path: str,
    ) -> None:
        """Render ugoira zip to GIF using PIL."""
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            frame_delays = {}
            for frame in frames:
                file_name = frame.get("file", "")
                delay = frame.get("delay", 100)
                if file_name:
                    frame_delays[file_name] = delay

            image_files = sorted(
                [
                    f
                    for f in zip_file.namelist()
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))
                ]
            )

            if not image_files:
                raise RuntimeError("动图 zip 文件中没有找到图像文件。")

            pil_frames = []
            delays = []
            for image_file in image_files:
                with zip_file.open(image_file) as f:
                    img = Image.open(io.BytesIO(f.read()))
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    pil_frames.append(img)
                    delay = frame_delays.get(image_file, 100)
                    delays.append(delay)

            if not pil_frames:
                raise RuntimeError("无法读取动图帧。")

            pil_frames[0].save(
                output_path,
                save_all=True,
                append_images=pil_frames[1:],
                duration=delays,
                loop=0,
                optimize=True,
            )

    def _render_ugoira_with_ffmpeg(
        self,
        zip_path: str,
        frames: list[dict[str, Any]],
        output_path: str,
    ) -> None:
        """Render ugoira zip to GIF using ffmpeg."""
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg 未安装，无法渲染动图。")

        frame_delays = {}
        for frame in frames:
            file_name = frame.get("file", "")
            delay = frame.get("delay", 100)
            if file_name:
                frame_delays[file_name] = delay

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            with zipfile.ZipFile(zip_path, "r") as zip_file:
                image_files = sorted(
                    [
                        f
                        for f in zip_file.namelist()
                        if f.lower().endswith((".jpg", ".jpeg", ".png"))
                    ]
                )
                if not image_files:
                    raise RuntimeError("动图 zip 文件中没有找到图像文件。")

                for i, image_file in enumerate(image_files):
                    zip_file.extract(image_file, tmpdir)
                    src = tmpdir_path / image_file
                    dst = tmpdir_path / f"frame_{i:05d}.jpg"
                    src.rename(dst)

            # Build concat file for ffmpeg with per-frame duration
            concat_file = tmpdir_path / "concat.txt"
            concat_lines = []
            for i, image_file in enumerate(image_files):
                delay_ms = frame_delays.get(image_file, 100)
                duration_sec = delay_ms / 1000.0
                concat_lines.append(
                    f"file 'frame_{i:05d}.jpg'\nduration {duration_sec}"
                )
            # Repeat last frame (ffmpeg concat requirement)
            concat_lines.append(f"file 'frame_{len(image_files) - 1:05d}.jpg'")
            concat_file.write_text("\n".join(concat_lines), encoding="utf-8")

            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-vf",
                    "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                    "-loop",
                    "0",
                    output_path,
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg 渲染动图失败: {result.stderr[:500]}")

    @staticmethod
    def format_pixiv_error(result: dict[str, Any]) -> str:
        """Format a Pixiv API error result into a user-friendly message."""
        status = result.get("status")
        error = result.get("error")
        if isinstance(error, dict):
            for key in ("message", "user_message"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return f"Pixiv API 错误（状态码={status}）：{value}"
            return f"Pixiv API 错误（状态码={status}）：{error}"
        if error:
            return f"Pixiv API 错误（状态码={status}）：{error}"
        return f"Pixiv API 请求失败（状态码={status}）。"
