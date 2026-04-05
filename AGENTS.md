# PixivDirect Plugin - AI 开发指南

## 插件概述

**PixivDirect** 是一个 AstrBot 插件，用于直连访问 Pixiv，支持查询作品详情、作者信息和随机获取收藏图片。

- **版本**: v3.0.0
- **作者**: Sagiri777
- **AstrBot 要求**: >= v4.5.0
- **仓库**: https://github.com/Sagiri777/astrbot_plugin_pixivdirect

---

## 代码架构

### 目录结构

```
astrbot_plugin_pixivdirect/
├── __init__.py              # 包初始化
├── main.py                  # 插件主类与生命周期编排
├── commands.py              # 命令处理逻辑（仍待继续拆分）
├── config_manager.py        # 配置文件管理
├── cache_manager.py         # 缓存池管理
├── image_handler.py         # 图片下载与处理
├── domain/                  # 领域模型与错误定义
│   ├── errors.py
│   └── models.py
├── infrastructure/          # 内建 Pixiv 客户端与基础设施
│   ├── __init__.py
│   └── pixiv_client.py
├── plugin/                  # 稳定插件入口
│   ├── __init__.py
│   └── entry.py
├── pixivSDK.py              # 历史迁移对照文件，运行时不再调用
├── utils.py                 # 格式化与工具函数
├── emoji_reaction.py        # 表情回应处理
├── constants.py             # 常量与配置项
├── metadata.yaml            # 插件元数据
├── README.md                # 用户文档
├── scripts/                 # 本地调试与辅助脚本
└── AGENTS.md                # 本文件
```

### 模块依赖关系

```
plugin/entry.py
  └── main.py (PixivDirectPlugin)

main.py
  ├── config_manager.py (ConfigManager)
  ├── cache_manager.py (CacheManager)
  ├── image_handler.py (ImageHandler)
  ├── commands.py (CommandHandler)
  ├── emoji_reaction.py (EmojiReactionHandler)
  ├── infrastructure/pixiv_client.py (PixivClientFacade)
  └── utils.py (format_*, help_text)

commands.py
  ├── config_manager.py
  ├── cache_manager.py
  ├── image_handler.py
  ├── emoji_reaction.py
  ├── infrastructure/pixiv_client.py
  └── utils.py

cache_manager.py
  ├── config_manager.py
  └── constants.py
```

---

## 核心类说明

### 1. PixivDirectPlugin (main.py)

插件主类，继承自 `Star`。

**职责：**
- 初始化所有管理器
- 初始化内建 Pixiv 客户端
- 处理命令路由（`/pixiv` 子命令分发）
- 管理 DNS 刷新调度
- 运行空闲缓存循环

**关键方法：**
- `initialize()` - 插件初始化
- `pixiv_command()` - 主命令入口，分发子命令
- `_pixiv_call()` - 统一的 Pixiv API 调用封装，底层改走 `PixivClientFacade`
- `_idle_cache_loop()` - 空闲缓存后台任务

### 2. CommandHandler (commands.py)

命令处理逻辑，处理所有用户交互。

**职责：**
- 用户登录验证
- 作品/作者查询
- 随机收藏获取
- 配置管理（share, r18, unique, quality, cache, config）
- 群聊屏蔽标签管理
- 频率限制
- 仍是当前最大的待拆分模块，后续新增逻辑应优先考虑继续向应用层拆分

**关键方法：**
- `handle_login()` - 处理登录命令
- `handle_id()` - 处理作品/作者查询
- `handle_random()` - 处理随机收藏命令
- `rate_limit_message()` - 频率限制检查
- `should_send_image()` - R-18 和屏蔽标签过滤

### 3. ConfigManager (config_manager.py)

配置文件管理，所有持久化数据的读写入口。

**管理的配置文件：**
- `user_refresh_tokens.json` - 用户 Token
- `cache_index.json` - 缓存索引
- `share_config.json` - 分享开关
- `r18_config.json` - R-18 群聊设置
- `idle_cache_queue.json` - 空闲缓存队列
- `unique_config.json` - 唯一随机设置
- `group_blocked_tags.json` - 群聊屏蔽标签
- `sent_illust_ids.json` - 已发送作品 ID
- `image_quality_config.json` - 图片质量设置
- `custom_constants.json` - 自定义常量

**关键属性：**
- `token_map: dict[str, str]` - 用户 Token 映射
- `random_cache: dict[str, dict[str, list]]` - 统一缓存池
- `cache_dir: Path` - 图片缓存目录

### 4. CacheManager (cache_manager.py)

缓存操作管理。

**职责：**
- 从缓存池中获取匹配项
- 缓存项筛选（按标签、作者、author_id）
- R-18 内容检测
- 缓存键生成

**关键方法：**
- `pop_cached_item()` - 获取并移除缓存项
- `find_cached_by_illust_id()` - 按作品 ID 查找缓存
- `count_matching_items()` - 统计匹配项数量
- `is_r18_item()` - 检测 R-18 内容
- `parse_random_filter()` - 解析筛选参数

### 5. ImageHandler (image_handler.py)

图片下载和处理。

**职责：**
- 下载图片到缓存目录
- 下载动图 zip 文件
- 渲染动图（PIL 优先，ffmpeg 回退）

**关键方法：**
- `download_image_to_cache()` - 下载普通图片
- `download_ugoira_zip_to_cache()` - 下载动图 zip
- `render_ugoira_to_gif()` - 渲染动图为 GIF
- `format_pixiv_error()` - 格式化 API 错误

### 6. PixivClientFacade / infrastructure/pixiv_client.py

插件当前运行时使用的 Pixiv 接入层，按本地 `pixez-flutter` 行为重建。

**职责：**
- OAuth refresh token 换 access token
- App API / Web 搜索请求封装
- 图片与 ugoira 下载
- PixEz 风格 DNS 覆盖、禁用 SNI 与 host map 刷新

**关键组件：**
- `PixivTransport` - Session、请求头、超时、重试、SNI / DNS 控制
- `PixivAuthClient` - Token 刷新
- `PixivApiClient` - 作品、作者、搜索、收藏元数据接口
- `PixivImageClient` - 图片与动图二进制下载
- `PixivClientFacade` - 面向插件主流程的统一入口

> `pixivSDK.py` 仅保留作历史迁移对照，运行时不再调用；若遇到 Pixiv 接入问题，优先参考本地 `pixez-flutter/` 与 `infrastructure/pixiv_client.py`。

---

## 开发规范

### 代码风格

1. **使用 ruff 格式化**
   ```bash
   ruff format .
   ruff check .
   ```

2. **类型注解**
   - 使用 `from __future__ import annotations` 启用延迟注解
   - 使用 `dict[str, Any]`、`list[str]` 等现代类型语法
   - 可选类型使用 `str | None`

3. **导入顺序**
   ```python
   from __future__ import annotations

   import asyncio
   import time
   from pathlib import Path
   from typing import Any

   from astrbot.api import logger
   from astrbot.api.event import AstrMessageEvent, filter
   from astrbot.api.star import Context, Star

   from .cache_manager import CacheManager
   from .config_manager import ConfigManager
   ```

4. **日志使用**
   ```python
   from astrbot.api import logger
   logger.info("[pixivdirect] Message here")
   logger.warning("[pixivdirect] Warning: %s", exc)
   ```

### 异步编程

1. **同步代码转异步**
   ```python
   # 将同步的内建 Pixiv client 调用转为异步
   result = await asyncio.to_thread(
       self._pixiv_client.call_action, action, params, **kwargs
   )
   ```

2. **锁的使用**
   ```python
   # 使用 asyncio.Lock() 保护共享状态
   async with self._storage_lock:
       # 操作共享数据
   ```

3. **异步迭代器**
   ```python
   @filter.command("pixiv")
   async def pixiv_command(self, event: AstrMessageEvent, args_str: str = ""):
       # 使用 yield 返回多个结果
       yield event.plain_result("消息")
       yield event.make_result().message("带图片").file_image(path)
   ```

### 错误处理

1. **API 调用错误**
   ```python
   result = await self._pixiv_call("illust_detail", params, refresh_token=token)
   if not result.get("ok"):
       await self._emoji_handler.add_emoji_reaction(event, "error")
       yield event.plain_result(self._image.format_pixiv_error(result))
       return
   ```

2. **连接错误重试**
   ```python
   try:
       result = await self._pixiv_call(...)
   except (ConnectionError, OSError) as exc:
       if attempt < max_retries:
           await asyncio.sleep(5)
           continue
   ```

3. **文件操作保护**
   ```python
   try:
       self._token_file.write_text(...)
   except OSError as exc:
       logger.warning("[pixivdirect] Failed to save: %s", exc)
   ```

---

## 常见开发任务

### 添加新命令

1. **在 `main.py` 的 `pixiv_command()` 中添加路由**
   ```python
   elif sub_cmd == "newcmd":
       async for result in self._command_handler.handle_newcmd(
           event, ["newcmd", *tokens[1:]]
       ):
           yield result
   ```

2. **在 `commands.py` 中实现处理函数**
   ```python
   async def handle_newcmd(self, event: AstrMessageEvent, args: list[str]):
       # 参数验证
       if len(args) < 2:
           yield event.plain_result("❌ 用法：/pixiv newcmd <arg>")
           return

       # Token 检查
       user_token = self.get_user_token(event)
       if not user_token:
           yield event.plain_result("❌ 请先登录：/pixiv login {refresh_token}")
           return

       # 执行逻辑
       # ...

       # 返回结果
       yield event.plain_result("✅ 操作成功")
   ```

3. **在 `utils.py` 中更新 `help_text()`**

### 添加新配置项

1. **在 `constants.py` 中定义默认值**
   ```python
   NEW_CONFIG_DEFAULT: int = 100
   CONFIGURABLE_CONSTANTS: dict[str, Any] = {
       # ... 现有配置
       "new_config": NEW_CONFIG_DEFAULT,
   }
   ```

2. **在 `config_manager.py` 中添加加载/保存逻辑**
   ```python
   # 添加属性
   self._new_config: dict[str, Any] = {}

   # 添加加载方法
   def _load_new_config(self) -> None:
       # 从 JSON 文件加载
       ...

   # 添加保存方法
   async def save_new_config(self) -> None:
       async with self._cache_lock:
           # 写入 JSON 文件
           ...
   ```

3. **在 `ConfigManager.load_all()` 中调用加载**

### 修改缓存逻辑

1. **缓存池结构**
   ```python
   # 统一缓存池结构
   {
       "user_key": {
           "__all__": [  # DEFAULT_POOL_KEY
               {
                   "path": "/path/to/image.jpg",
                   "caption": "作品详情文本",
                   "x_restrict": 0,
                   "tags": ["tag1", "tag2"],
                   "illust_id": 123456,
                   "author_id": 789,
                   "author_name": "画师名",
                   "page_count": 1
               }
           ]
       }
   }
   ```

2. **添加缓存项**
   ```python
   _user_cache = self._config.random_cache.setdefault(user_key, {})
   _queue = _user_cache.setdefault(DEFAULT_POOL_KEY, [])
   _queue.append({
       "path": local_path,
       "caption": caption,
       "x_restrict": illust.get("x_restrict", 0),
       "tags": tags,
       "illust_id": illust_id,
   })
   await self._config.save_cache_index()
   ```

3. **筛选逻辑在 `cache_manager.py` 的 `_item_matches_filter()` 中修改**

### 调用 Pixiv API

```python
# 通过 _pixiv_call 调用（自动处理 DNS、重试、Token 刷新）
result = await self._pixiv_call(
    "illust_detail",           # action 名称
    {"illust_id": 12345678},   # 参数
    refresh_token=user_token,  # 用户 Token
)

if not result.get("ok"):
    # 处理错误
    error_msg = self._image.format_pixiv_error(result)
    return

# 获取刷新后的 Token
latest_token = result.get("refresh_token") or user_token
if latest_token != user_token:
    await self.set_user_token(event, latest_token)

# 处理数据
data = result.get("data")
```

---

## 数据存储

### 存储位置

所有持久化数据存储在 AstrBot 数据目录下：
```
{astrbot_data_path}/pixivdirect/
├── user_refresh_tokens.json
├── cache/
│   ├── cache_index.json
│   ├── illust_123456_0_xxx.jpg
│   └── ...
├── pixiv_host_map.json
├── share_config.json
├── r18_config.json
├── idle_cache_queue.json
├── unique_config.json
├── group_blocked_tags.json
├── sent_illust_ids.json
├── image_quality_config.json
└── custom_constants.json
```

### 获取数据目录路径

```python
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

plugin_data_dir = Path(get_astrbot_plugin_data_path()) / "pixivdirect"
```

---

## 调试与测试

### 日志查看

```bash
# 查看插件相关日志
tail -f {astrbot_data_path}/logs/astrbot.log | grep pixivdirect

# 实时调试级别日志
grep -E "\[pixivdirect\]" {astrbot_data_path}/logs/astrbot.log
```

### 本地脚本调试

当 AI 需要在本地复现 `/pixiv search ...`、`/pixiv searchuser ...` 等网络问题时，优先使用“模拟插件命令流，但不模拟文件读取”的方式：

1. 使用脚本模拟 `main.py -> CommandHandler -> _pixiv_call -> infrastructure/pixiv_client.py` 的命令解析、参数构造、DNS 重试和搜索兜底逻辑。
2. 不要为了这类网络调试去构造完整的 `ConfigManager` 持久化数据、插件数据目录或 `user_refresh_tokens.json` 读取流程。
3. Token、关键词、页码等调试输入应通过命令行参数、环境变量，或脚本内显式传参提供，而不是依赖插件运行时文件读取。
4. 若沙箱阻止外网请求，应重新以提权方式执行同一条测试命令，不要把沙箱报错误判为 Pixiv 接口本身错误。
5. 调试目标是确认“插件命令行为”是否正确，例如：
   - `/pixiv search keyword` 是否先走 `search_illust`
   - 当作品搜索为空时，是否按插件当前逻辑回退到 `search_user`
   - 搜索参数是否和插件真实发送的一致
   - DNS 重试和运行时解析是否生效

推荐使用仓库内的调试脚本作为这类本地调试的入口，但重点是“模拟插件搜索链路”，而不是依赖真实插件配置文件。

### Token 调试输入

- 若仓库内已有可复用的脚本或方法用于提供测试 Token，可以将其作为脚本输入来源。
- 但在文档、脚本和调试说明中，应强调 Token 只是调试输入，不属于插件文件读取流程的一部分。
- **绝不**在日志、提交信息或文档示例中直接明文写出真实 Token。

### README 版本摘要数量检查

更新 `README.md` 的版本摘要前后，AI 应优先使用 `scripts/getReadmeVersionCount.py` 检查摘要数量，确保 README 中仅保留最近 5 条版本摘要：

```bash
python3 scripts/getReadmeVersionCount.py
```

若输出大于 `5`，必须删除最旧的多余版本摘要，再提交改动。

### 热重载

1. 修改代码后
2. 在 AstrBot WebUI 插件管理页找到插件
3. 点击 `...` -> `重载插件`
4. 查看是否有错误提示

### 常见错误

1. **Token 无效** - 用户需要重新获取 refresh_token
2. **连接超时** - 检查网络或 DNS 配置
3. **依赖缺失** - 确保 `requirements.txt` 包含所有依赖
4. **文件权限** - 确保数据目录可写

---

## 注意事项

### 安全

- **绝不记录或暴露用户 Token**
- **不将 Token 写入日志**
- **使用临时文件原子写入敏感配置**

### 性能

- **使用 `asyncio.to_thread()` 将同步 API 调用转为异步**
- **控制并发下载数量（默认 3）**
- **空闲缓存避免频繁请求**

### 兼容性

- **支持多平台**（aiocqhttp, telegram, discord 等）
- **R-18 内容在群聊中仅显示信息（默认）**
- **动图支持 PIL 和 ffmpeg 双渲染**

### 提交规范

使用 Conventional Commits 格式：
- `feat: add new command for ...`
- `fix: resolve issue with ...`
- `refactor: improve ...`
- `docs: update README`

每次完成代码、文档或配置修改后，必须整理本次改动并写好一次对应的 Git commit；不要只停留在工作区未提交状态。

---

## 版本号管理

### README 更新日志维护规则

- `README.md` 中的版本摘要**仅保留最近 5 条**。
- 新增版本摘要时，若超过 5 条，必须删除最旧的多余记录。
- 完整历史统一维护在 `CHANGELOG.md`。

### 版本号格式

采用 **语义化版本** (Semantic Versioning)：`MAJOR.MINOR.PATCH`

当前版本：`v3.0.0`

### 更新规则

| 更新类型 | 版本变化 | 示例 |
|----------|----------|------|
| Bug 修复 | PATCH | `1.6.0` -> `1.6.1` |
| 小改动、文档更新 | PATCH | `1.6.0` -> `1.6.1` |
| 新增功能/命令 | MINOR | `1.6.0` -> `1.7.0` |
| 新增配置项 | MINOR | `1.6.0` -> `1.7.0` |
| 重大重构 | MAJOR | `1.6.0` -> `2.0.0` |
| 不兼容的 API 修改 | MAJOR | `1.6.0` -> `2.0.0` |

> 例外：若仅进行文档/注释等非功能性改动（不影响插件行为），可不修改版本号。

### 具体场景判断

**PATCH 更新（1.6.0 -> 1.6.1）：**
- 修复现有命令的 bug
- 修复配置加载/保存问题
- 修复缓存逻辑错误
- 修复格式化/显示问题
- 更新文档（README、注释）
- 代码重构（不改变功能）
- 依赖版本更新

**MINOR 更新（1.6.0 -> 1.7.0）：**
- 新增 `/pixiv` 子命令
- 新增配置项（CONFIGURABLE_CONSTANTS）
- 新增筛选参数
- 新增平台支持
- 新增缓存策略
- 新增用户设置选项

**MAJOR 更新（1.6.0 -> 2.0.0）：**
- 重构插件架构
- 修改命令语法（破坏向后兼容）
- 修改缓存池结构（需要迁移）
- 移除已有功能
- 修改 API 接口签名

### 需要更新的文件

完成代码修改后，**必须**同步更新以下文件：

1. **`metadata.yaml`** - 更新 `version` 字段
   ```yaml
   version: v1.7.0  # 更新版本号
   ```

2. **`CHANGELOG.md`** - 创建/更新变更日志（见下方详细说明）

3. **`README.md`** - 更新版本号和更新日志
   ```markdown
   ### v1.7.0
   - 新增 xxx 功能
   - 修复 xxx 问题
   ```

### CHANGELOG.md 规范

**必须**在插件目录下创建或更新 `CHANGELOG.md` 文件，记录版本变更历史。

**文件格式：**

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- 新增的功能

### Changed
- 修改的功能

### Fixed
- 修复的问题

### Removed
- 移除的功能

## [1.6.0] - 2024-01-15

### Added
- 唯一模式优化：记录已发送图片ID
- 多图片支持：自动合并转发
- 图片质量设置

### Fixed
- 修复闲时缓存 count 参数无效的问题
```

**变更类别说明：**

| 类别 | 说明 | 版本影响 |
|------|------|----------|
| `Added` | 新增功能 | MINOR |
| `Changed` | 修改现有功能 | PATCH |
| `Deprecated` | 即将移除的功能 | MINOR |
| `Removed` | 已移除的功能 | MAJOR |
| `Fixed` | Bug 修复 | PATCH |
| `Security` | 安全相关修复 | PATCH |

**更新流程：**

```python
# 1. 将 [Unreleased] 下的变更移动到新版本下
# 2. 添加版本号和日期
## [1.7.0] - 2024-03-26

### Added
- 新增 /pixiv xxx 命令
- 新增 xxx 配置项

### Fixed
- 修复 xxx 问题

# 3. 保留空的 [Unreleased] 部分供下次使用
## [Unreleased]

### Added
-
```

### 版本更新流程

```bash
# 1. 完成功能开发和测试
# 2. 根据更新类型确定新版本号
# 3. 更新 CHANGELOG.md（将 Unreleased 变更移到新版本下）
# 4. 更新 metadata.yaml
# 5. 更新 README.md 更新日志
# 6. 运行 ruff 检查
ruff format . && ruff check .
# 8. 提交代码
git add -A && git commit -m "feat: add new feature (v1.7.0)"
```

---

## 快速参考

### 命令格式

```
/pixiv help                           # 帮助
/pixiv login {refresh_token}          # 登录
/pixiv id i {illust_id}              # 查看作品
/pixiv id a {artist_id}              # 查看作者
/pixiv random [筛选条件]               # 随机收藏
/pixiv random share true/false        # 分享开关
/pixiv random r18 true/false          # R-18 群聊开关
/pixiv random unique true/false       # 唯一随机开关
/pixiv random quality original/medium/small  # 图片质量
/pixiv random cache add/list/clear/now       # 缓存管理
/pixiv groupblock add/remove/list/clear      # 屏蔽标签
/pixiv dns                            # DNS 状态
/pixiv config list/get/set/reset      # 配置管理
```

### 筛选参数

| 参数 | 缩写 | 示例 |
|------|------|------|
| tag | t | `tag=风景` |
| author | a | `author=画师名` |
| author_id | aid | `author_id=1234567` |
| restrict | r | `restrict=public\|private` |
| max_pages | pages | `max_pages=5` |
| warmup | - | `warmup=2` |
| random | - | `random=true` |

### 关键常量

```python
DEFAULT_POOL_KEY = "__all__"           # 统一缓存池键
MIN_COMMAND_INTERVAL_SECONDS = 2.0     # 命令间隔
MAX_RANDOM_PAGES = 8                   # 最大扫描页数
IDLE_CACHE_INTERVAL_SECONDS = 900      # 空闲缓存间隔
IDLE_CACHE_COUNT = 5                   # 空闲缓存数量
DEFAULT_CACHE_SIZE = 10                # 默认缓存大小
MULTI_IMAGE_THRESHOLD = 3              # 多图合并转发阈值
```
