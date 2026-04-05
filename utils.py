from __future__ import annotations

import shlex
from typing import Any

from .constants import HELP_LINES
from .infrastructure.pixiv_client import pick_illust_image_urls


def parse_command_tokens(args_str: str) -> list[str]:
    try:
        return shlex.split(args_str)
    except ValueError:
        return args_str.split()


def parse_key_value_tokens(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    plain: list[str] = []
    kv: dict[str, str] = {}
    for token in tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            kv[key.strip().lower()] = value.strip()
        else:
            plain.append(token)
    return plain, kv


def user_key(event: Any) -> str:
    platform = event.get_platform_name()
    sender = event.get_sender_id()
    return f"{platform}:{sender}"


def help_text() -> str:
    return "\n".join(["PixEz 插件命令：", *HELP_LINES])


def format_illust_detail(data: dict[str, Any], *, quality: str) -> str:
    illust = data.get("illust") if isinstance(data, dict) else {}
    if not isinstance(illust, dict):
        return "未获取到作品详情。"
    user = illust.get("user") if isinstance(illust.get("user"), dict) else {}
    tags = [
        f"#{tag.get('name')}"
        for tag in illust.get("tags", [])
        if isinstance(tag, dict) and isinstance(tag.get("name"), str)
    ]
    image_count = len(pick_illust_image_urls(illust, quality))
    return "\n".join(
        [
            f"作品：{illust.get('title', '未知标题')}",
            f"ID：{illust.get('id', '-')}",
            f"作者：{user.get('name', '未知作者')} ({user.get('id', '-')})",
            f"类型：{illust.get('type', '-')}",
            f"页数：{illust.get('page_count', image_count or 1)}",
            f"浏览/收藏：{illust.get('total_view', 0)} / {illust.get('total_bookmarks', 0)}",
            f"创建时间：{illust.get('create_date', '-')}",
            f"标签：{' '.join(tags) if tags else '无'}",
        ]
    )


def format_user_detail(data: dict[str, Any]) -> str:
    user = data.get("user") if isinstance(data, dict) else {}
    profile = data.get("profile") if isinstance(data, dict) else {}
    if not isinstance(user, dict):
        return "未获取到作者详情。"
    return "\n".join(
        [
            f"作者：{user.get('name', '未知作者')}",
            f"ID：{user.get('id', '-')}",
            f"账号：{user.get('account', '-')}",
            f"插画/漫画/小说：{profile.get('total_illusts', 0)} / {profile.get('total_manga', 0)} / {profile.get('total_novels', 0)}",
            f"关注者：{profile.get('total_follow_users', 0)}",
            f"主页：{profile.get('webpage') or '无'}",
        ]
    )


def format_search_illusts(data: dict[str, Any], *, limit: int = 5) -> str:
    illusts = data.get("illusts") if isinstance(data, dict) else []
    if not isinstance(illusts, list) or not illusts:
        return "没有找到作品结果。"
    lines = ["作品搜索结果："]
    for illust in illusts[:limit]:
        if not isinstance(illust, dict):
            continue
        user = illust.get("user") if isinstance(illust.get("user"), dict) else {}
        lines.append(
            f"{illust.get('id', '-')} | {illust.get('title', '未知标题')} | {user.get('name', '未知作者')}"
        )
    return "\n".join(lines)


def format_search_users(data: dict[str, Any], *, limit: int = 5) -> str:
    previews = data.get("user_previews") if isinstance(data, dict) else []
    if not isinstance(previews, list) or not previews:
        return "没有找到用户结果。"
    lines = ["用户搜索结果："]
    for preview in previews[:limit]:
        if not isinstance(preview, dict):
            continue
        user = preview.get("user") if isinstance(preview.get("user"), dict) else {}
        profile = user.get("profile") if isinstance(user.get("profile"), dict) else {}
        lines.append(
            f"{user.get('id', '-')} | {user.get('name', '未知作者')} | 插画 {profile.get('total_illusts', 0)}"
        )
    return "\n".join(lines)


def format_random_caption(illust: dict[str, Any]) -> str:
    user = illust.get("user") if isinstance(illust.get("user"), dict) else {}
    tags = [
        f"#{tag.get('name')}"
        for tag in illust.get("tags", [])
        if isinstance(tag, dict) and isinstance(tag.get("name"), str)
    ]
    return "\n".join(
        [
            f"随机收藏：{illust.get('title', '未知标题')}",
            f"ID：{illust.get('id', '-')}",
            f"作者：{user.get('name', '未知作者')} ({user.get('id', '-')})",
            f"标签：{' '.join(tags) if tags else '无'}",
        ]
    )


def _format_illust_lines(
    title: str,
    illusts: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> str:
    if not illusts:
        return f"{title}\n无结果。"
    lines = [title]
    for illust in illusts[:limit]:
        user = illust.get("user") if isinstance(illust.get("user"), dict) else {}
        lines.append(
            f"{illust.get('id', '-')} | {illust.get('title', '未知标题')} | {user.get('name', '未知作者')}"
        )
    return "\n".join(lines)


def format_ranking_illusts(data: dict[str, Any]) -> str:
    illusts = data.get("illusts") if isinstance(data.get("illusts"), list) else []
    mode = data.get("mode") if isinstance(data.get("mode"), str) else "day"
    return _format_illust_lines(f"排行榜（{mode}）", illusts)


def format_recommended_illusts(data: dict[str, Any], *, recommend_type: str) -> str:
    if recommend_type == "user":
        previews = (
            data.get("user_previews")
            if isinstance(data.get("user_previews"), list)
            else []
        )
        if not previews:
            return "推荐用户作品\n无结果。"
        lines = ["推荐用户作品"]
        for preview in previews[:5]:
            if not isinstance(preview, dict):
                continue
            user = preview.get("user") if isinstance(preview.get("user"), dict) else {}
            lines.append(
                f"{user.get('id', '-')} | {user.get('name', '未知作者')} | {user.get('account', '')}"
            )
        return "\n".join(lines)

    illusts = data.get("illusts") if isinstance(data.get("illusts"), list) else []
    type_label = {
        "illust": "推荐插画",
        "manga": "推荐漫画",
    }.get(recommend_type, "推荐结果")
    return _format_illust_lines(type_label, illusts)


def format_related_illusts(data: dict[str, Any]) -> str:
    illusts = data.get("illusts") if isinstance(data.get("illusts"), list) else []
    return _format_illust_lines("相关推荐", illusts)


def format_ugoira_metadata(data: dict[str, Any]) -> str:
    metadata = (
        data.get("ugoira_metadata")
        if isinstance(data.get("ugoira_metadata"), dict)
        else {}
    )
    frames = metadata.get("frames") if isinstance(metadata.get("frames"), list) else []
    zip_urls = (
        metadata.get("zip_urls") if isinstance(metadata.get("zip_urls"), dict) else {}
    )
    zip_url = ""
    for key in ("original", "medium"):
        candidate = zip_urls.get(key)
        if isinstance(candidate, str) and candidate:
            zip_url = candidate
            break
    total_delay = sum(
        int(frame.get("delay", 0))
        for frame in frames
        if isinstance(frame, dict) and isinstance(frame.get("delay"), int)
    )
    return "\n".join(
        [
            "Ugoira 元数据：",
            f"帧数：{len(frames)}",
            f"总时长(ms)：{total_delay}",
            f"ZIP：{zip_url or '无'}",
        ]
    )
