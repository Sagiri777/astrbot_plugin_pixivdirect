# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- 

### Changed
- 

### Fixed
- 

## [1.8.7] - 2026-03-29

### Changed
- 抽取 `commands.py` 中随机缓存补货与缓存取回的公共 helper，进一步压缩共享/自身两条随机流程的重复代码

### Fixed
- 统一随机补货调用参数构造，降低共享随机和自用随机后续调整时出现分支不一致的风险

## [1.8.6] - 2026-03-29

### Changed
- 抽取 `commands.py` 中共享目标解析与 `warmup` 参数解析逻辑，减少随机收藏分支内的重复代码

### Fixed
- 统一 `@用户` 文本和 QQ `At` 组件的共享目标解析入口，避免后续修改时两套逻辑漂移

## [1.8.5] - 2026-03-29

### Changed
- 抽取 `commands.py` 中随机收藏结果发送与剩余缓存统计的公共逻辑，减少共享/自身、缓存/新获取四条路径的重复代码

### Fixed
- 优化随机收藏响应分支的维护性，统一 R-18 文本回退与筛选条件展示逻辑

## [1.8.4] - 2026-03-29

### Changed
- 抽取 `image_handler.py` 中图片/动图二进制下载的公共逻辑，统一动图帧延迟与压缩包图像列表处理
- 抽取 `emoji_reaction.py` 中 aiocqhttp 消息上下文与阶段表情 ID 解析逻辑，减少重复分支

### Fixed
- 优化表情反应处理流程，避免添加和移除路径分别维护各自的平台判断与消息 ID 提取代码

## [1.8.3] - 2026-03-29

### Changed
- 继续收敛 `config_manager.py` 的 JSON 加载逻辑，统一默认文件创建、映射归一化和闲时缓存队列校验
- 提取 `cache_manager.py` 的缓存路径有效性检查，减少重复文件存在性判断

### Fixed
- 修复唯一随机配置历史值兼容性较弱的问题，旧布尔/字符串值现在会统一归一化为 `true` 或 `false`
- 修复闲时缓存队列读取时对 `count`、`remaining` 缺少规范化的问题，异常值会回退到安全默认值
- 优化已发送作品 ID 的持久化顺序，避免 JSON 输出顺序抖动

## [1.8.2] - 2026-03-29

### Changed
- 抽取命令布尔值解析与作品缓存写入的公共逻辑，减少 `commands.py` 内重复代码

### Fixed
- 修复频率限制在用户被限流时仍会刷新时间戳，导致连续重试会不断延长等待时间的问题
- 修复作品详情和随机缓存写入时元数据结构不一致的问题，统一补齐作者与页数字段

## [1.8.1] - 2026-03-28

### Changed
- 群聊 R-18 自动打码改为直接内置 AutoHajimiMosaic 的核心分割与贴图流程，不再使用简化版近似实现
- 清理仓库内临时引入的 AutoHajimiMosaic Web/UI、Docker 与批处理文件，仅保留插件运行所需模型与素材

## [1.8.0] - 2026-03-28

### Added
- 新增群聊 R-18 标签显示开关，可单独控制是否展示标签行
- 新增群聊 R-18 图片自动打码开关，发送时可自动生成打码版本

### Changed
- 群聊内所有 R-18 图片发送路径现在统一经过标签过滤与可选打码处理，覆盖随机收藏、作品详情和搜索预览

## [1.7.3] - 2026-03-28

### Fixed
- 修复 `/pixiv dns refresh` 在当日已刷新过 DNS 后仍可能被 mtime 判定跳过的问题
- 修复 `/pixiv random cache now N` 的成功统计会把历史缓存误算进本次结果的问题
- 修复闲时缓存与即时缓存补货后未保存新的 refresh token，导致后续请求可能继续使用旧 token 的问题
- 修复 `/pixiv searchuser` 仍会复用插画搜索的选项解析并透传不适用参数的问题

## [1.7.2] - 2026-03-28

### Fixed
- 为 `/pixiv search` 和 `/pixiv searchuser` 增加对 440、429 和 5xx 状态码的自动重试
- 搜索类请求首次失败后会强制刷新 DNS 并重新鉴权后再请求一次，降低偶发搜索失败概率

## [1.7.1] - 2026-03-28

### Changed
- 运行时配置项现在会实际作用于限频、闲时缓存间隔、缓存目标数量和随机扫描页数
- `/pixiv search` 与 `/pixiv searchuser` 现支持多词关键词，并正确分离后续选项
- `/pixiv groupblock`、`/pixiv config` 以及 share/r18/unique/quality/cache 增加顶级命令别名

### Fixed
- 修复 `/pixiv dns refresh` 仅提示成功但未真正触发下次 DNS 刷新的问题
- 修复 `count=` 与 `random=true` 筛选参数未被解析，导致闲时缓存和彻底随机模式失效的问题
- 修复唯一随机模式未记录已发送作品、补货时未排除已发送作品的问题
- 修复群屏蔽标签命令与文档不一致，现支持 `tag=xxx` 和包含空格的标签输入
- 修复缓存索引重载时遗漏 `page_count` 元数据的问题

## [1.7.0] - 2026-03-26

### Added
- Search illustrations command (`/pixiv search {keyword}`)
- Search users command (`/pixiv searchuser {keyword}`)
- Translated tag support with `translate=true/false` option
- Search options: sort, target, duration, page, limit
- Search results display with illust preview image
- User search results with recent works list

### Changed
- Improved emoji reaction handler with duplicate detection
- Cleaned up debug logging in emoji_reaction.py

## [1.6.0] - 2026-03-26

### Added
- Unique mode optimization: track sent image IDs, auto-expand scan range
- Multi-image support: auto forward messages for >3 images
- Image quality settings (original/medium/small)
- Config management command (`/pixiv config`)
- DNS status display in `/pixiv dns`
- Cache now command for immediate caching

### Changed
- Refactored main.py into submodules
- Use event.message_str for full command arguments

### Fixed
- Fixed idle cache count parameter not working
- Fixed @ user mention handling
- Fixed share command debug logging

## [1.0.0] - 2026-03-24

### Added
- Unified cache pool with metadata filtering
- R-18 group chat filtering with admin config
- Ugoira support with PIL and ffmpeg dual rendering
- Idle cache queue and unique random mode
- Group blocked tags management
- Image quality configuration

### Fixed
- Fixed cache, config management and random selection issues

## [0.3.0] - 2026-03-23

### Added
- Unified cache pool for cross-filter reuse
- Metadata-based filtering (tags, author, R-18)
- R-18 group chat filtering (admin configurable)
- illustID cache auto-add to random pool
- Token-free operations for share/r18/@username
- ffmpeg fallback for ugoira rendering
- Emoji reaction toggle
- Debug logging and SSL optimization
- Accesser and pixez-flutter integration

### Fixed
- Fixed share config blocked by token check

## [0.2.0] - 2026-03-23

### Added
- Emoji mapping and cache mechanism
- Collection sharing feature
- `/pixiv random share` command
- Message filter for commands

## [0.1.0] - 2026-03-23

### Added
- Initial release
- User login with refresh_token
- Illust detail query
- Artist detail query
- Random bookmark collection
- Built-in cache and rate limiting
- PixEz DNS proxy support
