# astrbot-plugin-pixivdirect

基于 `pixez-flutter` 行为重建的 AstrBot Pixiv 插件。

当前版本：`v4.1.0`

## 更新日志

README 中仅保留最近 5 条版本摘要，完整历史见 [CHANGELOG.md](./CHANGELOG.md)。

### v4.1.0

- 补齐第 1 阶段 PixEz 能力：`ranking`、`recommended`、`related`、`ugoira`
- 新增 `/pixiv ranking`、`/pixiv recommended`、`/pixiv related`、`/pixiv ugoira`
- 补充第 1 阶段测试与迁移矩阵文档，明确 PixEz 非 UI 能力的已对齐/未对齐状态

### v4.0.0

- 以 `pixez-flutter` 为唯一行为参考，重写插件入口、命令层、配置层和 Pixiv 接入层
- 运行时改为新的 PixEz 风格内核，统一处理 OAuth、App API、Web 搜索、图片下载与 host map
- 插件命令收敛为 PixEz 移植版的基础能力：登录、作品/作者详情、作品搜索、用户搜索、随机收藏、质量设置、DNS 状态

### v3.0.3

- 修复 OAuth 刷新令牌请求在 `oauth.secure.pixiv.net` 命中失效缓存 IP 后直接 connect timeout 失败的问题，现会自动继续尝试运行时 DNS 候选 IP
- 修复认证阶段没有完整继承主调用链的超时、DNS 刷新和重试参数，避免 auth 与后续 Pixiv API 请求策略不一致

### v3.0.2

- 移除插件主流程到内建客户端之间的 `bypass_mode` 透传，改为只保留实际使用中的 `bypass_sni`、代理和 DNS 控制参数
- 修复 `/pixiv` 命令调用新客户端时因多传 `bypass_mode` 导致的异常

### v3.0.1

- 修复 `pixiv_command` 触发 Pixiv 请求时，内建客户端未兼容历史 `bypass_mode` 关键字参数而导致直接抛异常的问题
- `PixivClientFacade` 现已兼容旧调用方式，并补充回归测试覆盖这条链路

## 当前能力

- `/pixiv login <refresh_token>`
- `/pixiv id i <illust_id>`
- `/pixiv id a <user_id>`
- `/pixiv search <keyword>`
- `/pixiv searchuser <keyword>`
- `/pixiv ranking [mode=day] [date=YYYY-MM-DD]`
- `/pixiv recommended [type=illust|manga|user]`
- `/pixiv related <illust_id>`
- `/pixiv ugoira <illust_id> [download=true|false]`
- `/pixiv random [tag=标签] [restrict=public|private] [pages=1-8]`
- `/pixiv quality <small|medium|original>`
- `/pixiv dns`

## 架构

- [main.py](/Users/guozimier/Downloads/AstrBot/data/plugins/astrbot_plugin_pixivdirect/main.py)：AstrBot 插件入口与命令分发
- [commands.py](/Users/guozimier/Downloads/AstrBot/data/plugins/astrbot_plugin_pixivdirect/commands.py)：插件命令适配层
- [config_manager.py](/Users/guozimier/Downloads/AstrBot/data/plugins/astrbot_plugin_pixivdirect/config_manager.py)：Token、偏好设置与下载索引持久化
- [image_handler.py](/Users/guozimier/Downloads/AstrBot/data/plugins/astrbot_plugin_pixivdirect/image_handler.py)：图片下载与 ugoira 渲染
- [infrastructure/pixiv_client.py](/Users/guozimier/Downloads/AstrBot/data/plugins/astrbot_plugin_pixivdirect/infrastructure/pixiv_client.py)：面向插件的 PixEz 客户端入口
- [PIXEZ_MIGRATION_MATRIX.md](/Users/guozimier/Downloads/AstrBot/data/plugins/astrbot_plugin_pixivdirect/PIXEZ_MIGRATION_MATRIX.md)：PixEz 非 UI 能力迁移矩阵

## 使用方式

1. 将插件放入 AstrBot 的 `data/plugins/astrbot_plugin_pixivdirect/` 目录。
2. 在聊天中执行 `/pixiv login <refresh_token>`。
3. 使用 `/pixiv help` 查看命令。

## 说明

- 该版本以 `pixez-flutter/lib/network/`、`pixez-flutter/lib/models/` 与 hoster 逻辑为参考，目标是把 PixEz 的 Pixiv 接入方式移植到 AstrBot 插件环境。
- 仓库已经清理掉旧插件实现和历史运行残留，当前保留的文件均服务于新的 PixEz 插件实现、测试或发布流程。
