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

## [4.1.0] - 2026-04-05

### Added
- 新增 `/pixiv ranking`、`/pixiv recommended`、`/pixiv related` 与 `/pixiv ugoira` 命令
- 新增 `PIXEZ_MIGRATION_MATRIX.md`，系统梳理 PixEz 非 UI 能力迁移矩阵

### Changed
- 第 1 阶段已补齐 PixEz 对齐能力：`illust_ranking`、`illust_recommended`、`illust_related`、`ugoira_metadata`
- ugoira 命令现已支持 metadata 获取、zip 下载、GIF 渲染和基本发送链路
- README 当前能力、帮助文本与测试覆盖同步扩展到第 1 阶段命令

## [4.0.0] - 2026-04-05

### Added
- 新增基于 `pixez-flutter` 结构拆分的 `infrastructure/pixez` 内核，统一承载 PixEz 风格的 host map、传输层、OAuth 和 App API facade
- 新增 AstrBot 命令适配层的精简实现，提供 PixEz 移植版的登录、详情查询、搜索、随机收藏、质量设置和 DNS 查看能力

### Changed
- 以 `pixez-flutter` 为唯一行为参考，重写 `main.py`、`commands.py`、`config_manager.py`、`cache_manager.py`、`image_handler.py` 与 `infrastructure/pixiv_client.py`
- 插件运行时主路径已切换到新的 PixEz 插件实现，不再依赖旧的命令层和旧客户端结构

### Removed
- 移除旧测试集，改为围绕新的 PixEz 插件实现补充基础回归测试
- 清理旧 SDK、旧辅助模块、旧调试脚本和哈基米资源文件，仓库仅保留当前 PixEz 插件实现所需内容

## [3.0.3] - 2026-04-05

### Fixed
- 修复 `oauth.secure.pixiv.net` 命中失效缓存 IP 时，OAuth 刷新令牌流程会在 connect timeout 后直接失败的问题；现在会自动尝试运行时 DNS 候选 IP 继续认证
- 修复认证阶段未透传 `connect_timeout`、`dns_timeout`、`dns_update_hosts`、`runtime_dns_resolve` 等网络参数，导致 auth 请求与主请求链路行为不一致的问题

## [3.0.2] - 2026-04-05

### Changed
- 移除 `main.py -> PixivClientFacade.call_action()` 这条新客户端调用链中的 `bypass_mode` 透传，改为仅保留实际仍生效的 `bypass_sni`、代理与 DNS 控制参数，避免继续堆叠无效兼容层

### Fixed
- 修复 `/pixiv` 主命令调用内建客户端时因为继续传递 `bypass_mode` 而触发参数不匹配异常的问题

## [3.0.1] - 2026-04-05

### Fixed
- 修复 `PixivDirectPlugin._pixiv_call()` 透传 `bypass_mode` 时，`PixivClientFacade.call_action()` 因未兼容历史关键字参数而直接抛出 `unexpected keyword argument 'bypass_mode'` 的问题
- `PixivClientFacade` 现会兼容旧的 `bypass_mode` 调用方式，并继续将 `auto` / `accesser` 归一为 `pixez`，避免插件主流程和调试脚本再次因签名回归报错

## [3.0.0] - 2026-04-05

### Added
- 新增 `infrastructure.pixiv_client` 分层 Pixiv 客户端，按本地 `pixez-flutter` 的 OAuth、App API、图片访问与 Web 搜索行为重建插件运行时接入层
- 新增 `domain` 与 `plugin.entry` 结构，为后续继续拆分命令层、存储层和后台任务层提供稳定入口

### Changed
- 插件运行时不再调用 `pixivSDK.py`，`main.py` 现改为通过 `PixivClientFacade` 调度 Pixiv 请求
- `commands.py` 中的图片 URL 选择逻辑已统一切换到新的内建客户端 helper
- 插件版本提升至 `3.0.0`

### Fixed
- 保持 PixEz 风格的 App API、OAuth、图片请求、Web 搜索和 `illust_recommended` 参数行为，并以新的客户端实现补齐测试覆盖

## [2.0.1] - 2026-04-05

### Fixed
- 修复 `illust_recommended` 请求与本地 `pixez-flutter` 的参数不一致问题；现在与 PixEz 一样使用 `filter=for_ios` 与 `include_ranking_label=true`

### Changed
- 新增测试覆盖 `illust_recommended` 的请求参数，防止后续再次偏离本地 PixEz clone

## [2.0.0] - 2026-04-05

### Changed
- 网络层按本地 `pixez-flutter` 实现重新对齐：App API、OAuth 与图片请求默认统一走 PixEz 风格的 DNS 覆盖、禁用 SNI 与跳过证书校验链路
- `pixiv_host_map.json` 继续保留为持久化 host 缓存文件；启动阶段默认优先刷新图片 host，管理员手动刷新时再补刷新全部 PixEz host
- `scripts/test_bypass_modes.py`、手动调试脚本与帮助文档已同步收敛为 `pixez` / `direct` 视角，不再把 `auto`、`accesser` 作为常规模式展示

### Fixed
- 修复插件此前偏离本地 PixEz clone 的网络行为：App API 不再保留 TLS/SNI，而是改回 PixEz 当前真实使用的禁用 SNI + DNS override 语义
- 修复历史 `bypass_mode.json` 中的 `auto` / `accesser` 值会继续影响运行模式的问题；旧值现在会自动迁移为 `pixez`

## [1.12.1] - 2026-04-05

### Changed
- PixEz 模式下的 App API 请求现改为保留域名 URL 与 TLS/SNI，只将 DNS 解析覆盖到候选缓存 IP；图片链路继续维持固定 IP + 禁用 SNI 的直连方式

### Fixed
- 修复 App API 仍沿用“URL 直接改成 IP + 禁用 SNI”旧链路，导致无法对齐 pixez-flutter 近 4 天最新 SNI 绕过策略的问题

## [1.12.0] - 2026-04-02

### Added
- 新增收藏元数据缓存、两天新用户元数据预热，以及 `bookmark_metadata_cache.json`、`metadata_warmup_state.json` 等持久化文件
- 新增 `/pixiv random source` 与 `/pixiv imagehost` 命令，支持 random 的元数据读取层级与通用 HTTP 图床上传配置
- 新增图床上传模块与相关测试，支持按 JSON 路径提取返回图片 URL

### Changed
- `/pixiv random` 现在默认按 本地图片缓存 > 元数据缓存 > 实时随机 的顺序取图，并在任一路径下载前优先复用本地缓存
- 新用户登录成功后会自动创建两天的公开收藏元数据预热窗口，后台分批扫描并写入元数据缓存

### Fixed
- 随机命中仅有元数据但尚未下载图片的作品时，现可即时补图并回填本地图片缓存，不再只能依赖实时随机接口

## [1.11.8] - 2026-04-01

### Fixed
- 修复 `scripts/test_bypass_modes.py` 在 SDK 加载、token 读取或单个 mode/check 抛出异常时会直接退出的问题，改为统一收敛为失败结果并继续输出最终汇总表
## [1.11.7] - 2026-04-01

### Changed
- `scripts/test_bypass_modes.py` 现在会将异常收敛为失败结果并继续后续模式测试，便于直接比较 `pixez` 与 `accesser` 的表现

### Fixed
- 为 PixEz 直连分支补充单候选失败日志，避免测试时只看到 Accesser 分支告警而看不到 PixEz 实际尝试情况
- 修复 `accesser` 模式仍沿用原始 Pixiv 域名发起 TLS 请求的问题，改为真正使用别名域名链路并按别名候选 IP 发起请求
## [1.11.6] - 2026-04-01

### Added
- 新增 `scripts/test_bypass_modes.py`，可按保守节流频率对比 `auto`、`pixez`、`accesser` 与直连模式下的搜索、详情和图片请求表现

## [1.11.5] - 2026-04-01

### Fixed
- 修复 `web_search_illust` 与 `web_search_user` 在未显式提供 token 时仍会先触发 refresh token 请求的问题，Web Ajax 搜索现在可按无鉴权请求直接发起
- 修复图片与 ugoira zip 下载在仅提供资源 URL 时仍会被错误要求先鉴权的问题，避免无必要的 OAuth 请求
- 修复 Pixiv Web Ajax 搜索沿用 App API User-Agent 的问题，改为使用浏览器风格请求头以匹配 Web 接口场景

## [1.11.4] - 2026-04-01

### Fixed
- 补齐作品/作者详情等 App API 请求的 `filter=for_android` 默认参数，保持与 PixEz 请求一致
- Web 搜索兜底仅在作品搜索时传递排序参数，避免作者搜索携带无效排序字段

## [1.11.3] - 2026-03-31

### Changed
- `/pixiv search` 与 `/pixiv searchuser` 现在会为 App API 运行时 DNS 重试启用更保守的连接超时、候选数限制和可重试失败预算，连续超时或 `403` 时会更快转入 Web 搜索或代理兜底

### Fixed
- 修复搜索链路在连续命中超时、连接重置等网络异常时可能长时间串行遍历大量候选 IP，导致一次命令卡住数分钟的问题
- 修复搜索候选快速失败场景下底层 SDK 可能直接抛出网络异常，导致上层无法继续进入 Web 搜索兜底的问题

## [1.11.2] - 2026-03-31

### Fixed
- 修复 `aiocqhttp` 发送 `/pixiv id` 等命中的本地 PNG 缓存图时，仍可能直接沿用原始路径进入 QQ 发送链路并触发超时的问题
- 发送前现在会统一为本地静态 PNG/WebP 等格式生成并复用 JPEG 发送缓存，不再只在超大图片时才做压缩处理

## [1.11.1] - 2026-03-31

### Fixed
- 修复 `accesser` 模式对普通 Pixiv 请求未启用实时 DNS 解析，导致 `/pixiv id`、图片下载和鉴权等请求无法稳定走 Accesser 风格域名覆盖的问题
- 修复 `/pixiv proxy clear` 未清空当日代理救援计数，重新配置代理后可能过早进入粘滞代理窗口的问题

## [1.11.0] - 2026-03-31

### Added
- 新增 `/pixiv bypass` 管理命令，可在 `auto`、`pixez`、`accesser` 三种绕过模式之间切换
- 新增搜索代理配置与状态文件，支持 `/pixiv proxy status/set/clear/enable/threshold/sticky`

### Changed
- 搜索命令现在会在 App API 失败后继续尝试 Pixiv Web Ajax 搜索兜底
- 当同一天内多次触发搜索代理兜底后，插件会自动进入 3 天粘滞代理窗口，后续搜索优先走代理
- `disable_bypass_sni` 继续保留为全局关闭开关，同时新增独立的 bypass mode 选择

## [1.10.11] - 2026-03-31

### Fixed
- 修复 `aiocqhttp` 发送随机收藏等本地缓存静态图时，遇到超大 PNG/JPEG 容易在 QQ 侧上传超时的问题
- 发送前现在会自动为超出安全阈值的静态图生成并复用压缩发送缓存，统一限制尺寸与体积，避免同类大图再次直接进入发送链路

## [1.10.10] - 2026-03-31

### Changed
- Pixiv 直连链路调整为 PixEz 优先模式：插件启动时立即执行 DoH 解析，并在每天凌晨 4 点后台重跑一次
- 请求阶段默认优先使用缓存 IP + 禁用 TLS SNI，只有当前候选失败后才回退到 Accesser 风格的域名解析覆盖

## [1.10.9] - 2026-03-31

### Changed
- Pixiv 直连链路调整为混合模式：优先保留 Accesser 风格的域名解析覆盖，并在同一候选失败后回退到 PixEz 风格的禁用 TLS SNI + 跳过证书校验
- 新增 `disable_bypass_sni` 运行时配置，关闭绕过后会跳过 DoH 刷新并直接走普通域名请求

## [1.10.8] - 2026-03-31

### Fixed
- 修复搜索接口在运行时 DNS 模式下遍历完所有 IP 候选仍返回 `403` 时，会直接把最后一个 `403` 返回给上层而不再尝试原域名直连的问题
- 现在 `search_illust` 与 `search_user` 在 IP 候选全部被拒绝后，会额外补一次原域名请求，降低固定 IP 与别名 IP 全部被风控时的失败概率

## [1.10.7] - 2026-03-31

### Changed
- `/pixiv search` 在作品搜索结果为空时，现在会自动回退到 `search_user`，返回匹配到的作者列表
- 仅当作品搜索没有命中时才触发作者兜底，避免影响已有作品搜索结果展示

## [1.10.6] - 2026-03-31

### Fixed
- 修复 Pixiv 搜索接口参数中的 `include_translated_tag_results` 与 `merge_plain_keyword_results` 仍以 Python 布尔值发送，导致重试后接口返回 `400 invalid value` 的问题
- 搜索请求现在会将上述布尔参数规范化为 Pixiv 接口接受的 `"true"` / `"false"` 字符串

## [1.10.5] - 2026-03-31

### Fixed
- 修复 `/pixiv search` 与 `/pixiv searchuser` 在运行时 DNS 重试时，命中返回 `403` 的旧 IP 后会直接结束而不继续尝试后续候选 IP 的问题
- 现在搜索接口在 IP 直连分支收到 `403` 时会继续尝试动态解析得到的其他候选 IP，降低反复卡在失效或受限固定 IP 上的概率

## [1.10.4] - 2026-03-31

### Changed
- 为图片下载、写入缓存、缓存命中、发送前判定、额外图片发送和动图渲染补充更细粒度日志，便于定位图片链路卡在哪个阶段

## [1.10.3] - 2026-03-31

### Fixed
- `/pixiv search` 与 `/pixiv searchuser` 现在会在 Pixiv 返回 `403` 时强制刷新 DNS，并启用运行时解析后重试，降低搜索接口卡在失效固定 IP 上导致持续失败的概率

## [1.10.2] - 2026-03-31

### Added
- `/pixiv random` 的 `tag`、`author`、`author_id` 支持同一字段内使用 `&` 组合多个正负筛选条件（负筛选支持 `!` / `！`）

### Fixed
- 修复多正负筛选混用时随机缓存匹配不完整的问题，现会正确排除任一负筛选命中项并同时满足全部正筛选项

## [1.10.1] - 2026-03-31

### Added
- `/pixiv random` 筛选参数支持负筛选语法（`!` / `！`），可用于 `tag`、`author`、`author_id`

### Fixed
- 修复随机缓存筛选逻辑未正确排除负筛选条件的问题，避免返回包含被排除标签、作者或作者 ID 的图片

## [1.10.0] - 2026-03-30

### Added
- 新增最近 7 天 random 筛选条件使用统计，会同时记录用户自己使用和其他人通过共享使用其收藏时的筛选偏好

### Changed
- 闲时缓存在用户没有显式缓存队列时，现会优先为该用户预热最近 7 天内使用频率最高的 random 筛选条件
- 新增 `random_usage_stats.json` 持久化文件，用于按天聚合 random 筛选条件使用次数
## [1.9.1] - 2026-03-30

### Fixed
- 调整 `/pixiv id i` 的发送链路，作品详情图片不再受群聊 R-18 显示、自动打码、R-18 标签隐藏和群屏蔽标签限制影响
- 缓存命中的作品详情图片同样改为原样发送，避免 `id` 查询与实时拉取行为不一致

## [1.9.0] - 2026-03-30

### Added
- 新增 R-18 全图模糊打码模式，支持按群聊或私聊用户分别设置 `off`、`hajimi`、`blur` 模式
- 新增 `r18 mosaic strength 1-100` 命令，可为不同群聊或用户分别设置全图模糊强度

### Changed
- 哈基米打码相关依赖改为可选安装，默认安装仅保留基础运行依赖
- `r18` 帮助和状态输出补充打码模式与全图模糊强度说明

### Fixed
- 当哈基米打码依赖缺失或处理失败时，发送链路现在会自动回退到全图模糊，避免直接发送原图

## [1.8.13] - 2026-03-30

### Changed
- `/pixiv config list` 改为从 `constants.py` 自动生成可配置常量列表，减少新增运行时常量后命令侧遗漏同步的问题
- `/pixiv config get/set/reset` 现同时支持命令 key 和原始常量名（如 `idle_cache_interval` 与 `IDLE_CACHE_INTERVAL_SECONDS`）

### Fixed
- 修复部分运行时常量虽可在配置命令中看到但实际未走自定义配置读取的问题
- 收紧常量配置查看权限，`/pixiv config` 相关查看与修改操作均仅允许 AstrBot 管理员执行

## [1.8.12] - 2026-03-29

### Changed
- 哈基米打码分割前会按像素上限自动缩放输入，降低超大图片触发高内存占用的风险

### Fixed
- 打码流程改为逐个掩码回传到 CPU 并即时处理，避免一次性加载全部掩码造成内存峰值过高

## [1.8.11] - 2026-03-29

### Changed
- 重写 `/pixiv help` 帮助菜单，按基础、搜索、随机收藏、常用设置、管理分组展示
- 补充 `dns`、`share`、`quality`、`unique`、`r18` 等子命令的定向用法提示

## [1.8.10] - 2026-03-29

### Changed
- 为 `login`、`id`、`search`、`searchuser`、`random`、`cache`、`groupblock`、`config` 增加更明确的定向用法提示

### Fixed
- 修复子命令后仅输入空格但未提供参数时，仍可能继续走正常命令处理的问题

## [1.8.9] - 2026-03-29

### Added
- `/pixiv random` 现支持为多页作品发送多张图片，随机缓存会同时保存附加页图片路径

### Fixed
- 修复随机收藏命中多页作品时始终只发送首图的问题

## [1.8.8] - 2026-03-29

### Changed
- 抽取 `commands.py` 中作品详情图片结果缓存与多图发送的公共 helper，减少动图、少图、多图三条路径的重复代码

### Fixed
- 统一作品详情缓存写入字段，降低后续调整作品发送路径时遗漏缓存元数据的风险

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
