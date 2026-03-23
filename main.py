from __future__ import annotations

import asyncio
import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.utils.astrbot_path import (
    get_astrbot_plugin_data_path,
    get_astrbot_temp_path,
)

from .pixivSDK import pixiv


@register("pixivdirect", "Sagiri777", "PixivDirect command plugin", "0.1.0")
class PixivDirectPlugin(Star):
    # Emoji ID mapping for different stages (参考emojiReply)
    EMOJI_MAP = {
        # Type 1 表情
        "得意": 4,
        "流泪": 5,
        "睡": 8,
        "大哭": 9,
        "尴尬": 10,
        "调皮": 12,
        "微笑": 14,
        "酷": 16,
        "可爱": 21,
        "傲慢": 23,
        "饥饿": 24,
        "困": 25,
        "惊恐": 26,
        "流汗": 27,
        "憨笑": 28,
        "悠闲": 29,
        "奋斗": 30,
        "疑问": 32,
        "嘘": 33,
        "晕": 34,
        "敲打": 38,
        "再见": 39,
        "发抖": 41,
        "爱情": 42,
        "跳跳": 43,
        "拥抱": 49,
        "蛋糕": 53,
        "咖啡": 60,
        "玫瑰": 63,
        "爱心": 66,
        "太阳": 74,
        "月亮": 75,
        "赞": 76,
        "握手": 78,
        "胜利": 79,
        "飞吻": 85,
        "西瓜": 89,
        "冷汗": 96,
        "擦汗": 97,
        "抠鼻": 98,
        "鼓掌": 99,
        "糗大了": 100,
        "坏笑": 101,
        "左哼哼": 102,
        "右哼哼": 103,
        "哈欠": 104,
        "委屈": 106,
        "左亲亲": 109,
        "可怜": 111,
        "示爱": 116,
        "抱拳": 118,
        "拳头": 120,
        "爱你": 122,
        "NO": 123,
        "OK": 124,
        "转圈": 125,
        "挥手": 129,
        "喝彩": 144,
        "棒棒糖": 147,
        "茶": 171,
        "泪奔": 173,
        "无奈": 174,
        "卖萌": 175,
        "小纠结": 176,
        "doge": 179,
        "惊喜": 180,
        "骚扰": 181,
        "笑哭": 182,
        "我最美": 183,
        "点赞": 201,
        "托脸": 203,
        "托腮": 212,
        "啵啵": 214,
        "蹭一蹭": 219,
        "抱抱": 222,
        "拍手": 227,
        "佛系": 232,
        "喷脸": 240,
        "甩头": 243,
        "加油抱抱": 246,
        "脑阔疼": 262,
        "捂脸": 264,
        "辣眼睛": 265,
        "哦哟": 266,
        "头秃": 267,
        "问号脸": 268,
        "暗中观察": 269,
        "emm": 270,
        "吃瓜": 271,
        "呵呵哒": 272,
        "我酸了": 273,
        "汪汪": 277,
        "汗": 278,
        "无眼笑": 281,
        "敬礼": 282,
        "面无表情": 284,
        "摸鱼": 285,
        "哦": 287,
        "睁眼": 289,
        "敲开心": 290,
        "摸锦鲤": 293,
        "期待": 294,
        "拜谢": 297,
        "元宝": 298,
        "牛啊": 299,
        "右亲亲": 305,
        "牛气冲天": 306,
        "喵喵": 307,
        "仔细分析": 314,
        "加油": 315,
        "崇拜": 318,
        "比心": 319,
        "庆祝": 320,
        "拒绝": 322,
        "吃糖": 324,
        "生气": 326,
        # Type 2 表情 (部分常用)
        "晴天": 9728,
        "闪光": 10024,
        "错误": 10060,
        "问号": 10068,
        "苹果": 127822,
        "草莓": 127827,
        "拉面": 127836,
        "面包": 127838,
        "刨冰": 127847,
        "啤酒": 127866,
        "干杯": 127867,
        "虫": 128027,
        "牛": 128046,
        "鲸鱼": 128051,
        "猴": 128053,
        "好的": 128076,
        "厉害": 128077,
        "内衣": 128089,
        "男孩": 128102,
        "爸爸": 128104,
        "礼物": 128157,
        "睡觉": 128164,
        "水": 128166,
        "吹气": 128168,
        "肌肉": 128170,
        "邮箱": 128235,
        "火": 128293,
        "呲牙": 128513,
        "激动": 128514,
        "高兴": 128516,
        "嘿嘿": 128522,
        "羞涩": 128524,
        "哼哼": 128527,
        "不屑": 128530,
        "失落": 128532,
        "淘气": 128540,
        "吐舌": 128541,
        "紧张": 128560,
        "瞪眼": 128563,
    }

    # Stage-specific emoji names
    STAGE_EMOJIS = {
        "login": ["赞", "OK"],  # 登录阶段
        "query_illust": ["期待", "比心"],  # 查询作品阶段
        "query_artist": ["崇拜", "爱心"],  # 查询作者阶段
        "random": ["惊喜", "庆祝"],  # 随机收藏阶段
        "error": ["尴尬", "流汗"],  # 错误阶段
        "rate_limit": ["困", "哈欠"],  # 限频阶段
        "help": ["吃瓜", "暗中观察"],  # 帮助阶段
    }
    _DNS_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60
    _DNS_REFRESH_RETRY_SECONDS = 60
    _RANDOM_DOWNLOAD_CONCURRENCY = 3
    _MIN_COMMAND_INTERVAL_SECONDS = 2.0
    _MAX_RANDOM_PAGES = 8
    _MAX_RANDOM_WARMUP = 3
    _IDLE_CACHE_INTERVAL_SECONDS = 300  # 5 minutes between idle cache runs
    _IDLE_CACHE_COUNT = 2  # Number of items to cache per user during idle
    _DEFAULT_CACHE_SIZE = 10  # Default minimum cache size to maintain

    def __init__(self, context: Context):
        super().__init__(context)
        self._storage_lock = asyncio.Lock()
        self._dns_refresh_lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()
        self._rate_limit_lock = asyncio.Lock()
        self._token_map: dict[str, str] = {}
        self._random_cache: dict[str, dict[str, list[dict[str, str]]]] = {}
        self._last_command_ts: dict[str, float] = {}
        self._dns_next_refresh_at: float = 0.0
        self._share_enabled: bool = False  # Share disabled by default
        self._idle_cache_task: asyncio.Task | None = None
        self._last_idle_cache_ts: float = 0.0

        self._plugin_data_dir = Path(get_astrbot_plugin_data_path()) / "pixivdirect"
        self._cache_dir = Path(get_astrbot_temp_path()) / "pixivdirect"
        self._cache_index_file = self._cache_dir / "cache_index.json"
        self._token_file = self._plugin_data_dir / "user_refresh_tokens.json"
        self._host_map_file = self._plugin_data_dir / "pixiv_host_map.json"
        self._share_config_file = self._plugin_data_dir / "share_config.json"

    async def initialize(self):
        self._plugin_data_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._load_tokens()
        self._load_cache_index()
        self._load_share_config()
        # Start idle cache task
        self._idle_cache_task = asyncio.create_task(self._idle_cache_loop())

    def _load_tokens(self) -> None:
        if not self._token_file.exists():
            self._token_map = {}
            return
        try:
            raw = json.loads(self._token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load token file, using empty mapping."
            )
            self._token_map = {}
            return

        users = raw.get("users") if isinstance(raw, dict) else None
        if not isinstance(users, dict):
            self._token_map = {}
            return

        loaded: dict[str, str] = {}
        for key, token in users.items():
            if isinstance(key, str) and isinstance(token, str) and key and token:
                loaded[key] = token
        self._token_map = loaded

    def _load_cache_index(self) -> None:
        if not self._cache_index_file.exists():
            self._random_cache = {}
            return
        try:
            raw = json.loads(self._cache_index_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load cache index, using empty cache."
            )
            self._random_cache = {}
            return

        if not isinstance(raw, dict):
            self._random_cache = {}
            return

        loaded_cache: dict[str, dict[str, list[dict[str, str]]]] = {}
        for user_key, user_cache in raw.items():
            if not isinstance(user_key, str) or not isinstance(user_cache, dict):
                continue
            loaded_user_cache: dict[str, list[dict[str, str]]] = {}
            for cache_key, items in user_cache.items():
                if not isinstance(cache_key, str) or not isinstance(items, list):
                    continue
                valid_items: list[dict[str, str]] = []
                for item in items:
                    if isinstance(item, dict):
                        path = item.get("path")
                        caption = item.get("caption")
                        if isinstance(path, str) and path and Path(path).exists():
                            if isinstance(caption, str):
                                valid_items.append({"path": path, "caption": caption})
                            else:
                                valid_items.append({"path": path, "caption": ""})
                if valid_items:
                    loaded_user_cache[cache_key] = valid_items
            if loaded_user_cache:
                loaded_cache[user_key] = loaded_user_cache
        self._random_cache = loaded_cache

    def _load_share_config(self) -> None:
        if not self._share_config_file.exists():
            self._share_enabled = False
            return
        try:
            raw = json.loads(self._share_config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "[pixivdirect] Failed to load share config, using default (disabled)."
            )
            self._share_enabled = False
            return

        if isinstance(raw, dict):
            self._share_enabled = bool(raw.get("share_enabled", False))
        else:
            self._share_enabled = False

    async def _save_share_config(self) -> None:
        async with self._cache_lock:
            try:
                self._share_config_file.write_text(
                    json.dumps(
                        {"share_enabled": self._share_enabled},
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[pixivdirect] Failed to save share config: %s", exc)

    async def _idle_cache_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._IDLE_CACHE_INTERVAL_SECONDS)
                await self._perform_idle_cache()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("[pixivdirect] Idle cache loop error: %s", exc)
                await asyncio.sleep(60)  # Wait before retrying

    async def _perform_idle_cache(self) -> None:
        if not self._token_map:
            return

        now = time.time()
        if now - self._last_idle_cache_ts < self._IDLE_CACHE_INTERVAL_SECONDS:
            return

        self._last_idle_cache_ts = now
        logger.info(
            "[pixivdirect] Starting idle cache for %d users", len(self._token_map)
        )

        for user_key, refresh_token in list(self._token_map.items()):
            try:
                await self._idle_cache_user(user_key, refresh_token)
            except Exception as exc:
                logger.warning(
                    "[pixivdirect] Idle cache failed for user %s: %s", user_key, exc
                )

    async def _idle_cache_user(self, user_key: str, refresh_token: str) -> None:
        user_cache = self._random_cache.get(user_key, {})
        default_cache_key = self._cache_key({"restrict": "public", "max_pages": 3})
        current_queue = user_cache.get(default_cache_key, [])

        if len(current_queue) >= self._DEFAULT_CACHE_SIZE:
            return

        items_to_add = self._DEFAULT_CACHE_SIZE - len(current_queue)
        items_to_add = min(items_to_add, self._IDLE_CACHE_COUNT)

        filter_params = {"restrict": "public", "max_pages": 3}
        latest_refresh_token, error = await self._enqueue_random_items(
            user_key=user_key,
            cache_key=default_cache_key,
            refresh_token=refresh_token,
            filter_params=filter_params,
            count=items_to_add,
        )

        if error:
            logger.warning(
                "[pixivdirect] Idle cache error for user %s: %s", user_key, error
            )
        else:
            logger.info(
                "[pixivdirect] Cached %d items for user %s", items_to_add, user_key
            )

    async def _save_cache_index(self) -> None:
        async with self._cache_lock:
            try:
                self._cache_index_file.write_text(
                    json.dumps(self._random_cache, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                logger.warning("[pixivdirect] Failed to save cache index: %s", exc)

    async def _save_tokens(self) -> None:
        async with self._storage_lock:
            payload = {"users": self._token_map}
            tmp_file = self._token_file.with_suffix(".tmp")
            tmp_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp_file.replace(self._token_file)

    @staticmethod
    def _user_key(event: AstrMessageEvent) -> str:
        return f"{event.get_platform_id()}:{event.get_sender_id()}"

    @staticmethod
    def _split_command(message: str) -> list[str]:
        tokens = re.split(r"\s+", (message or "").strip())
        tokens = [token for token in tokens if token]
        if tokens and tokens[0].lower() == "pixiv":
            return tokens[1:]
        return tokens

    @staticmethod
    def _format_pixiv_error(result: dict[str, Any]) -> str:
        status = result.get("status")
        error = result.get("error")
        if isinstance(error, dict):
            for key in ("message", "user_message"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return f"Pixiv API 错误（状态码={status}）：{value}"
            return f"Pixiv API 错误（状态码={status}）：{json.dumps(error, ensure_ascii=False)}"
        if error:
            return f"Pixiv API 错误（状态码={status}）：{error}"
        return f"Pixiv API 请求失败（状态码={status}）。"

    @staticmethod
    def _format_number(num: int | None) -> str:
        if num is None:
            return "未知"
        if num >= 10000:
            return f"{num / 10000:.1f}万"
        return str(num)

    def _format_illust_detail(
        self, illust: dict[str, Any], user: dict[str, Any], tags: list[str]
    ) -> str:
        title = str(illust.get("title") or "（无标题）")
        illust_id = illust.get("id")
        page_count = illust.get("page_count", 1)
        total_view = illust.get("total_view")
        total_bookmarks = illust.get("total_bookmarks")
        create_date = illust.get("create_date", "")
        illust_type = illust.get("type", "")

        # 格式化创建日期
        if create_date:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(create_date.replace("Z", "+00:00"))
                create_date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                create_date_str = (
                    create_date[:16] if len(create_date) > 16 else create_date
                )
        else:
            create_date_str = "未知"

        # 构建标签显示
        tags_text = ""
        if tags:
            tags_text = " ".join([f"#{tag}" for tag in tags[:8]])
            if len(tags) > 8:
                tags_text += f" 等{len(tags)}个标签"

        # 构建输出
        lines = [
            f"✨ {title}",
            f"🎨 作者: {user.get('name', '未知')} (ID: {user.get('id', '未知')})",
            f"🆔 作品ID: {illust_id}",
            f"📄 页数: {page_count}",
            f"👁️ 浏览: {self._format_number(total_view)} | ❤️ 收藏: {self._format_number(total_bookmarks)}",
            f"📅 发布: {create_date_str}",
        ]

        # 添加作品类型信息
        type_text = ""
        if illust_type == "ugoira":
            type_text = "🎬 类型: 动图"
        elif illust_type == "illust":
            type_text = "🖼️ 类型: 插画"
        elif illust_type == "manga":
            type_text = "📚 类型: 漫画"
        if type_text:
            lines.append(type_text)

        if tags_text:
            lines.append(f"🏷️ {tags_text}")

        return "\n".join(lines)

    def _format_author_detail(
        self, user: dict[str, Any], profile: dict[str, Any]
    ) -> str:
        user_id = user.get("id")
        name = user.get("name", "未知")
        account = user.get("account", "")
        total_illusts = profile.get("total_illusts", 0)
        total_manga = profile.get("total_manga", 0)
        total_follow = profile.get("total_follow_users", 0)
        webpage = profile.get("webpage")

        lines = [
            f"👤 {name}",
            f"🆔 作者ID: {user_id}",
        ]

        if account:
            lines.append(f"📱 账号: @{account}")

        lines.extend(
            [
                f"🎨 插画: {total_illusts} | 📚 漫画: {total_manga}",
                f"👥 关注者: {self._format_number(total_follow)}",
            ]
        )

        if webpage:
            lines.append(f"🔗 主页: {webpage}")

        return "\n".join(lines)

    def _format_random_bookmark(
        self,
        item: dict[str, Any],
        matched_count: int | None = None,
        pages_scanned: int | None = None,
    ) -> str:
        illust_id = item.get("illust_id")
        title = str(item.get("title") or "（无标题）")
        author_name = str(item.get("author_name") or "未知作者")
        author_id = item.get("author_id")
        tags = item.get("tags", [])
        page_count = item.get("page_count", 1)
        total_view = item.get("total_view")
        total_bookmarks = item.get("total_bookmarks")

        # 构建标签显示
        tags_text = ""
        if tags:
            tags_text = " ".join([f"#{tag}" for tag in tags[:6]])
            if len(tags) > 6:
                tags_text += f" 等{len(tags)}个"

        lines = [
            f"✨ {title}",
            f"🎨 作者: {author_name} (ID: {author_id})",
            f"🆔 作品ID: {illust_id}",
            f"📄 页数: {page_count}",
            f"👁️ 浏览: {self._format_number(total_view)} | ❤️ 收藏: {self._format_number(total_bookmarks)}",
        ]

        if tags_text:
            lines.append(f"🏷️ {tags_text}")

        # 显示匹配信息（如果有）
        if matched_count is not None:
            lines.append(f"🎯 匹配: {matched_count}个作品")
        if pages_scanned is not None:
            lines.append(f"📄 扫描: {pages_scanned}页")

        return "\n".join(lines)

    @staticmethod
    def _tos_notice() -> str:
        return "使用说明（TOS 合规）：仅可用于账号本人授权访问与个人查看，请勿批量抓取、商用转载或绕过 Pixiv 规则。"

    async def _rate_limit_message(self, event: AstrMessageEvent) -> str | None:
        user_key = self._user_key(event)
        now = time.time()
        async with self._rate_limit_lock:
            last = self._last_command_ts.get(user_key)
            self._last_command_ts[user_key] = now
        if last is None:
            return None
        wait_seconds = self._MIN_COMMAND_INTERVAL_SECONDS - (now - last)
        if wait_seconds > 0:
            return f"请求过于频繁，请在 {wait_seconds:.1f} 秒后重试。"
        return None

    async def _consume_dns_refresh_flag(self) -> bool:
        now = time.time()
        if now < self._dns_next_refresh_at:
            return False

        async with self._dns_refresh_lock:
            now = time.time()
            if now < self._dns_next_refresh_at:
                return False

            if not self._host_map_file.exists():
                self._dns_next_refresh_at = now + self._DNS_REFRESH_RETRY_SECONDS
                return True

            try:
                age = now - self._host_map_file.stat().st_mtime
            except OSError:
                self._dns_next_refresh_at = now + self._DNS_REFRESH_RETRY_SECONDS
                return True

            if age >= self._DNS_REFRESH_INTERVAL_SECONDS:
                self._dns_next_refresh_at = now + self._DNS_REFRESH_RETRY_SECONDS
                return True

            self._dns_next_refresh_at = now + (
                self._DNS_REFRESH_INTERVAL_SECONDS - max(0.0, age)
            )
            return False

    async def _mark_dns_refreshed(self) -> None:
        async with self._dns_refresh_lock:
            self._dns_next_refresh_at = time.time() + self._DNS_REFRESH_INTERVAL_SECONDS

    async def _add_emoji_reaction(self, event: AstrMessageEvent, stage: str) -> None:
        """为当前消息添加阶段相关的表情回应"""
        try:
            # 只在aiocqhttp平台支持表情回应
            if event.get_platform_name() != "aiocqhttp":
                return

            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                AiocqhttpMessageEvent,
            )

            if not isinstance(event, AiocqhttpMessageEvent):
                return

            # 获取当前阶段的表情列表
            emoji_names = self.STAGE_EMOJIS.get(stage, [])
            if not emoji_names:
                return

            # 获取表情ID列表
            emoji_ids = []
            for emoji_name in emoji_names:
                emoji_id = self.EMOJI_MAP.get(emoji_name)
                if emoji_id is not None:
                    emoji_ids.append(str(emoji_id))

            if not emoji_ids:
                return

            # 获取消息ID和客户端
            client = event.bot
            message_id = event.message_obj.message_id

            # 顺序发送表情回应
            for emoji_id in emoji_ids:
                try:
                    await client.api.call_action(
                        "set_msg_emoji_like",
                        message_id=message_id,
                        emoji_id=emoji_id,
                    )
                    await asyncio.sleep(0.3)  # 添加延迟避免请求过快
                except Exception as e:
                    logger.warning(
                        "[pixivdirect] Failed to add emoji reaction %s: %s",
                        emoji_id,
                        e,
                    )

        except Exception as e:
            logger.warning("[pixivdirect] Error adding emoji reaction: %s", e)

    async def _pixiv_call(
        self, action: str, params: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        dns_update_hosts = await self._consume_dns_refresh_flag()
        result = await asyncio.to_thread(
            pixiv,
            action,
            params,
            dns_cache_file=str(self._host_map_file),
            dns_update_hosts=dns_update_hosts,
            runtime_dns_resolve=False,
            max_retries=2,
            **kwargs,
        )
        if dns_update_hosts:
            await self._mark_dns_refreshed()
        return result

    @staticmethod
    def _safe_filename_from_url(url: str, fallback: str) -> str:
        raw = Path(urlsplit(url).path).name
        name = raw if raw else fallback
        return re.sub(r"[^a-zA-Z0-9._-]+", "_", name) or fallback

    async def _download_image_to_cache(
        self,
        image_url: str,
        *,
        access_token: str | None,
        refresh_token: str,
        name_prefix: str,
    ) -> str:
        image_result = await self._pixiv_call(
            "image",
            {"url": image_url},
            access_token=access_token,
            refresh_token=refresh_token,
        )
        if not image_result.get("ok"):
            raise RuntimeError(self._format_pixiv_error(image_result))

        content = image_result.get("content")
        if not isinstance(content, (bytes, bytearray)):
            raise RuntimeError("Pixiv 图片响应未返回二进制内容。")

        safe_name = self._safe_filename_from_url(image_url, f"{name_prefix}.bin")
        target = (
            self._cache_dir / f"{name_prefix}_{int(time.time() * 1000)}_{safe_name}"
        )
        target.write_bytes(bytes(content))
        return str(target)

    async def _download_ugoira_zip_to_cache(
        self,
        zip_url: str,
        *,
        access_token: str | None,
        refresh_token: str,
        name_prefix: str,
    ) -> str:
        zip_result = await self._pixiv_call(
            "ugoira_zip",
            {"url": zip_url},
            access_token=access_token,
            refresh_token=refresh_token,
        )
        if not zip_result.get("ok"):
            raise RuntimeError(self._format_pixiv_error(zip_result))

        content = zip_result.get("content")
        if not isinstance(content, (bytes, bytearray)):
            raise RuntimeError("Pixiv 动图 zip 响应未返回二进制内容。")

        safe_name = self._safe_filename_from_url(zip_url, f"{name_prefix}.zip")
        target = (
            self._cache_dir / f"{name_prefix}_{int(time.time() * 1000)}_{safe_name}"
        )
        target.write_bytes(bytes(content))
        return str(target)

    def _render_ugoira_to_gif(
        self,
        zip_path: str,
        frames: list[dict[str, Any]],
        output_path: str,
    ) -> None:
        """将动图 zip 文件渲染为 GIF。"""
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            # 构建帧文件名到延迟的映射
            frame_delays = {}
            for frame in frames:
                file_name = frame.get("file", "")
                delay = frame.get("delay", 100)
                if file_name:
                    frame_delays[file_name] = delay

            # 获取 zip 中的所有图像文件并排序
            image_files = sorted(
                [
                    f
                    for f in zip_file.namelist()
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))
                ]
            )

            if not image_files:
                raise RuntimeError("动图 zip 文件中没有找到图像文件。")

            # 读取所有帧
            pil_frames = []
            delays = []
            for image_file in image_files:
                with zip_file.open(image_file) as f:
                    img = Image.open(io.BytesIO(f.read()))
                    # 转换为 RGB 模式（如果需要）
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    pil_frames.append(img)
                    # 获取延迟时间（毫秒）
                    delay = frame_delays.get(image_file, 100)
                    delays.append(delay)

            if not pil_frames:
                raise RuntimeError("无法读取动图帧。")

            # 保存为 GIF
            pil_frames[0].save(
                output_path,
                save_all=True,
                append_images=pil_frames[1:],
                duration=delays,
                loop=0,
                optimize=True,
            )

    @staticmethod
    def _parse_random_filter(filter_tokens: list[str]) -> tuple[dict[str, Any], str]:
        params: dict[str, Any] = {}
        loose_text: list[str] = []

        aliases = {
            "tag": "tag",
            "t": "tag",
            "author": "author",
            "a": "author",
            "author_id": "author_id",
            "aid": "author_id",
            "restrict": "restrict",
            "r": "restrict",
            "max_pages": "max_pages",
            "pages": "max_pages",
            "warmup": "warmup",
        }

        for token in filter_tokens:
            if "=" not in token:
                loose_text.append(token)
                continue
            key_raw, value_raw = token.split("=", 1)
            key = aliases.get(key_raw.strip().lower())
            value = value_raw.strip()
            if not key or not value:
                continue
            params[key] = value

        if loose_text and "tag" not in params:
            params["tag"] = " ".join(loose_text)

        if "author_id" in params:
            try:
                params["author_id"] = int(str(params["author_id"]))
            except ValueError:
                params.pop("author_id", None)

        if "max_pages" in params:
            try:
                params["max_pages"] = max(
                    1,
                    min(
                        PixivDirectPlugin._MAX_RANDOM_PAGES,
                        int(str(params["max_pages"])),
                    ),
                )
            except ValueError:
                params.pop("max_pages", None)

        if "restrict" in params:
            restrict = str(params["restrict"]).lower()
            params["restrict"] = "private" if restrict == "private" else "public"

        summary_items: list[str] = []
        for key in ("tag", "author", "author_id", "restrict", "max_pages"):
            if key in params:
                summary_items.append(f"{key}={params[key]}")
        summary = ", ".join(summary_items) if summary_items else "无"
        return params, summary

    def _find_user_by_name(self, target_name: str) -> str | None:
        """Find user key by their display name or account."""
        if not target_name:
            return None

        target_lower = target_name.lower()

        # Search through all cached user keys
        for user_key in self._token_map.keys():
            # user_key format is "platform:sender_id"
            # We need to extract the sender_id part
            parts = user_key.split(":", 1)
            if len(parts) != 2:
                continue

            platform, sender_id = parts

            # Try to find user by searching in cache captions
            user_cache = self._random_cache.get(user_key, {})
            for cache_items in user_cache.values():
                for item in cache_items:
                    caption = item.get("caption", "")
                    # Look for author name in caption
                    if (
                        f"作者: {target_name}" in caption
                        or target_lower in caption.lower()
                    ):
                        return user_key

            # Also check if the sender_id matches
            if sender_id == target_name:
                return user_key

        return None

    def _cache_key(self, filter_params: dict[str, Any]) -> str:
        identity = {
            "tag": filter_params.get("tag"),
            "author": filter_params.get("author"),
            "author_id": filter_params.get("author_id"),
            "restrict": filter_params.get("restrict", "public"),
            "max_pages": filter_params.get("max_pages", 3),
        }
        return json.dumps(identity, ensure_ascii=False, sort_keys=True)

    async def _pop_cached_item(
        self, user_key: str, cache_key: str
    ) -> dict[str, str] | None:
        async with self._cache_lock:
            user_cache = self._random_cache.get(user_key)
            if not user_cache:
                return None
            queue = user_cache.get(cache_key)
            if not queue:
                return None

            while queue:
                item = queue.pop(0)
                path = item.get("path")
                if isinstance(path, str) and path and Path(path).exists():
                    return item
            return None

    async def _enqueue_random_items(
        self,
        *,
        user_key: str,
        cache_key: str,
        refresh_token: str,
        filter_params: dict[str, Any],
        count: int,
    ) -> tuple[str, str | None]:
        latest_refresh_token = refresh_token
        user_cache = self._random_cache.setdefault(user_key, {})
        queue = user_cache.setdefault(cache_key, [])
        pending_items: list[dict[str, Any]] = []

        for _ in range(max(1, count)):
            random_result = await self._pixiv_call(
                "random_bookmark_image",
                filter_params,
                refresh_token=latest_refresh_token,
            )
            if not random_result.get("ok"):
                return latest_refresh_token, self._format_pixiv_error(random_result)

            latest_refresh_token = str(
                random_result.get("refresh_token") or latest_refresh_token,
            )
            data = random_result.get("data")
            if not isinstance(data, dict):
                return latest_refresh_token, "Pixiv 随机收藏返回数据格式异常。"

            image_url = data.get("image_url")
            if not isinstance(image_url, str) or not image_url:
                return latest_refresh_token, "Pixiv 随机收藏未返回图片地址。"

            illust_id = data.get("id")
            title = str(data.get("title") or "（无标题）")
            author_data = (
                data.get("author") if isinstance(data.get("author"), dict) else {}
            )
            author_name = str(author_data.get("name") or "未知作者")
            author_id = author_data.get("id")

            # 获取illust详细信息
            illust_data = (
                data.get("illust") if isinstance(data.get("illust"), dict) else {}
            )

            pending_items.append(
                {
                    "illust_id": illust_id,
                    "title": title,
                    "author_name": author_name,
                    "author_id": author_id,
                    "filters": data.get("filters")
                    if isinstance(data.get("filters"), dict)
                    else {},
                    "tags": data.get("tags")
                    if isinstance(data.get("tags"), list)
                    else [],
                    "matched_count": data.get("matched_count"),
                    "pages_scanned": data.get("pages_scanned"),
                    "image_url": image_url,
                    "access_token": random_result.get("access_token"),
                    "refresh_token": latest_refresh_token,
                    "page_count": illust_data.get("page_count", 1),
                    "total_view": illust_data.get("total_view"),
                    "total_bookmarks": illust_data.get("total_bookmarks"),
                },
            )

        if not pending_items:
            return latest_refresh_token, "未找到符合筛选条件的收藏图片。"

        semaphore = asyncio.Semaphore(self._RANDOM_DOWNLOAD_CONCURRENCY)

        async def build_cache_item(item: dict[str, Any]) -> dict[str, str]:
            async with semaphore:
                local_path = await self._download_image_to_cache(
                    str(item["image_url"]),
                    access_token=(
                        str(item["access_token"]) if item.get("access_token") else None
                    ),
                    refresh_token=str(item["refresh_token"]),
                    name_prefix=f"bookmark_{item['illust_id'] or 'unknown'}",
                )
            caption = self._format_random_bookmark(
                item,
                matched_count=item.get("matched_count"),
                pages_scanned=item.get("pages_scanned"),
            )
            return {"path": local_path, "caption": caption}

        built_items = await asyncio.gather(
            *(build_cache_item(item) for item in pending_items),
            return_exceptions=True,
        )
        async with self._cache_lock:
            for built_item in built_items:
                if isinstance(built_item, Exception):
                    logger.warning(
                        "[pixivdirect] Random cache download failed: %s", built_item
                    )
                    continue
                queue.append(built_item)

        if not queue:
            return latest_refresh_token, "随机结果图片缓存失败，请稍后重试。"

        await self._save_cache_index()
        return latest_refresh_token, None

    def _get_user_token(self, event: AstrMessageEvent) -> str | None:
        return self._token_map.get(self._user_key(event))

    async def _set_user_token(
        self, event: AstrMessageEvent, refresh_token: str
    ) -> None:
        self._token_map[self._user_key(event)] = refresh_token
        await self._save_tokens()

    @staticmethod
    def _help_text() -> str:
        return (
            "Pixiv 指令：\n"
            "- /pixiv login {refresh_token}\n"
            "- /pixiv id i {illust_id}\n"
            "- /pixiv id a {artist_id}\n"
            "- /pixiv random [tag=xxx] [author=xxx] [author_id=123] [restrict=public|private] [max_pages=3]\n"
            "- /pixiv random @{用户名称} [筛选条件]  # 查看其他用户的收藏（需先开启分享）\n"
            "- /pixiv random share true/false  # 开启/关闭收藏分享功能"
        )

    async def _handle_login(self, event: AstrMessageEvent, args: list[str]):
        if len(args) < 2:
            await self._add_emoji_reaction(event, "error")
            yield event.plain_result("用法：/pixiv login {refresh_token}")
            return

        refresh_token = args[1].strip()
        if not refresh_token:
            await self._add_emoji_reaction(event, "error")
            yield event.plain_result("refresh_token 不能为空。")
            return

        await self._add_emoji_reaction(event, "login")
        verify_result = await self._pixiv_call(
            "random_bookmark_image",
            {"max_pages": 1},
            refresh_token=refresh_token,
        )
        if not verify_result.get("ok"):
            await self._add_emoji_reaction(event, "error")
            yield event.plain_result(
                "Token 校验失败：" + self._format_pixiv_error(verify_result),
            )
            return

        latest_refresh_token = str(verify_result.get("refresh_token") or refresh_token)
        await self._set_user_token(event, latest_refresh_token)
        yield event.plain_result("已绑定当前用户的 Pixiv Token。")

    async def _handle_id(self, event: AstrMessageEvent, args: list[str]):
        if len(args) < 3:
            await self._add_emoji_reaction(event, "error")
            yield event.plain_result(
                "用法：/pixiv id i {illust_id} 或 /pixiv id a {artist_id}"
            )
            return

        user_token = self._get_user_token(event)
        if not user_token:
            await self._add_emoji_reaction(event, "error")
            yield event.plain_result("请先登录：/pixiv login {refresh_token}")
            return

        typ = args[1].lower().strip()
        target_id = args[2].strip()
        if not target_id.isdigit():
            await self._add_emoji_reaction(event, "error")
            yield event.plain_result("ID 必须是数字。")
            return

        if typ == "i":
            await self._add_emoji_reaction(event, "query_illust")
            result = await self._pixiv_call(
                "illust_detail",
                {"illust_id": int(target_id)},
                refresh_token=user_token,
            )
            if not result.get("ok"):
                await self._add_emoji_reaction(event, "error")
                yield event.plain_result(self._format_pixiv_error(result))
                return

            latest_refresh_token = str(result.get("refresh_token") or user_token)
            if latest_refresh_token != user_token:
                await self._set_user_token(event, latest_refresh_token)

            data = result.get("data")
            illust = data.get("illust") if isinstance(data, dict) else None
            if not isinstance(illust, dict):
                yield event.plain_result("解析作品详情失败。")
                return

            user = illust.get("user") if isinstance(illust.get("user"), dict) else {}
            tags_raw = (
                illust.get("tags") if isinstance(illust.get("tags"), list) else []
            )
            tags: list[str] = []
            for item in tags_raw:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name:
                        tags.append(name)

            caption = self._format_illust_detail(illust, user, tags)

            # 检测是否为动图
            illust_type = illust.get("type", "")
            if illust_type == "ugoira":
                # 处理动图
                try:
                    # 获取动图元数据
                    ugoira_result = await self._pixiv_call(
                        "ugoira_metadata",
                        {"illust_id": int(target_id)},
                        refresh_token=latest_refresh_token,
                    )
                    if not ugoira_result.get("ok"):
                        yield event.plain_result(
                            self._format_pixiv_error(ugoira_result)
                        )
                        return

                    ugoira_data = ugoira_result.get("data")
                    if not isinstance(ugoira_data, dict):
                        yield event.plain_result("解析动图元数据失败。")
                        return

                    ugoira_metadata = ugoira_data.get("ugoira_metadata")
                    if not isinstance(ugoira_metadata, dict):
                        yield event.plain_result("动图元数据格式异常。")
                        return

                    # 获取 zip 文件 URL
                    zip_urls = ugoira_metadata.get("zip_urls")
                    if not isinstance(zip_urls, dict):
                        yield event.plain_result("动图 zip URL 不存在。")
                        return

                    # 优先使用 original，其次 medium
                    zip_url = zip_urls.get("original") or zip_urls.get("medium")
                    if not zip_url:
                        yield event.plain_result("动图 zip URL 为空。")
                        return

                    # 获取帧信息
                    frames = ugoira_metadata.get("frames")
                    if not isinstance(frames, list):
                        yield event.plain_result("动图帧信息不存在。")
                        return

                    # 下载 zip 文件
                    zip_path = await self._download_ugoira_zip_to_cache(
                        zip_url,
                        access_token=ugoira_result.get("access_token"),
                        refresh_token=str(
                            ugoira_result.get("refresh_token") or latest_refresh_token
                        ),
                        name_prefix=f"ugoira_{target_id}",
                    )

                    # 渲染为 GIF
                    gif_path = (
                        self._cache_dir
                        / f"ugoira_{target_id}_{int(time.time() * 1000)}.gif"
                    )
                    await asyncio.to_thread(
                        self._render_ugoira_to_gif,
                        zip_path,
                        frames,
                        str(gif_path),
                    )

                    yield event.make_result().message(caption).file_image(str(gif_path))
                    return

                except Exception as exc:  # noqa: BLE001
                    logger.warning("[pixivdirect] Ugoira processing failed: %s", exc)
                    yield event.plain_result(f"{caption}\n\n⚠️ 动图处理失败：{exc}")
                    return

            # 处理普通图片
            preview_url = None
            image_urls = illust.get("image_urls")
            if isinstance(image_urls, dict):
                for key in ("large", "medium", "square_medium"):
                    value = image_urls.get(key)
                    if isinstance(value, str) and value:
                        preview_url = value
                        break
            if not preview_url:
                meta_single_page = illust.get("meta_single_page")
                if isinstance(meta_single_page, dict):
                    value = meta_single_page.get("original_image_url")
                    if isinstance(value, str) and value:
                        preview_url = value

            if preview_url:
                try:
                    local_path = await self._download_image_to_cache(
                        preview_url,
                        access_token=result.get("access_token"),
                        refresh_token=latest_refresh_token,
                        name_prefix=f"illust_{illust.get('id') or target_id}",
                    )
                    yield event.make_result().message(caption).file_image(local_path)
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[pixivdirect] Preview download failed: %s", exc)

            yield event.plain_result(caption)
            return

        if typ == "a":
            await self._add_emoji_reaction(event, "query_artist")
            result = await self._pixiv_call(
                "user_detail",
                {"user_id": int(target_id)},
                refresh_token=user_token,
            )
            if not result.get("ok"):
                await self._add_emoji_reaction(event, "error")
                yield event.plain_result(self._format_pixiv_error(result))
                return

            latest_refresh_token = str(result.get("refresh_token") or user_token)
            if latest_refresh_token != user_token:
                await self._set_user_token(event, latest_refresh_token)

            data = result.get("data")
            user = data.get("user") if isinstance(data, dict) else None
            profile = data.get("profile") if isinstance(data, dict) else None
            if not isinstance(user, dict) or not isinstance(profile, dict):
                yield event.plain_result("解析作者详情失败。")
                return

            caption = self._format_author_detail(user, profile)
            yield event.plain_result(caption)
            return

        yield event.plain_result("未知类型，请使用 i（作品）或 a（作者）。")

    async def _handle_random(self, event: AstrMessageEvent, args: list[str]):
        user_token = self._get_user_token(event)
        if not user_token:
            await self._add_emoji_reaction(event, "error")
            yield event.plain_result("请先登录：/pixiv login {refresh_token}")
            return

        # Check for share configuration command
        if len(args) >= 2 and args[1].lower() == "share":
            if len(args) >= 3:
                value = args[2].lower()
                if value in ("true", "1", "yes", "on"):
                    self._share_enabled = True
                    await self._save_share_config()
                    yield event.plain_result("已开启收藏分享功能。")
                    return
                elif value in ("false", "0", "no", "off"):
                    self._share_enabled = False
                    await self._save_share_config()
                    yield event.plain_result("已关闭收藏分享功能。")
                    return
                else:
                    yield event.plain_result("无效的值，请使用 true 或 false。")
                    return
            else:
                status = "开启" if self._share_enabled else "关闭"
                yield event.plain_result(f"收藏分享功能当前状态：{status}")
                return

        # Check for @user parameter
        target_user_key = None
        target_user_name = None
        remaining_args = []

        for token in args[1:]:
            if token.startswith("@"):
                target_user_name = token[1:]
                target_user_key = self._find_user_by_name(target_user_name)
                if not target_user_key:
                    yield event.plain_result(f"未找到用户：{target_user_name}")
                    return
                if not self._share_enabled:
                    yield event.plain_result(
                        "收藏分享功能未开启，请使用 /pixiv random share true 开启。"
                    )
                    return
            else:
                remaining_args.append(token)

        filter_params, filter_summary = self._parse_random_filter(remaining_args)
        filter_params.setdefault("restrict", "public")
        filter_params.setdefault("max_pages", 3)

        cache_key = self._cache_key(filter_params)

        # Use target user's cache if specified, otherwise use current user's
        if target_user_key:
            user_key = target_user_key
            is_shared = True
        else:
            user_key = self._user_key(event)
            is_shared = False

        cached_item = await self._pop_cached_item(user_key, cache_key)
        if cached_item:
            await self._add_emoji_reaction(event, "random")
            caption = cached_item.get("caption") or "Pixiv 随机收藏（缓存）"
            path = cached_item.get("path")
            if path:
                source_info = "缓存（共享）" if is_shared else "缓存"
                yield (
                    event.make_result()
                    .message(f"{caption}\n- 来源: {source_info}")
                    .file_image(path)
                )
                return

        # If accessing shared cache and no cached item, don't fetch new items
        if is_shared:
            yield event.plain_result("该用户的缓存中没有找到符合条件的图片。")
            return

        warmup = 2
        raw_warmup = filter_params.pop("warmup", None)
        if raw_warmup is not None:
            try:
                warmup = max(1, min(self._MAX_RANDOM_WARMUP, int(str(raw_warmup))))
            except ValueError:
                warmup = 2

        await self._add_emoji_reaction(event, "random")
        latest_refresh_token, error = await self._enqueue_random_items(
            user_key=user_key,
            cache_key=cache_key,
            refresh_token=user_token,
            filter_params=filter_params,
            count=warmup,
        )
        if latest_refresh_token != user_token:
            await self._set_user_token(event, latest_refresh_token)

        if error:
            await self._add_emoji_reaction(event, "error")
            yield event.plain_result(f"获取随机收藏失败：{error}")
            return

        picked = await self._pop_cached_item(user_key, cache_key)
        if not picked:
            yield event.plain_result("未找到可发送的缓存图片。")
            return

        caption = picked.get("caption") or "Pixiv 随机收藏"
        path = picked.get("path")
        remain = len(self._random_cache.get(user_key, {}).get(cache_key, []))
        if path:
            yield (
                event.make_result()
                .message(
                    f"{caption}\n- 来源: 新获取\n- 剩余缓存: {remain}\n- 筛选条件: {filter_summary}",
                )
                .file_image(path)
            )
            return

        yield event.plain_result(caption)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=99)
    async def on_any_message(self, event: AstrMessageEvent):
        if event.get_sender_id() == event.get_self_id():
            return
        yield event.plain_result("吃瓜")

    @filter.command_group("pixiv")
    def pixiv_group(self):
        """Pixiv command group."""

    @pixiv_group.command("help")
    async def pixiv_help(self, event: AstrMessageEvent):
        """Show Pixiv command usages."""
        limited = await self._rate_limit_message(event)
        if limited:
            await self._add_emoji_reaction(event, "rate_limit")
            yield event.plain_result(limited)
            return
        await self._add_emoji_reaction(event, "help")
        yield event.plain_result(self._help_text())

    @pixiv_group.command("login")
    async def pixiv_login(self, event: AstrMessageEvent, refresh_token: str = ""):
        """Bind user's Pixiv refresh token."""
        limited = await self._rate_limit_message(event)
        if limited:
            await self._add_emoji_reaction(event, "rate_limit")
            yield event.plain_result(limited)
            return
        async for result in self._handle_login(event, ["login", refresh_token]):
            yield result

    @pixiv_group.command("id")
    async def pixiv_id(
        self, event: AstrMessageEvent, target_type: str = "", target_id: str = ""
    ):
        """Query Pixiv by illust id or artist id."""
        limited = await self._rate_limit_message(event)
        if limited:
            await self._add_emoji_reaction(event, "rate_limit")
            yield event.plain_result(limited)
            return
        async for result in self._handle_id(event, ["id", target_type, target_id]):
            yield result

    @pixiv_group.command("random")
    async def pixiv_random(self, event: AstrMessageEvent, filter_text: GreedyStr = ""):
        """Get a random bookmarked image with optional filters."""
        limited = await self._rate_limit_message(event)
        if limited:
            await self._add_emoji_reaction(event, "rate_limit")
            yield event.plain_result(limited)
            return
        filter_tokens = [
            token for token in re.split(r"\s+", str(filter_text).strip()) if token
        ]
        args = ["random", *filter_tokens]
        async for result in self._handle_random(event, args):
            yield result

    async def terminate(self):
        if self._idle_cache_task and not self._idle_cache_task.done():
            self._idle_cache_task.cancel()
            try:
                await self._idle_cache_task
            except asyncio.CancelledError:
                pass
        self._random_cache.clear()
