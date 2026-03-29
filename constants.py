from __future__ import annotations

from typing import Any

# Emoji ID mapping for different stages (参考emojiReply)
EMOJI_MAP: dict[str, int] = {
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

# Plugin configuration constants
DNS_REFRESH_INTERVAL_SECONDS: float = 24 * 60 * 60
DNS_REFRESH_RETRY_SECONDS: float = 60
RANDOM_DOWNLOAD_CONCURRENCY: int = 3
MIN_COMMAND_INTERVAL_SECONDS: float = 2.0
MAX_RANDOM_PAGES: int = 8
MAX_RANDOM_WARMUP: int = 3
IDLE_CACHE_INTERVAL_SECONDS: float = 900  # 15 minutes between idle cache runs
IDLE_CACHE_COUNT: int = 5  # Number of items to cache per user during idle
DEFAULT_CACHE_SIZE: int = 10  # Default minimum cache size to maintain
DEFAULT_POOL_KEY: str = "__all__"  # Unified cache pool key per user

# Unique mode scan settings
MAX_UNIQUE_SCAN_PAGES: int = 9  # Max pages to scan in unique mode (3+3+3)
DEFAULT_SCAN_PAGES: int = 3  # Default pages to scan

# Multi-image settings
MULTI_IMAGE_THRESHOLD: int = 3  # Threshold for using forward messages
MAX_IMAGES_PER_ILLUST: int = 20  # Max images to download per illust

# Search settings
SEARCH_DEFAULT_LIMIT: int = 10
SEARCH_MAX_LIMIT: int = 30
SEARCH_SORT_OPTIONS: list[str] = [
    "date_desc",
    "date_asc",
    "popular_desc",
    "popular_male_desc",
    "popular_female_desc",
]
SEARCH_TARGET_OPTIONS: list[str] = [
    "partial_match_for_tags",
    "exact_match_for_tags",
    "title_and_caption",
]
SEARCH_DURATION_OPTIONS: list[str] = [
    "within_last_day",
    "within_last_week",
    "within_last_month",
]
SEARCH_USER_SORT_OPTIONS: list[str] = [
    "date_desc",
]

# Stage-specific emoji names
STAGE_EMOJIS: dict[str, list[str]] = {
    "login": ["赞", "OK"],  # 登录阶段
    "query_illust": ["期待", "比心"],  # 查询作品阶段
    "query_artist": ["崇拜", "爱心"],  # 查询作者阶段
    "random": ["惊喜", "庆祝"],  # 随机收藏阶段
    "search": ["期待", "暗中观察"],  # 搜索阶段
    "error": ["尴尬", "流汗"],  # 错误阶段
    "rate_limit": ["困", "哈欠"],  # 限频阶段
    "help": ["吃瓜", "暗中观察"],  # 帮助阶段
}

NON_CONFIGURABLE_CONSTANTS: frozenset[str] = frozenset(
    {
        "DNS_REFRESH_INTERVAL_SECONDS",
        "DNS_REFRESH_RETRY_SECONDS",
        "DEFAULT_SCAN_PAGES",
        "MAX_IMAGES_PER_ILLUST",
    }
)


def constant_config_key(name: str) -> str:
    if name.endswith("_SECONDS"):
        name = name[: -len("_SECONDS")]
    return name.lower()


def _is_configurable_constant(name: str, value: Any) -> bool:
    return (
        name.isupper()
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and name not in NON_CONFIGURABLE_CONSTANTS
    )


# Configurable constants are auto-generated from numeric runtime constants.
CONFIGURABLE_CONSTANTS: dict[str, Any] = {
    constant_config_key(name): value
    for name, value in globals().items()
    if _is_configurable_constant(name, value)
}

CONFIGURABLE_CONSTANT_NAMES: dict[str, str] = {
    constant_config_key(name): name
    for name, value in globals().items()
    if _is_configurable_constant(name, value)
}

CONFIGURABLE_CONSTANT_ALIASES: dict[str, str] = {}
for _config_key, _constant_name in CONFIGURABLE_CONSTANT_NAMES.items():
    CONFIGURABLE_CONSTANT_ALIASES[_config_key] = _config_key
    CONFIGURABLE_CONSTANT_ALIASES[_constant_name] = _config_key
    CONFIGURABLE_CONSTANT_ALIASES[_constant_name.lower()] = _config_key
