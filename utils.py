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


HELP_MENU: list[dict[str, Any]] = [
    {
        "section": "基础",
        "items": [
            {"command": "/pixiv help", "description": "查看完整帮助菜单"},
            {
                "command": "/pixiv login {refresh_token}",
                "description": "绑定 Pixiv 账号，后续命令默认使用该账号访问",
                "usage_key": "login",
            },
            {
                "command": "/pixiv id i {illust_id}",
                "description": "查看单个作品详情，支持多图与动图",
                "usage_key": "id",
            },
            {
                "command": "/pixiv id a {artist_id}",
                "description": "查看作者详情与作品统计",
                "usage_key": "id",
            },
        ],
    },
    {
        "section": "搜索",
        "items": [
            {
                "command": "/pixiv search {关键词} [选项]",
                "description": "搜索插画，可附带排序、时间范围、页码等参数",
                "usage_key": "search",
            },
            {
                "command": "/pixiv searchuser {关键词} [选项]",
                "description": "搜索作者，可附带排序、页码、数量等参数",
                "usage_key": "searchuser",
            },
            {
                "command": "插画选项：sort=date_desc target=partial_match_for_tags duration=within_last_week translate=true page=1 limit=10",
                "description": "插画搜索的常见可选参数",
            },
            {
                "command": "作者选项：sort=date_desc page=1 limit=10",
                "description": "作者搜索的常见可选参数",
            },
        ],
    },
    {
        "section": "随机收藏",
        "items": [
            {
                "command": "/pixiv random",
                "description": "随机获取自己收藏中的图片，作品多图时会自动接入多图发送逻辑",
                "usage_key": "random",
            },
            {
                "command": "/pixiv random tag=风景",
                "description": "按标签、作者、页数等条件筛选自己的收藏",
                "usage_key": "random",
            },
            {
                "command": "/pixiv random @{用户} [筛选条件]",
                "description": "在对方开启分享时查看对方的收藏随机图",
                "usage_key": "random",
            },
            {
                "command": "筛选参数：tag=xxx&!yyy author=aaa&！bbb author_id=123&!456 restrict=public|private max_pages=3 warmup=2 random=true",
                "description": "随机收藏支持多正负筛选（tag/author/author_id，支持 ! 和 ！）",
            },
        ],
    },
    {
        "section": "常用设置",
        "items": [
            {
                "command": "/pixiv share true/false",
                "description": "开启或关闭自己的收藏分享",
                "usage_key": "share",
            },
            {
                "command": "/pixiv quality original/medium/small",
                "description": "设置后续下载图片的质量档位",
                "usage_key": "quality",
            },
            {
                "command": "/pixiv unique true/false",
                "description": "开启后尽量避免重复发送同一作品",
                "usage_key": "unique",
            },
            {
                "command": "/pixiv r18 true/false",
                "description": "设置群聊中是否允许直接发送 R-18 图片",
                "usage_key": "r18",
            },
            {
                "command": "/pixiv r18 tag true/false",
                "description": "设置群聊中是否显示 R-18 标签提示",
                "usage_key": "r18",
            },
            {
                "command": "/pixiv r18 mosaic true/false",
                "description": "设置群聊 R-18 图片是否自动打码",
                "usage_key": "r18",
            },
            {
                "command": "/pixiv r18 mosaic mode off/hajimi/blur",
                "description": "设置 R-18 打码模式，可选关闭、哈基米打码或全图模糊",
                "usage_key": "r18",
            },
            {
                "command": "/pixiv r18 mosaic strength 1-100",
                "description": "设置全图模糊模式的强度，支持按群或私聊用户分别配置",
                "usage_key": "r18",
            },
        ],
    },
    {
        "section": "管理",
        "items": [
            {
                "command": "/pixiv cache add/list/clear/now/nowall/schedule [筛选条件|N]",
                "description": "管理闲时缓存任务与手动补货",
                "usage_key": "cache",
            },
            {
                "command": "/pixiv groupblock add/remove/list/clear tag=xxx",
                "description": "管理群聊屏蔽标签，命中后随机图不会直接发送",
                "usage_key": "groupblock",
            },
            {
                "command": "/pixiv dns",
                "description": "查看当前 DNS 刷新状态",
                "usage_key": "dns",
            },
            {
                "command": "/pixiv dns refresh",
                "description": "手动触发一次 DNS 刷新",
                "usage_key": "dns",
            },
            {
                "command": "/pixiv config list/get/set/reset [key] [value]",
                "description": "查看或修改插件运行配置项",
                "usage_key": "config",
            },
            {
                "command": "/pixiv bypass",
                "description": "查看当前绕过模式与 legacy 开关状态",
                "usage_key": "bypass",
            },
            {
                "command": "/pixiv bypass mode auto|pixez|accesser",
                "description": "切换 PixEz / Accesser / 自动混合模式",
                "usage_key": "bypass",
            },
            {
                "command": "/pixiv proxy status/set/clear/enable/threshold/sticky",
                "description": "管理搜索失败后的代理兜底与粘滞代理窗口",
                "usage_key": "proxy",
            },
        ],
    },
]


def help_text() -> str:
    """Return the help text for the plugin."""
    lines = ["📖 PixivDirect 帮助"]
    for section in HELP_MENU:
        lines.append(f"\n【{section['section']}】")
        for item in section["items"]:
            lines.append(f"- {item['command']}  # {item['description']}")
    lines.append(
        "\n💡 顶级别名：/pixiv share、/pixiv quality、/pixiv cache、/pixiv dns、/pixiv config、/pixiv bypass、/pixiv proxy、/pixiv groupblock"
    )
    return "\n".join(lines)


def command_usage(command: str) -> str | None:
    """Return targeted usage text for a specific subcommand."""
    section = next(
        (
            current
            for current in HELP_MENU
            if any(item.get("usage_key") == command for item in current["items"])
        ),
        None,
    )
    if section is None:
        return None

    lines = [f"📋 /pixiv {command} 用法："]
    descriptions: list[str] = []
    for item in section["items"]:
        if item.get("usage_key") != command:
            continue
        lines.append(f"- {item['command']}  # {item['description']}")
        descriptions.append(str(item["description"]))

    if command == "id":
        lines.append("说明：`i` 查询作品，`a` 查询作者。")
    elif command == "random":
        lines.append("- /pixiv random share true/false  # 开启或关闭收藏分享")
        lines.append(
            "- /pixiv random quality original/medium/small  # 设置随机图下载质量"
        )
        lines.append(
            "- /pixiv random cache add/list/clear/now/nowall/schedule  # 管理随机缓存"
        )
    elif command == "cache":
        lines.append("- /pixiv cache add tag=xxx count=N|always  # 添加缓存任务")
        lines.append("- /pixiv cache list  # 查看缓存任务")
        lines.append("- /pixiv cache clear  # 清空缓存任务")
        lines.append("- /pixiv cache now N  # 立即补货 N 张")
        lines.append("- /pixiv cache nowall  # 立即执行所有缓存任务")
        lines.append("- /pixiv cache schedule  # 查看缓存调度")
    elif command == "dns":
        lines.append("说明：查看状态或手动刷新 DNS。")
    elif command == "groupblock":
        lines.append("- /pixiv groupblock add tag=xxx  # 添加屏蔽标签")
        lines.append("- /pixiv groupblock remove tag=xxx  # 删除屏蔽标签")
        lines.append("- /pixiv groupblock list  # 查看当前屏蔽标签")
        lines.append("- /pixiv groupblock clear  # 清空屏蔽标签")
    elif command == "config":
        lines.append("- /pixiv config list  # 查看全部配置")
        lines.append("- /pixiv config get <key>  # 查看单个配置")
        lines.append("- /pixiv config set <key> <value>  # 修改配置")
        lines.append("- /pixiv config reset [key]  # 重置配置")
    elif command == "bypass":
        lines.append("- /pixiv bypass  # 查看当前绕过模式")
        lines.append("- /pixiv bypass mode auto  # 使用自动混合模式")
        lines.append("- /pixiv bypass mode pixez  # 只走 PixEz 式直连")
        lines.append("- /pixiv bypass mode accesser  # 只走 Accesser 式域名覆盖")
    elif command == "proxy":
        lines.append("- /pixiv proxy status  # 查看搜索代理状态")
        lines.append("- /pixiv proxy set <proxy_url>  # 设置搜索代理地址")
        lines.append("- /pixiv proxy clear  # 清空搜索代理地址")
        lines.append("- /pixiv proxy enable true/false  # 启用或禁用搜索代理")
        lines.append("- /pixiv proxy threshold <count>  # 设置每日触发阈值")
        lines.append("- /pixiv proxy sticky <days>  # 设置粘滞代理天数")
    elif command == "r18":
        lines.append("- /pixiv r18 true/false  # 群聊中控制是否发送 R-18 图片")
        lines.append("- /pixiv r18 tag true/false  # 群聊中控制是否显示标签")
        lines.append("- /pixiv r18 mosaic true/false  # 群聊中快速开启或关闭自动打码")
        lines.append(
            "- /pixiv r18 mosaic mode off/hajimi/blur  # 设置打码模式，私聊可为当前用户单独配置"
        )
        lines.append(
            "- /pixiv r18 mosaic strength 1-100  # 设置全图模糊强度，私聊和群聊分别生效"
        )
    elif descriptions:
        lines.append(f"说明：{descriptions[0]}")

    return "\n".join(lines)
