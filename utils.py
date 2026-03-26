from __future__ import annotations

import re
from typing import Any

from astrbot.api.event import AstrMessageEvent


def user_key(event: AstrMessageEvent) -> str:
    """Generate a unique user key from the event."""
    return f"{event.get_platform_id()}:{event.get_sender_id()}"


def split_command(message: str) -> list[str]:
    """Split a command message into tokens."""
    tokens = re.split(r"\s+", (message or "").strip())
    tokens = [token for token in tokens if token]
    if tokens and tokens[0].lower() == "pixiv":
        return tokens[1:]
    return tokens


def format_number(num: int | None) -> str:
    """Format a number with Chinese units for large numbers."""
    if num is None:
        return "未知"
    if num >= 10000:
        return f"{num / 10000:.1f}万"
    return str(num)


def format_illust_detail(
    illust: dict[str, Any], user: dict[str, Any], tags: list[str]
) -> str:
    """Format illustration details into a readable string."""
    title = str(illust.get("title") or "（无标题）")
    illust_id = illust.get("id")
    page_count = illust.get("page_count", 1)
    total_view = illust.get("total_view")
    total_bookmarks = illust.get("total_bookmarks")
    create_date = illust.get("create_date", "")
    illust_type = illust.get("type", "")

    # Format creation date
    if create_date:
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(create_date.replace("Z", "+00:00"))
            create_date_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            create_date_str = create_date[:16] if len(create_date) > 16 else create_date
    else:
        create_date_str = "未知"

    # Build tags display
    tags_text = ""
    if tags:
        tags_text = " ".join([f"#{tag}" for tag in tags[:8]])
        if len(tags) > 8:
            tags_text += f" 等{len(tags)}个标签"

    # Build output
    lines = [
        f"✨ {title}",
        f"🎨 作者: {user.get('name', '未知')} (ID: {user.get('id', '未知')})",
        f"🆔 作品ID: {illust_id}",
        f"📄 页数: {page_count}",
        f"👁️ 浏览: {format_number(total_view)} | ❤️ 收藏: {format_number(total_bookmarks)}",
        f"📅 发布: {create_date_str}",
    ]

    # Add type info
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


def format_author_detail(user: dict[str, Any], profile: dict[str, Any]) -> str:
    """Format author details into a readable string."""
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
            f"👥 关注者: {format_number(total_follow)}",
        ]
    )

    if webpage:
        lines.append(f"🔗 主页: {webpage}")

    return "\n".join(lines)


def format_search_result(
    illusts: list[dict[str, Any]],
    keyword: str,
    page: int,
    total_count: int | None = None,
) -> str:
    """Format search results into a readable string."""
    if not illusts:
        return f"🔍 搜索结果：关键词「{keyword}」没有找到相关作品。"

    total_str = f"共找到{format_number(total_count)}个作品" if total_count else ""
    lines = [
        f"🔍 搜索结果：关键词「{keyword}」（第{page}页{f'，{total_str}' if total_str else ''}）"
    ]

    for i, illust in enumerate(illusts, 1):
        title = str(illust.get("title") or "（无标题）")
        illust_id = illust.get("id")
        user = illust.get("user") if isinstance(illust.get("user"), dict) else {}
        user_name = user.get("name", "未知")
        user_id = user.get("id", "未知")
        total_bookmarks = illust.get("total_bookmarks")
        x_restrict = illust.get("x_restrict", 0)

        lines.append(f"\n{i}. 🌅 {title}")
        lines.append(f"   🎨 作者: {user_name} (ID: {user_id})")
        lines.append(f"   🆔 作品ID: {illust_id}")
        if total_bookmarks is not None:
            lines.append(f"   ❤️ 收藏: {format_number(total_bookmarks)}")
        if isinstance(x_restrict, int) and x_restrict > 0:
            lines.append("   🔞 R-18 内容")

    lines.append(f"\n💡 使用 /pixiv search {keyword} page={page + 1} 查看下一页")
    return "\n".join(lines)


def format_search_user_result(
    user_previews: list[dict[str, Any]],
    keyword: str,
    page: int,
    total_count: int | None = None,
) -> str:
    """Format search user results into a readable string."""
    if not user_previews:
        return f"🔍 搜索作者结果：关键词「{keyword}」没有找到相关作者。"

    total_str = f"共找到{format_number(total_count)}个作者" if total_count else ""
    lines = [
        f"🔍 搜索作者结果：关键词「{keyword}」（第{page}页{f'，{total_str}' if total_str else ''}）"
    ]

    for i, preview in enumerate(user_previews, 1):
        user = preview.get("user") if isinstance(preview.get("user"), dict) else {}
        user_name = user.get("name", "未知")
        user_id = user.get("id", "未知")
        account = user.get("account", "")

        # Get user profile info if available
        profile = (
            user.get("profile", {}) if isinstance(user.get("profile"), dict) else {}
        )
        total_illusts = profile.get("total_illusts", 0)
        total_manga = profile.get("total_manga", 0)

        lines.append(f"\n{i}. 👤 {user_name}")
        lines.append(f"   🆔 作者ID: {user_id}")
        if account:
            lines.append(f"   📱 账号: @{account}")
        lines.append(f"   🎨 插画: {total_illusts} | 📚 漫画: {total_manga}")

        # List recent illusts
        illusts = (
            preview.get("illusts") if isinstance(preview.get("illusts"), list) else []
        )
        if illusts:
            lines.append("   📝 最近作品:")
            for j, illust in enumerate(illusts[:3], 1):
                illust_id = illust.get("id", "未知")
                illust_title = illust.get("title", "（无标题）")
                lines.append(f"     - 作品ID: {illust_id}「{illust_title}」")

    lines.append(f"\n💡 使用 /pixiv searchuser {keyword} page={page + 1} 查看下一页")
    return "\n".join(lines)


def format_random_bookmark(
    item: dict[str, Any],
    matched_count: int | None = None,
    pages_scanned: int | None = None,
) -> str:
    """Format a random bookmark item into a readable string."""
    illust_id = item.get("illust_id")
    title = str(item.get("title") or "（无标题）")
    author_name = str(item.get("author_name") or "未知作者")
    author_id = item.get("author_id")
    tags = item.get("tags", [])
    page_count = item.get("page_count", 1)
    total_view = item.get("total_view")
    total_bookmarks = item.get("total_bookmarks")

    # Build tags display
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
        f"👁️ 浏览: {format_number(total_view)} | ❤️ 收藏: {format_number(total_bookmarks)}",
    ]

    if tags_text:
        lines.append(f"🏷️ {tags_text}")

    # R-18 indicator
    x_restrict = item.get("x_restrict", 0)
    if isinstance(x_restrict, int) and x_restrict > 0:
        lines.append("🔞 R-18 内容")

    # Show match info if available
    if matched_count is not None:
        lines.append(f"🎯 匹配: {matched_count}个作品")
    if pages_scanned is not None:
        lines.append(f"📄 扫描: {pages_scanned}页")

    return "\n".join(lines)


def tos_notice() -> str:
    """Return the Terms of Service notice."""
    return (
        "📋 使用说明（TOS 合规）："
        "仅可用于账号本人授权访问与个人查看，请勿批量抓取、商用转载或绕过 Pixiv 规则。"
    )


def help_text() -> str:
    """Return the help text for the plugin."""
    return (
        "📖 Pixiv 指令：\n"
        "- /pixiv login {refresh_token}  # 登录 Pixiv\n"
        "- /pixiv id i {illust_id}  # 查看作品详情\n"
        "- /pixiv id a {artist_id}  # 查看作者详情\n"
        "- /pixiv search {关键词} [选项]  # 搜索插画\n"
        "- /pixiv searchuser {关键词} [选项]  # 搜索作者\n"
        "- /pixiv random [筛选条件]  # 随机获取收藏\n"
        "- /pixiv random @{用户} [筛选条件]  # 查看他人收藏（需对方开启分享）\n"
        "- /pixiv random share true/false  # 开启/关闭收藏分享\n"
        "- /pixiv random r18 true/false  # 管理员：开启/关闭群聊 R-18\n"
        "- /pixiv random unique true/false  # 管理员：开启/关闭唯一随机模式\n"
        "- /pixiv random quality original/medium/small  # 管理员：设置图片质量\n"
        "- /pixiv random groupblock add/remove/list/clear [tag]  # 管理员：群聊屏蔽标签\n"
        "- /pixiv random cache add/list/clear/now/nowall/schedule [筛选条件|N]  # 闲时缓存管理\n"
        "- /pixiv dns  # 查看 DNS 刷新状态\n"
        "- /pixiv dns refresh  # 管理员：手动刷新 DNS\n"
        "- /pixiv config list/get/set/reset [key] [value]  # 管理员：配置管理\n"
        "\n💡 搜索插画选项：sort=date_desc target=partial_match_for_tags duration=within_last_week translate=true page=1 limit=10\n"
        "💡 搜索作者选项：sort=date_desc page=1 limit=10\n"
        "💡 筛选条件：tag=xxx author=xxx author_id=123 restrict=public|private max_pages=3 warmup=2 random=true"
    )
