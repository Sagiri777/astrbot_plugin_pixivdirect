from __future__ import annotations

import asyncio
import hashlib
import io
import math
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image, ImageFilter, ImageOps, ImageSequence

from astrbot.api import logger


class ImageHandler:
    """Handles image downloading and processing for the Pixiv plugin."""

    _AIOCQHTTP_SEND_MAX_BYTES = 3 * 1024 * 1024
    _AIOCQHTTP_SEND_MAX_EDGE = 2560
    _AIOCQHTTP_SEND_MAX_PIXELS = 6_000_000
    _AIOCQHTTP_SEND_DIRECT_FORMATS = {".jpg", ".jpeg"}
    _AIOCQHTTP_SEND_QUALITIES = (90, 84, 78, 72, 66, 60, 54)
    _AIOCQHTTP_SEND_RESIZE_FACTORS = (1.0, 0.9, 0.8, 0.7, 0.6)
    _RESAMPLE_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")

    def __init__(
        self,
        cache_dir: Path,
        pixiv_call_func,
    ) -> None:
        self._cache_dir = cache_dir
        self._pixiv_call = pixiv_call_func

    @staticmethod
    def _apply_blur_to_pil(image: Image.Image, strength: int) -> Image.Image:
        radius = max(1, min(100, strength)) / 2.0
        return image.filter(ImageFilter.GaussianBlur(radius=radius))

    @staticmethod
    def _apply_hajimi_to_pil(image: Image.Image) -> Image.Image:
        from .hajimi_mosaic import apply_hajimi_mosaic_to_pil

        return apply_hajimi_mosaic_to_pil(image)

    def _apply_censor_to_pil(
        self,
        image: Image.Image,
        *,
        mode: str,
        blur_strength: int,
    ) -> Image.Image:
        if mode == "blur":
            return self._apply_blur_to_pil(image, blur_strength)
        if mode == "hajimi":
            return self._apply_hajimi_to_pil(image)
        raise ValueError(f"Unsupported censor mode: {mode}")

    @staticmethod
    def safe_filename_from_url(url: str, fallback: str) -> str:
        """Generate a safe filename from a URL."""
        raw = Path(urlsplit(url).path).name
        name = raw if raw else fallback
        return re.sub(r"[^a-zA-Z0-9._-]+", "_", name) or fallback

    async def _download_binary_to_cache(
        self,
        action: str,
        resource_url: str,
        *,
        access_token: str | None,
        refresh_token: str,
        name_prefix: str,
        fallback_name: str,
        binary_label: str,
    ) -> str:
        logger.info(
            "[pixivdirect] Requesting %s via action=%s, url=%s, prefix=%s",
            binary_label,
            action,
            resource_url,
            name_prefix,
        )
        result = await self._pixiv_call(
            action,
            {"url": resource_url},
            access_token=access_token,
            refresh_token=refresh_token,
        )
        if not result.get("ok"):
            logger.warning(
                "[pixivdirect] %s request failed, action=%s, status=%s, url=%s",
                binary_label,
                action,
                result.get("status"),
                resource_url,
            )
            raise RuntimeError(self.format_pixiv_error(result))

        content = result.get("content")
        if not isinstance(content, (bytes, bytearray)):
            raise RuntimeError(f"Pixiv {binary_label}响应未返回二进制内容。")

        safe_name = self.safe_filename_from_url(resource_url, fallback_name)
        target = (
            self._cache_dir / f"{name_prefix}_{int(time.time() * 1000)}_{safe_name}"
        )
        target.write_bytes(bytes(content))
        logger.info(
            "[pixivdirect] Saved %s to %s (%d bytes)",
            binary_label,
            target,
            len(content),
        )
        return str(target)

    @staticmethod
    def _collect_frame_delays(frames: list[dict[str, Any]]) -> dict[str, int]:
        frame_delays: dict[str, int] = {}
        for frame in frames:
            file_name = frame.get("file", "")
            delay = frame.get("delay", 100)
            if file_name:
                frame_delays[file_name] = delay
        return frame_delays

    @staticmethod
    def _list_archive_image_files(zip_file: zipfile.ZipFile) -> list[str]:
        return sorted(
            [
                name
                for name in zip_file.namelist()
                if name.lower().endswith((".jpg", ".jpeg", ".png"))
            ]
        )

    async def download_image_to_cache(
        self,
        image_url: str,
        *,
        access_token: str | None,
        refresh_token: str,
        name_prefix: str,
    ) -> str:
        """Download an image to the cache directory and return the local path."""
        return await self._download_binary_to_cache(
            "image",
            image_url,
            access_token=access_token,
            refresh_token=refresh_token,
            name_prefix=name_prefix,
            fallback_name=f"{name_prefix}.bin",
            binary_label="图片",
        )

    async def download_ugoira_zip_to_cache(
        self,
        zip_url: str,
        *,
        access_token: str | None,
        refresh_token: str,
        name_prefix: str,
    ) -> str:
        """Download an ugoira zip file to the cache directory."""
        return await self._download_binary_to_cache(
            "ugoira_zip",
            zip_url,
            access_token=access_token,
            refresh_token=refresh_token,
            name_prefix=name_prefix,
            fallback_name=f"{name_prefix}.zip",
            binary_label="动图 zip",
        )

    def render_ugoira_to_gif(
        self,
        zip_path: str,
        frames: list[dict[str, Any]],
        output_path: str,
    ) -> None:
        """Render ugoira zip to GIF, fallback to ffmpeg if PIL fails."""
        logger.info(
            "[pixivdirect] Rendering ugoira zip=%s to gif=%s with %d frames",
            zip_path,
            output_path,
            len(frames),
        )
        try:
            self._render_ugoira_with_pil(zip_path, frames, output_path)
            logger.info("[pixivdirect] Ugoira rendered with PIL: %s", output_path)
        except Exception as pil_exc:
            logger.warning(
                "[pixivdirect] PIL GIF render failed: %s, trying ffmpeg", pil_exc
            )
            self._render_ugoira_with_ffmpeg(zip_path, frames, output_path)
            logger.info("[pixivdirect] Ugoira rendered with ffmpeg: %s", output_path)

    def _render_ugoira_with_pil(
        self,
        zip_path: str,
        frames: list[dict[str, Any]],
        output_path: str,
    ) -> None:
        """Render ugoira zip to GIF using PIL."""
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            frame_delays = self._collect_frame_delays(frames)
            image_files = self._list_archive_image_files(zip_file)
            logger.info(
                "[pixivdirect] PIL ugoira render reading %d image files from %s",
                len(image_files),
                zip_path,
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
        logger.info(
            "[pixivdirect] Falling back to ffmpeg for ugoira render: %s -> %s",
            zip_path,
            output_path,
        )

        frame_delays = self._collect_frame_delays(frames)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            with zipfile.ZipFile(zip_path, "r") as zip_file:
                image_files = self._list_archive_image_files(zip_file)
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

    async def create_censored_image(
        self,
        image_path: str,
        *,
        name_prefix: str,
        mode: str,
        blur_strength: int = 12,
    ) -> str:
        """Create a censored variant of an image for safer delivery."""
        logger.info(
            "[pixivdirect] Scheduling %s censor generation for %s",
            mode,
            image_path,
        )
        return await asyncio.to_thread(
            self._create_censored_image_sync,
            image_path,
            name_prefix,
            mode,
            blur_strength,
        )

    async def create_mosaic_image(
        self,
        image_path: str,
        *,
        name_prefix: str,
    ) -> str:
        """Backward-compatible wrapper for Hajimi mosaic generation."""
        return await self.create_censored_image(
            image_path,
            name_prefix=name_prefix,
            mode="hajimi",
        )

    async def prepare_image_for_send(
        self,
        image_path: str | None,
        *,
        platform_name: str,
    ) -> str | None:
        """Prepare a local image for safer platform delivery."""
        if not image_path or platform_name != "aiocqhttp":
            return image_path

        try:
            return await asyncio.to_thread(
                self._prepare_aiocqhttp_image_for_send_sync,
                image_path,
            )
        except Exception as exc:
            logger.warning(
                "[pixivdirect] Failed to optimize image for aiocqhttp send %s: %s",
                image_path,
                exc,
            )
            return image_path

    def _create_censored_image_sync(
        self,
        image_path: str,
        name_prefix: str,
        mode: str,
        blur_strength: int,
    ) -> str:
        source = Path(image_path)
        if not source.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        stat = source.stat()
        digest = hashlib.md5(
            f"{source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}".encode()
        ).hexdigest()[:12]
        suffix = source.suffix.lower()
        target_suffix = (
            suffix if suffix in {".gif", ".jpg", ".jpeg", ".png", ".webp"} else ".png"
        )
        target = self._cache_dir / (
            f"{name_prefix}_{digest}_{mode}_{blur_strength}{target_suffix}"
        )
        if target.exists():
            logger.info("[pixivdirect] Reusing existing censored cache %s", target)
            return str(target)

        logger.info(
            "[pixivdirect] Creating new %s censored cache %s from %s",
            mode,
            target,
            source,
        )
        with Image.open(source) as img:
            is_animated = bool(getattr(img, "is_animated", False))
            if is_animated:
                logger.info(
                    "[pixivdirect] Source image is animated, rendering censored GIF"
                )
                self._save_animated_censor(
                    img,
                    target,
                    mode=mode,
                    blur_strength=blur_strength,
                )
            else:
                frame = (
                    img.convert("RGBA") if img.mode == "RGBA" else img.convert("RGB")
                )
                censored = self._apply_censor_to_pil(
                    frame,
                    mode=mode,
                    blur_strength=blur_strength,
                )
                self._save_single_frame(censored, target, target_suffix)

        logger.info("[pixivdirect] Censored image saved to %s", target)
        return str(target)

    @staticmethod
    def _flatten_to_rgb(image: Image.Image) -> Image.Image:
        normalized = ImageOps.exif_transpose(image)
        if normalized.mode in {"RGBA", "LA"}:
            background = Image.new("RGB", normalized.size, (255, 255, 255))
            alpha = normalized.getchannel("A")
            background.paste(normalized.convert("RGBA"), mask=alpha)
            return background
        if normalized.mode == "P" and "transparency" in normalized.info:
            rgba = normalized.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        return normalized.convert("RGB")

    @classmethod
    def _delivery_resize_ratio(cls, width: int, height: int) -> float:
        if width <= 0 or height <= 0:
            return 1.0

        ratio = 1.0
        max_edge = max(width, height)
        if max_edge > cls._AIOCQHTTP_SEND_MAX_EDGE:
            ratio = min(ratio, cls._AIOCQHTTP_SEND_MAX_EDGE / max_edge)

        pixels = width * height
        if pixels > cls._AIOCQHTTP_SEND_MAX_PIXELS:
            ratio = min(
                ratio,
                math.sqrt(cls._AIOCQHTTP_SEND_MAX_PIXELS / pixels),
            )

        return min(1.0, ratio)

    @classmethod
    def _resize_for_delivery(cls, image: Image.Image) -> Image.Image:
        width, height = image.size
        ratio = cls._delivery_resize_ratio(width, height)
        if ratio >= 0.999:
            return image

        resized = image.resize(
            (
                max(1, int(width * ratio)),
                max(1, int(height * ratio)),
            ),
            cls._RESAMPLE_LANCZOS,
        )
        logger.info(
            "[pixivdirect] Resized aiocqhttp send image from %sx%s to %sx%s",
            width,
            height,
            resized.width,
            resized.height,
        )
        return resized

    @classmethod
    def _encode_delivery_jpeg(
        cls,
        image: Image.Image,
    ) -> tuple[bytes, int]:
        best_bytes = b""
        best_quality = cls._AIOCQHTTP_SEND_QUALITIES[-1]
        best_size = 0

        for resize_factor in cls._AIOCQHTTP_SEND_RESIZE_FACTORS:
            working = image
            if resize_factor < 0.999:
                working = image.resize(
                    (
                        max(1, int(image.width * resize_factor)),
                        max(1, int(image.height * resize_factor)),
                    ),
                    cls._RESAMPLE_LANCZOS,
                )

            for quality in cls._AIOCQHTTP_SEND_QUALITIES:
                buffer = io.BytesIO()
                working.save(
                    buffer,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=True,
                )
                payload = buffer.getvalue()
                payload_size = len(payload)
                if not best_bytes or payload_size < best_size:
                    best_bytes = payload
                    best_quality = quality
                    best_size = payload_size
                if payload_size <= cls._AIOCQHTTP_SEND_MAX_BYTES:
                    return payload, quality

        return best_bytes, best_quality

    def _prepare_aiocqhttp_image_for_send_sync(self, image_path: str) -> str:
        source = Path(image_path)
        if not source.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        stat = source.stat()
        digest = hashlib.md5(
            f"{source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}".encode()
        ).hexdigest()[:12]
        target = self._cache_dir / f"sendsafe_{source.stem}_{digest}.jpg"
        if target.exists():
            return str(target)

        with Image.open(source) as image:
            if bool(getattr(image, "is_animated", False)):
                logger.info(
                    "[pixivdirect] Skipping aiocqhttp delivery optimization for animated image %s",
                    source,
                )
                return str(source)

            source_suffix = source.suffix.lower()
            should_reencode = (
                source_suffix not in self._AIOCQHTTP_SEND_DIRECT_FORMATS
                or image.format not in {"JPEG", "MPO"}
            )
            if (
                not should_reencode
                and stat.st_size <= self._AIOCQHTTP_SEND_MAX_BYTES
                and self._delivery_resize_ratio(*image.size) >= 0.999
            ):
                return str(source)

            flattened = self._flatten_to_rgb(image)
            resized = self._resize_for_delivery(flattened)
            payload, quality = self._encode_delivery_jpeg(resized)
            if not payload:
                return str(source)

        target.write_bytes(payload)
        logger.info(
            "[pixivdirect] Prepared aiocqhttp send cache %s from %s (%d -> %d bytes, quality=%s)",
            target,
            source,
            stat.st_size,
            len(payload),
            quality,
        )
        return str(target)

    def _save_animated_censor(
        self,
        image: Image.Image,
        target: Path,
        *,
        mode: str,
        blur_strength: int,
    ) -> None:
        frames: list[Image.Image] = []
        durations: list[int] = []
        loop = int(image.info.get("loop", 0))
        logger.info(
            "[pixivdirect] Processing animated %s censor with loop=%s",
            mode,
            loop,
        )

        for frame in ImageSequence.Iterator(image):
            rgba = (
                frame.convert("RGBA") if frame.mode == "RGBA" else frame.convert("RGB")
            )
            censored = self._apply_censor_to_pil(
                rgba,
                mode=mode,
                blur_strength=blur_strength,
            )
            frames.append(censored)
            durations.append(
                int(frame.info.get("duration", image.info.get("duration", 100)))
            )

        if not frames:
            raise RuntimeError("无法读取动态图像帧。")

        frames[0].save(
            target,
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=loop,
            disposal=2,
        )

    @staticmethod
    def _save_single_frame(image: Image.Image, target: Path, suffix: str) -> None:
        if suffix in {".jpg", ".jpeg"}:
            image.convert("RGB").save(target, quality=95)
            return
        image.save(target)

    @staticmethod
    def format_pixiv_error(result: dict[str, Any]) -> str:
        """Format a Pixiv API error result into a user-friendly message."""
        status = result.get("status")
        error = result.get("error")
        suffix_parts: list[str] = []
        fallback_chain = result.get("fallback_chain")
        if isinstance(fallback_chain, list) and fallback_chain:
            suffix_parts.append(" -> ".join(str(part) for part in fallback_chain))
        if result.get("proxy_used"):
            suffix_parts.append("已尝试代理")
        suffix = f"（{', '.join(suffix_parts)}）" if suffix_parts else ""
        if isinstance(error, dict):
            for key in ("message", "user_message"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return f"Pixiv API 错误（状态码={status}）{suffix}：{value}"
            return f"Pixiv API 错误（状态码={status}）{suffix}：{error}"
        if error:
            return f"Pixiv API 错误（状态码={status}）{suffix}：{error}"
        return f"Pixiv API 请求失败（状态码={status}）{suffix}。"
