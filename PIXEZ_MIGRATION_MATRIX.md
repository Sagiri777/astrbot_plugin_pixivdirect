# PixEz Migration Matrix

本文件只统计 `pixez-flutter` 中“非 UI、但与 Pixiv 能力直接相关”的实现，并对照当前 AstrBot 插件的对齐情况。

状态说明：

- `已对齐`：插件已有等价能力，且已接入当前运行主路径
- `部分对齐`：底层或部分能力存在，但还没有完整达到 PixEz 的能力面或命令暴露
- `未对齐`：PixEz 有该能力，当前插件没有
- `不迁移(UI)`：能力本质依赖界面交互，不在本次迁移范围内

## 参考范围

- `pixez-flutter/lib/network/api_client.dart`
- `pixez-flutter/lib/network/oauth_client.dart`
- `pixez-flutter/lib/network/account_client.dart`
- `pixez-flutter/lib/network/refresh_token_interceptor.dart`
- `pixez-flutter/lib/er/hoster.dart`
- `pixez-flutter/lib/er/fetcher.dart`
- `pixez-flutter/lib/store/save_store.dart`
- `pixez-flutter/lib/store/mute_store.dart`
- `pixez-flutter/lib/store/tag_history_store.dart`
- `pixez-flutter/lib/models/*.dart` 中对应 Pixiv 数据模型

## 迁移矩阵

| 分类 | PixEz 能力 | PixEz 来源 | 当前插件状态 | 差异说明 |
|---|---|---|---|---|
| 认证 | refresh token 换 access token | `network/oauth_client.dart` `postRefreshAuthToken` | 已对齐 | 已在 [`infrastructure/pixiv_client.py`](/Users/guozimier/Downloads/AstrBot/data/plugins/astrbot_plugin_pixivdirect/infrastructure/pixiv_client.py) 实现 |
| 认证 | 用户名密码登录 | `network/oauth_client.dart` `postAuthToken` | 未对齐 | 插件仅支持直接保存 refresh token |
| 认证 | PKCE Web 登录 URL 生成 | `network/oauth_client.dart` `generateWebviewUrl` | 未对齐 | 当前无 WebView 登录流 |
| 认证 | authorization code 换 token | `network/oauth_client.dart` `code2Token` | 未对齐 | 当前未实现 code 登录流程 |
| 认证 | 自动 Bearer 注入 | `network/refresh_token_interceptor.dart` | 部分对齐 | 插件按单次调用即时 refresh，不是 PixEz 的全局 Dio 拦截器 |
| 认证 | OAuth 400 自动刷新并重放请求 | `network/refresh_token_interceptor.dart` | 部分对齐 | 插件在调用前 refresh，但没有对 400 OAuth 失败后二次重放做完整拦截器复刻 |
| 认证 | 连接关闭异常自动重试 | `network/refresh_token_interceptor.dart` | 部分对齐 | 插件传输层有重试，但不是 PixEz 这条 Dio 错误拦截逻辑 |
| 账户 | 临时账号创建 | `network/account_client.dart` `createProvisionalAccount` | 未对齐 | 当前插件无账户创建能力 |
| 账户 | 账户资料编辑 | `network/account_client.dart` `accountEdit` | 未对齐 | 当前插件无账户编辑命令 |
| 网络 | App API 固定 Header 与 `X-Client-*` | `network/api_client.dart` | 已对齐 | 已按 PixEz 风格实现 |
| 网络 | OAuth 固定 Header | `network/oauth_client.dart` | 已对齐 | 已按 PixEz 风格实现 |
| 网络 | 图片 Referer / UA | `er/hoster.dart` `header` | 已对齐 | 已在图片下载逻辑中实现 |
| 网络 | host map 默认 IP | `er/hoster.dart` `_constMap` | 已对齐 | 已实现同源默认 host map |
| 网络 | DoH 刷新 host map | `er/hoster.dart` `dnsQuery*` | 已对齐 | 插件已支持刷新和持久化 host map |
| 网络 | 关闭 SNI / 跳过证书校验访问 Pixiv | `network/*` + `er/hoster.dart` | 已对齐 | 插件传输层已实现 |
| 网络 | 图片下载专用兼容客户端 | `network/api_client.dart` `createCompatibleClient` | 部分对齐 | 插件用 requests 复刻行为，没有保留 Dio/rhttp 结构 |
| 网络 | CacheInterceptor 请求缓存 | `network/api_client.dart` | 未对齐 | 插件当前没有 PixEz 那样的内存请求缓存层 |
| 插画 | 获取推荐插画 | `api_client.dart` `getRecommend` | 已对齐 | 底层 action 与命令层均已接入 |
| 插画 | 获取推荐漫画 | `api_client.dart` `getMangaRecommend` | 部分对齐 | 通过 path 调用已接入命令，尚未收敛为命名 action |
| 插画 | 获取推荐用户 | `api_client.dart` `getUserRecommended` | 部分对齐 | 通过 path 调用已接入命令，返回格式适配仍较轻量 |
| 插画 | 插画详情 | `api_client.dart` `getIllustDetail` | 已对齐 | `/pixiv id i` 已接入 |
| 插画 | 插画相关推荐 | `api_client.dart` `getIllustRelated` | 已对齐 | 已补齐命名 action 与命令入口 |
| 插画 | 插画排行榜 | `api_client.dart` `getIllustRanking` | 部分对齐 | 已接入命令与基本参数，尚未补齐 PixEz 更完整模式/分页语义 |
| 插画 | 点赞/收藏插画 | `api_client.dart` `postLikeIllust` | 未对齐 | 当前只读，不支持收藏写操作 |
| 插画 | 取消收藏插画 | `api_client.dart` `postUnLikeIllust` / `getUnlikeIllust` | 未对齐 | 当前无写操作 |
| 插画 | 收藏详情 | `api_client.dart` `getIllustBookmarkDetail` | 未对齐 | 当前无该 API/action |
| 插画 | 获取插画评论 | `api_client.dart` `getIllustComments` | 未对齐 | 当前无评论能力 |
| 插画 | 获取插画评论回复 | `api_client.dart` `getIllustCommentsReplies` | 未对齐 | 当前无评论能力 |
| 插画 | 发表评论 | `api_client.dart` `postIllustComment` | 未对齐 | 当前无评论能力 |
| 插画 | 趋势标签 | `api_client.dart` `getIllustTrendTags` | 未对齐 | 当前无趋势标签能力 |
| 插画 | 热门预览 | `api_client.dart` `getPopularPreview` | 未对齐 | 当前无 popular preview 能力 |
| 插画 | walkthrough 推荐 | `api_client.dart` `walkthroughIllusts` | 未对齐 | 当前无该能力 |
| 插画 | ugoira 元数据 | `api_client.dart` `getUgoiraMetadata` | 已对齐 | metadata 已接入命令入口 |
| 插画 | ugoira zip 下载 | `er/fetcher.dart` / `api_client.dart` | 部分对齐 | 已具备 zip 下载 + GIF 渲染命令链路，但没有 PixEz 下载队列体系 |
| 插画 | 多页图片质量选择 | `models/illust.dart` extension | 已对齐 | 插件已按 small/medium/original 取图 |
| 用户 | 用户详情 | `api_client.dart` `getUser` | 已对齐 | `/pixiv id a` 已接入 |
| 用户 | 用户作品列表 | `api_client.dart` `getUserIllusts` / `getUserIllustsOffset` | 部分对齐 | 底层 action 存在，但无命令层 |
| 用户 | 用户小说列表 | `api_client.dart` `getUserNovels` | 未对齐 | 插件无小说能力 |
| 用户 | 获取粉丝列表 | `api_client.dart` `getFollowUser` | 未对齐 | 插件无社交列表能力 |
| 用户 | 获取关注列表 | `api_client.dart` `getUserFollowing` | 未对齐 | 插件无社交列表能力 |
| 用户 | 关注用户 | `api_client.dart` `postFollowUser` / `postUserFollowAdd` | 未对齐 | 插件无写操作 |
| 用户 | 取消关注用户 | `api_client.dart` `postUnFollowUser` / `postUnfollowUser` | 未对齐 | 插件无写操作 |
| 用户 | 关注状态详情 | `api_client.dart` `getUserFollowDetail` | 未对齐 | 插件无该能力 |
| 用户 | AI 展示设置读取 | `api_client.dart` `getUserAISettings` | 未对齐 | 插件无该能力 |
| 用户 | AI 展示设置修改 | `api_client.dart` `postUserAIShowSettings` | 未对齐 | 插件无该能力 |
| 用户 | restricted mode 读取 | `api_client.dart` `userRestrictedModeSettingsGet` | 未对齐 | 插件无该能力 |
| 用户 | restricted mode 修改 | `api_client.dart` `userRestrictedModeSettings` | 未对齐 | 插件无该能力 |
| 搜索 | 搜索插画 | `api_client.dart` `getSearchIllust` | 已对齐 | `/pixiv search` 已接入基本参数 |
| 搜索 | 搜索用户 | `api_client.dart` `getSearchUser` | 已对齐 | `/pixiv searchuser` 已接入 |
| 搜索 | 搜索小说 | `api_client.dart` `getSearchNovel` | 未对齐 | 插件无小说搜索 |
| 搜索 | 搜索自动补全 | `api_client.dart` `getSearchAutoCompleteKeywords` / `getSearchAutocomplete` | 未对齐 | 插件无自动补全能力 |
| 搜索 | 插画搜索高级参数：日期区间 | `api_client.dart` `getSearchIllust` | 部分对齐 | 当前只支持 `sort`/`target`，未暴露 `start_date`/`end_date` |
| 搜索 | 插画搜索高级参数：bookmark 区间 | `api_client.dart` `getSearchIllust` | 未对齐 | 当前无 `bookmark_num_min/max` |
| 搜索 | 插画搜索高级参数：AI 类型 | `api_client.dart` `getSearchIllust` | 未对齐 | 当前无 `search_ai_type` |
| 搜索 | Web 搜索兜底 | PixEz Web/Ajax 侧行为 + 本仓库移植层 | 已对齐 | 当前插件已实现 `web_search_illust` / `web_search_user` |
| 收藏 | 获取插画收藏列表 | `api_client.dart` `getBookmarksIllust` / `getBookmarksIllustsOffset` | 已对齐 | 当前随机收藏和 metadata 预留链路都依赖该接口 |
| 收藏 | 获取插画收藏标签 | `api_client.dart` `getUserBookmarkTagsIllust` | 未对齐 | 当前插件无收藏标签列表命令 |
| 收藏 | 获取小说收藏列表 | `api_client.dart` `getUserBookmarkNovel` | 未对齐 | 插件无小说能力 |
| 收藏 | 添加小说收藏 | `api_client.dart` `postNovelBookmarkAdd` | 未对齐 | 插件无小说能力 |
| 收藏 | 取消小说收藏 | `api_client.dart` `postNovelBookmarkDelete` | 未对齐 | 插件无小说能力 |
| 收藏 | 随机收藏抽样 | PixEz 无直接现成命令，插件扩展 | 部分对齐 | 这是插件侧新增能力，不是 PixEz 原生一等能力 |
| 关注流 | 获取关注作品流 | `api_client.dart` `getFollowIllusts` | 未对齐 | 插件无 follow timeline |
| 系列 | 插画系列详情 | `api_client.dart` `illustSeries` | 未对齐 | 插件无系列 API/action |
| 系列 | 通过插画取系列作品 | `api_client.dart` `illustSeriesIllust` | 未对齐 | 插件无该能力 |
| 系列 | 小说系列详情 | `api_client.dart` `novelSeries` / `nextNovelSeries` | 未对齐 | 插件无小说能力 |
| Watchlist | 小说 watchlist 列表 | `api_client.dart` `watchListNovel` | 未对齐 | 插件无该能力 |
| Watchlist | 小说 watchlist 增删 | `api_client.dart` `watchListNovelAdd/Delete` | 未对齐 | 插件无该能力 |
| Watchlist | 漫画 watchlist 列表 | `api_client.dart` `watchListManga` | 未对齐 | 插件无该能力 |
| Watchlist | 漫画 watchlist 增删 | `api_client.dart` `watchListMangaAdd/Delete` | 未对齐 | 插件无该能力 |
| Novel | 小说详情 | `api_client.dart` `getNovelDetail` | 未对齐 | 插件无小说能力 |
| Novel | 小说正文 | `api_client.dart` `getNovelText` | 未对齐 | 插件无小说能力 |
| Novel | 小说 webview 数据 | `api_client.dart` `webviewNovel` | 未对齐 | 插件无小说能力 |
| Novel | 小说排行榜 | `api_client.dart` `getNovelRanking` | 未对齐 | 插件无小说能力 |
| Novel | 小说推荐 | `api_client.dart` `getNovelRecommended` | 未对齐 | 插件无小说能力 |
| Novel | 关注小说流 | `api_client.dart` `getNovelFollow` | 未对齐 | 插件无小说能力 |
| Novel | 小说评论/回复/发评 | `api_client.dart` `getNovelComments*` / `postNovelComment` | 未对齐 | 插件无小说能力 |
| 下载 | 图片保存到本地/图库 | `er/fetcher.dart` + `store/save_store.dart` | 部分对齐 | 插件支持下载到缓存目录，不支持 PixEz 的任务队列/图库保存体系 |
| 下载 | 并发下载队列 | `er/fetcher.dart` | 未对齐 | 当前插件是简单顺序下载 |
| 下载 | 下载进度持久化任务 | `er/fetcher.dart` + `models/task_persist.dart` | 未对齐 | 插件无任务数据库 |
| 下载 | 命名模板/保存路径策略 | `store/save_store.dart` | 未对齐 | 插件无 PixEz 级命名模板体系 |
| 缓存 | 图片 URL 质量缓存 | `er/illust_cacher.dart` | 未对齐 | 插件只缓存下载索引 |
| 持久化 | 多账号数据库 | `models/account.dart` | 未对齐 | 插件只存每个 AstrBot 用户的 refresh token |
| 持久化 | tag history 导入导出 | `store/tag_history_store.dart` | 未对齐 | 插件无 tag history |
| 持久化 | mute/ban 用户、标签、评论 | `store/mute_store.dart` + `models/ban_*` | 未对齐 | 当前插件已移除旧群屏蔽逻辑，未复刻 PixEz mute store |
| 领域模型 | Illust/User/UserPreview/Ugoira/Series/Follow 等模型 | `models/*.dart` | 部分对齐 | 插件目前主要直接消费 dict，只建立了少量 Python dataclass |

## 当前结论

### 已对齐的核心能力

- PixEz 风格认证基础链路：refresh token -> access token
- PixEz 风格 App API 请求头
- PixEz 风格 OAuth 请求头
- PixEz 风格 host map / DNS override / 关闭 SNI / 图片 Referer
- 插画详情
- 用户详情
- 插画搜索
- 用户搜索
- Web 搜索兜底
- 收藏列表驱动的随机抽样
- 图片质量选择与图片下载

### 部分对齐但还需要继续补的高优先级

- OAuth 拦截器式自动重放
- 推荐漫画/推荐用户的命名 action 收敛与返回模型细化
- 插画排行榜的更完整 PixEz 语义、用户作品列表、收藏标签列表、热门预览、趋势标签
- 下载任务/队列体系与领域模型的系统化收敛

### 当前完全未对齐的大片能力

- 小说全系能力
- 评论全系能力
- 关注/粉丝/关注流
- watchlist / series
- 账户创建与编辑
- 下载任务队列、图库保存、命名模板
- 多账号数据库和 mute/tag history 等本地数据体系

## 建议的下一阶段补齐顺序

1. 用户域补齐：`user_illusts`、`follow_detail`、`follow add/delete`
2. 搜索域补齐：autocomplete、popular preview、趋势标签
3. 收藏域补齐：bookmark detail、bookmark tags、bookmark add/delete
4. 系列与 watchlist
5. 小说域
6. 评论域
7. 账户编辑与本地持久化体系
