from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import requests

from astrbot.api import logger


class ImageHostHandler:
    """Uploads local images to a generic HTTP image host."""

    @staticmethod
    def _extract_by_path(payload: Any, dotted_path: str) -> str | None:
        current = payload
        for segment in [part for part in dotted_path.split(".") if part]:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
                continue
            if isinstance(current, list) and segment.isdigit():
                index = int(segment)
                if 0 <= index < len(current):
                    current = current[index]
                    continue
            return None
        if isinstance(current, str) and current.strip():
            return current.strip()
        return None

    @staticmethod
    def is_enabled(config: dict[str, Any]) -> bool:
        return bool(config.get("enabled")) and bool(
            str(config.get("endpoint") or "").strip()
        )

    @classmethod
    def _upload_sync(cls, image_path: str, config: dict[str, Any]) -> str | None:
        endpoint = str(config.get("endpoint") or "").strip()
        if not endpoint:
            return None

        method = str(config.get("method") or "post").strip().lower()
        file_field = str(config.get("file_field") or "file").strip() or "file"
        headers = (
            {str(k): str(v) for k, v in config.get("headers", {}).items()}
            if isinstance(config.get("headers"), dict)
            else {}
        )
        form_fields = (
            {str(k): str(v) for k, v in config.get("form_fields", {}).items()}
            if isinstance(config.get("form_fields"), dict)
            else {}
        )
        success_path = str(config.get("success_path") or "").strip()
        timeout_seconds = max(3, int(config.get("timeout_seconds", 20) or 20))

        path = Path(image_path)
        with path.open("rb") as fh:
            response = requests.request(
                method.upper(),
                endpoint,
                headers=headers,
                data=form_fields,
                files={file_field: (path.name, fh)},
                timeout=timeout_seconds,
            )
        response.raise_for_status()

        if not success_path:
            return None

        payload = response.json()
        url = cls._extract_by_path(payload, success_path)
        if not url:
            raise RuntimeError(
                f"Image host success_path 未命中有效 URL: {success_path}"
            )
        return url

    async def upload_image(self, image_path: str, config: dict[str, Any]) -> str | None:
        if not self.is_enabled(config):
            return None
        try:
            return await asyncio.to_thread(self._upload_sync, image_path, config)
        except Exception as exc:
            logger.warning(
                "[pixivdirect] Image host upload failed for %s: %s", image_path, exc
            )
            return None
