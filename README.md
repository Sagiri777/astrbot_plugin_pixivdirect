# astrbot-plugin-pixivdirect

PixivDirect 插件，用于直连访问 Pixiv，支持查询作品详情、作者信息和随机获取收藏图片。

当前版本：`v1.11.5`

## 更新日志

README 中仅保留最近 5 条版本摘要（超出 5 条时需删除最旧记录），完整历史请见 [CHANGELOG.md](./CHANGELOG.md)。

### v1.11.5

- 修复 Pixiv Web 搜索兜底仍会先强制 refresh token 的问题，未携带 token 时也可直接发起 Web Ajax 搜索
- 修复图片与 ugoira zip 下载被错误要求先鉴权的问题，并将 Web 搜索请求头切换为浏览器风格

### v1.11.4

- 补齐作品/作者详情等 App API 请求的 `filter=for_android` 默认参数，与 PixEz 请求保持一致
- Web 搜索兜底仅在作品搜索时附带排序参数，避免作者搜索携带无效排序字段

### v1.11.3

- 修复 `/pixiv search` / `/pixiv searchuser` 在连续超时、`403`、连接重置时可能长时间遍历大量候选 IP，导致单次查询卡住数分钟的问题
- 搜索恢复链路现在会限制运行时 DNS 候选与可重试失败预算，更快降级到 Web 搜索或代理兜底

### v1.11.2

- 修复 `aiocqhttp` 发送 `/pixiv id` 等命中的本地 PNG 缓存图时，因未进入发送缓存压缩流程而仍可能在 QQ 侧超时的问题
- `aiocqhttp` 现在会将本地静态 PNG/WebP 等格式统一转换为更稳妥的 JPEG 发送缓存，减少缓存命中场景下的图片发送失败

### v1.11.1

- 修复 `accesser` 模式对普通请求未启用实时 DNS 解析，导致大多数非搜索请求仍退回普通域名链路的问题
- 修复 `/pixiv proxy clear` 未清空当日代理救援计数，重新配置代理后可能提前进入粘滞代理窗口的问题

## 功能特性

- **用户认证**：通过 refresh_token 绑定 Pixiv 账号
- **作品查询**：根据作品 ID 获取详细信息和预览图
- **作者查询**：根据作者 ID 获取作者信息和作品统计
- **随机收藏**：从个人收藏中随机获取图片，支持多条件筛选
- **智能缓存**：统一缓存池 + 元数据筛选，精准快速匹配
- **空闲缓存**：程序空闲时自动为所有用户预缓存随机图片，并优先预热最近 7 天最高频的 random 筛选条件
- **收藏分享**：支持与其他用户分享收藏内容（可配置）
- **R-18 管理**：支持配置群聊 R-18 图片显示、标签显示、打码模式与全图模糊强度
- **频率限制**：内置请求频率控制，避免 API 限流
- **搜索恢复**：`/pixiv search` / `/pixiv searchuser` 支持 App API 快速失败、Pixiv Web 搜索兜底和代理兜底
- **绕过模式切换**：支持 `auto`、`pixez`、`accesser` 三种绕过模式，并兼容 `disable_bypass_sni`
- **DNS 优化**：支持 PixEz 优先的 DoH + 缓存 IP + 禁用 SNI 直连模式，并可按配置关闭
- **QQ 发送优化**：`aiocqhttp` 发送前会自动为本地静态图生成更稳妥的发送缓存，优先规避 PNG/WebP 等格式和超大图片带来的上传超时问题
- **动图支持**：PIL 渲染失败时自动回退 ffmpeg
- **多图支持**：多图片作品自动合并转发发送
- **图片质量设置**：可按用户/群组设置图片质量（原图/中等/小图）
- **唯一随机优化**：记录已发送图片ID，避免重复发送
- **彻底随机**：支持彻底随机模式，从所有符合条件的图片中随机选择
- **使用统计预热**：自动统计 random 常用筛选条件，为闲时缓存提供个性化预热依据

## 安装与配置

### 前置条件

1. 已安装 AstrBot（版本 >= v4.5.0）
2. 拥有 Pixiv 账号并获取 refresh_token
3. （可选）安装 ffmpeg 以支持动图渲染
4. 使用全图模糊模式只需默认依赖
5. 若要启用哈基米打码模式，需额外安装 `ultralytics`、`opencv-python`、`numpy`

### 获取 refresh_token

1. **方法一**：使用 Pixiv 第三方客户端（如 PixEz）获取
2. **方法二**：通过 OAuth 流程手动获取（需要抓包）

### 安装插件

将插件文件夹放置在 AstrBot 的 `data/plugins/` 目录下：

```
data/plugins/
└── astrbot_plugin_pixivdirect/
    ├── main.py
    ├── pixivSDK.py
    ├── metadata.yaml
    └── ...
```

## 使用指南

### 基本命令

所有命令均以 `/pixiv` 开头：

#### 1. 查看帮助
```
/pixiv help
```
显示所有可用命令和使用说明。

#### 2. 用户登录
```
/pixiv login {refresh_token}
```
绑定 Pixiv 账号。refresh_token 会与当前用户 ID 关联存储。

**示例**：
```
/pixiv login 0zeH-pYcDB***RE***cUQ
```

#### 3. 查询作品详情
```
/pixiv id i {illust_id}
```
根据作品 ID 获取详细信息，包括标题、作者、标签、浏览量、收藏数等。获取的图片会自动加入随机缓存池。如果该作品已在缓存中，则直接从缓存发送，避免重复请求。

**示例**：
```
/pixiv id i 12345678
```

**返回信息**：
- 作品 ID 和标题
- 作者名称和 ID
- 页数、浏览量、收藏数
- 发布时间
- 标签列表（以 # 前缀显示）
- 预览图（如果可用）

**多图片作品处理**：
- 图片数量 <= 3：直接下载并依次发送所有图片
- 图片数量 > 3：使用合并转发消息发送

#### 4. 查询作者详情
```
/pixiv id a {artist_id}
```
根据作者 ID 获取作者信息和作品统计。

**示例**：
```
/pixiv id a 1234567
```

**返回信息**：
- 作者 ID、名称、账号
- 插画数、漫画数
- 关注者数量
- 个人主页链接

#### 5. 随机收藏图片
```
/pixiv random [筛选条件]
```
从个人收藏中随机获取一张图片。

**筛选条件**（可选）：

| 参数 | 缩写 | 说明 | 示例 |
|------|------|------|------|
| `tag` | `t` | 按标签筛选 | `tag=风景` |
| `author` | `a` | 按作者名称筛选 | `author=画师名` |
| `author_id` | `aid` | 按作者 ID 筛选 | `author_id=1234567` |
| `restrict` | `r` | 收藏可见性 | `restrict=public` 或 `restrict=private` |
| `max_pages` | `pages` | 最大扫描页数（1-8） | `max_pages=5` |
| `warmup` | - | 预获取数量（1-3） | `warmup=2` |
| `random` | - | 彻底随机模式 | `random=true` |

> `tag` / `author` / `author_id` 支持多条件写法：使用 `&` 连接多个条件，负筛选前缀可用 `!` 或 `！`。

**示例**：
```
# 无筛选随机获取
/pixiv random

# 按标签筛选
/pixiv random tag=风景

# 按作者筛选
/pixiv random author=画师名

# 多条件 + 负筛选（支持半角 ! / 全角 ！）
/pixiv random tag=风景&!R-18&！R-18G
/pixiv random author=画师A&!画师B
/pixiv random author_id=1234567&!7654321

# 彻底随机（从所有收藏中随机选择）
/pixiv random random=true

# 组合筛选
/pixiv random tag=猫&!涩图 author=画师A&！画师B author_id=1234567&!7654321 restrict=private max_pages=5
```

**返回信息**：
- 作品 ID 和标题
- 作者名称和 ID
- 页数、浏览量、收藏数
- 标签列表（以 # 前缀显示）
- R-18 标识（如适用）
- 剩余缓存数量和筛选条件
- 图片文件

#### 6. 查看其他用户的收藏
```
/pixiv random @{用户名称} [筛选条件]
```
查看指定用户的收藏内容（需要先开启分享功能）。查看他人收藏不需要当前用户绑定 token。

**示例**：
```
/pixiv random @用户名
/pixiv random @用户名 tag=风景
/pixiv random @用户名 author=画师名
```

#### 7. 开启/关闭收藏分享
```
/pixiv random share true/false
```
控制是否允许其他用户查看自己的收藏内容。此命令不需要绑定 token。

**示例**：
```
# 开启分享
/pixiv random share true

# 关闭分享
/pixiv random share false

# 查看当前状态
/pixiv random share
```

**注意**：分享功能默认关闭，需要手动开启后其他用户才能查看你的收藏。

#### 8. 群聊 R-18 内容显示设置（仅管理员）
```
/pixiv random r18 true/false
/pixiv random r18 tag true/false
/pixiv random r18 mosaic true/false
/pixiv random r18 mosaic mode off/hajimi/blur
/pixiv random r18 mosaic strength 1-100
```
控制群聊中 R-18 图片是否发送、标签是否显示，以及发送时采用哪种打码模式。群聊中仅 AstrBot 管理员可修改；私聊中可为当前用户单独设置打码模式和模糊强度，不需要绑定 token。

- **关闭时（默认）**：群聊中 `/pixiv random` 命中 R-18 图片时，仅发送作品说明文字，不发送图片
- **开启时**：群聊中 `/pixiv random` 命中 R-18 图片时，会发送图片
- **标签显示**：默认显示，可单独关闭后隐藏 R-18 图片消息中的 `🏷️` 标签行
- **自动打码**：默认关闭，开启后可选择 `hajimi` 或 `blur`
- **哈基米打码**：使用内置的 [AutoHajimiMosaic](https://github.com/frinkleko/AutoHajimiMosaic) 逻辑，若依赖未安装会自动回退到全图模糊
- **全图模糊**：对整张图应用高斯模糊，支持 `1-100` 的强度设置
- **私聊中**：无论此设置如何，R-18 图片均正常发送

**群聊 `/pixiv random` 实际行为**：
- `r18=false`：发送作品说明文字，并附带 “R-18 内容在群聊中仅显示信息”，不发送图片
- `r18=true` 且 `mosaic=false`：发送作品说明文字 + 原图
- `r18=true` 且 `mosaic=true`：发送作品说明文字 + 自动打码后的图片
- `r18 tag=false`：无论发送原图还是打码图，都会隐藏消息中的 `🏷️` 标签行
- `r18 tag=true`：标签正常显示

**示例**：
```
# 开启群聊 R-18 显示
/pixiv random r18 true

# 关闭群聊 R-18 显示（默认）
/pixiv random r18 false

# 查看当前状态
/pixiv random r18

# 隐藏群聊 R-18 标签
/pixiv random r18 tag false

# 开启群聊 R-18 自动打码
/pixiv random r18 mosaic true

# 设置群聊使用全图模糊模式
/pixiv random r18 mosaic mode blur

# 设置群聊全图模糊强度为 30
/pixiv random r18 mosaic strength 30

# 私聊中仅为自己设置哈基米打码
/pixiv random r18 mosaic mode hajimi
```

**注意**：通过 `/pixiv id i {illust_id}` 指定获取的图片不受此限制影响。

#### 9. 图片质量设置（仅管理员）
```
/pixiv random quality original/medium/small
```
设置图片发送质量。按实体（用户或群组）独立设置。

- `original`：原图（默认）
- `medium`：中等质量
- `small`：小图（缩略图）

**示例**：
```
# 设置当前群聊为中等质量
/pixiv random quality medium

# 查看当前设置
/pixiv random quality
```

#### 10. 闲时缓存管理
```
/pixiv random cache add tag=xxx count=N|always
/pixiv random cache list
/pixiv random cache clear
/pixiv random cache now N
```
管理闲时缓存队列。可以指定筛选条件和缓存次数。

**示例**：
```
# 在之后的 5 次闲时缓存中缓存 tag=风景 的图片
/pixiv random cache add tag=风景 count=5

# 始终缓存特定作者的图片
/pixiv random cache add author=画师名 count=always

# 查看当前队列
/pixiv random cache list

# 清空队列
/pixiv random cache clear

# 立即缓存 3 张图片
/pixiv random cache now 3
```

**关于 count=always 的说明**：
- 当有多个 `count=always` 的任务时，按添加顺序轮流执行
- 每次闲时缓存只处理队列中的第一个任务
- 如果第一个任务是 `count=always`，则不会被移除，会持续参与后续缓存

#### 11. 唯一随机模式（仅管理员）
```
/pixiv random unique true/false
```
控制图片发送后是否从缓存池中移除。

- **关闭时（默认）**：图片发送后保留在缓存池中，可再次被随机到
- **开启时**：图片发送后从缓存池中移除，不会再次被随机到。同时会记录已发送的图片ID，新缓存时会避开这些ID

**唯一模式优化说明**：
- 开启唯一模式后，系统会记录每个用户已发送的图片ID
- 缓存新图片时，会自动避开已发送的ID
- 当前3页没有未发送过的图片时，会自动扩展扫描范围（最多9页）
- 支持 `random=true` 参数实现彻底随机

**示例**：
```
# 开启唯一随机模式
/pixiv random unique true

# 关闭唯一随机模式
/pixiv random unique false

# 查看当前状态
/pixiv random unique
```

#### 12. 群聊屏蔽标签（仅管理员）
```
/pixiv groupblock add/remove tag=xxx
/pixiv groupblock list
/pixiv groupblock clear
```
为当前群聊设置屏蔽的标签。包含被屏蔽标签的图片将不会在该群中发送。

**示例**：
```
# 添加屏蔽标签
/pixiv groupblock add R-18

# 移除屏蔽标签
/pixiv groupblock remove R-18

# 查看屏蔽列表
/pixiv groupblock list

# 清空屏蔽列表
/pixiv groupblock clear
```

#### 13. DNS 刷新管理
```
/pixiv dns
/pixiv dns refresh  # 仅管理员
```
查看 DNS 刷新状态或手动触发刷新。默认启用 PixEz 优先模式：插件启动时立即执行 DoH 解析，并在每天凌晨 4 点重跑一次；后续请求优先使用缓存 IP + 禁用 SNI 的 TLS 设置，若该候选失败再回退到 Accesser 风格覆盖。若设置 `disable_bypass_sni=true`，则会跳过 DoH 刷新并直接使用普通域名请求。

**示例**：
```
# 查看下次刷新时间
/pixiv dns

# 手动触发刷新（仅管理员）
/pixiv dns refresh
```

可通过运行时配置切换是否启用 SNI 绕过：

```text
/pixiv config get disable_bypass_sni
/pixiv config set disable_bypass_sni true
/pixiv config set disable_bypass_sni false
```

#### 14. 绕过模式切换（仅管理员）
```text
/pixiv bypass
/pixiv bypass mode auto
/pixiv bypass mode pixez
/pixiv bypass mode accesser
```

- `auto`：默认模式，先走 PixEz 式直连，再回退到 Accesser 式域名覆盖。
- `pixez`：只走缓存 IP + 禁用 SNI 的直连链路。
- `accesser`：只走 Accesser 式域名覆盖，不走 PixEz 直连。
- 若 `disable_bypass_sni=true`，则无论当前模式为何，都会直接走普通域名请求。

#### 15. 搜索代理管理（仅管理员）
```text
/pixiv proxy status
/pixiv proxy set http://127.0.0.1:7890
/pixiv proxy clear
/pixiv proxy enable true
/pixiv proxy threshold 3
/pixiv proxy sticky 3
```

- 搜索命令会先走 App API 与 Web 搜索兜底。
- 当同一天内多次走到代理兜底步骤时，插件会自动进入粘滞代理窗口，后续 3 天优先使用代理搜索。
- 代理兜底仅作用于 `/pixiv search` 和 `/pixiv searchuser`，不会影响随机收藏、图片下载和作品详情。

#### 16. 配置管理（仅管理员）
```
/pixiv config list
/pixiv config get <key>
/pixiv config set <key> <value>
/pixiv config reset [key]
```
管理插件内部常量配置。

`/pixiv config list` 会根据 `constants.py` 中当前支持运行时覆盖的常量自动生成列表，是当前版本最准确的可配置项来源。

`get/set/reset` 同时支持命令 key 和原始常量名，例如：

```text
/pixiv config get idle_cache_interval
/pixiv config get IDLE_CACHE_INTERVAL_SECONDS
/pixiv config set random_download_concurrency 5
```

**示例**：
```
# 查看所有配置
/pixiv config list

# 获取配置值
/pixiv config get idle_cache_count

# 设置配置值
/pixiv config set idle_cache_count 10

# 重置单个配置
/pixiv config reset idle_cache_count

# 重置所有配置
/pixiv config reset
```

### 命令格式说明

支持两种命令格式：

1. **标准格式**：`/pixiv {子命令} {参数...}`
   ```
   /pixiv login 0zeH-pYcDB***RE***cUQ
   /pixiv id i 12345678
   /pixiv random tag=风景
   ```

2. **空格分隔格式**：`pixiv {子命令} {参数...}`
   ```
   pixiv login 0zeH-pYcDB***RE***cUQ
   pixiv id i 12345678
   pixiv random tag=风景
   ```

## 技术架构

### 核心组件

1. **main.py**：插件主逻辑
   - 命令解析与路由
   - 用户 Token 管理
   - 统一缓存池管理
   - R-18 内容过滤
   - 频率限制

2. **pixivSDK.py**：Pixiv API 封装
   - OAuth 认证流程
   - API 请求封装
   - 图片下载
   - DNS 代理支持

### 数据存储

插件数据存储在以下位置：

- **用户 Token**：`{plugin_data_path}/pixivdirect/user_refresh_tokens.json`
- **DNS 缓存**：`{plugin_data_path}/pixivdirect/pixiv_host_map.json`
- **分享配置**：`{plugin_data_path}/pixivdirect/share_config.json`
- **R-18 配置**：`{plugin_data_path}/pixivdirect/r18_config.json`
- **R-18 标签配置**：`{plugin_data_path}/pixivdirect/r18_tag_config.json`
- **R-18 打码配置**：`{plugin_data_path}/pixivdirect/r18_mosaic_config.json`
- **闲时缓存队列**：`{plugin_data_path}/pixivdirect/idle_cache_queue.json`
- **唯一随机配置**：`{plugin_data_path}/pixivdirect/unique_config.json`
- **群聊屏蔽标签**：`{plugin_data_path}/pixivdirect/group_blocked_tags.json`
- **已发送图片ID**：`{plugin_data_path}/pixivdirect/sent_illust_ids.json`
- **图片质量配置**：`{plugin_data_path}/pixivdirect/image_quality_config.json`
- **random 使用统计**：`{plugin_data_path}/pixivdirect/random_usage_stats.json`
- **自定义常量**：`{plugin_data_path}/pixivdirect/custom_constants.json`
- **图片缓存**：`{plugin_data_path}/pixivdirect/cache/`（持久化存储，用户可在此目录下管理缓存图片）
- **缓存索引**：`{plugin_data_path}/pixivdirect/cache/cache_index.json`

### 缓存机制

- **统一缓存池**：所有缓存图片存储在统一池中，不再按筛选条件分桶
- **元数据筛选**：缓存时记录 `x_restrict`、`tags`、`author_id`、`author_name` 等元数据，筛选时从池中按元数据精准匹配
- **跨条件复用**：同一张图片可被不同筛选条件复用（如先缓存的图片可在后续 `tag=xxx` 请求中被匹配）
- **自动入池**：通过 `/pixiv id i` 获取的图片自动加入随机缓存池
- **空闲自动缓存**：程序空闲时自动为所有绑定了的用户预缓存随机图片，默认每 15 分钟执行一次
- **缓存数量显示**：随机发送时显示当前筛选条件在缓存中剩余的数量
- **图片缓存**：下载的图片会保存在持久化目录 `{plugin_data_path}/pixivdirect/cache/`，用户可自行管理（删除不需要的图片）
- **DNS 缓存**：PixEz 的 IP 映射会在每天凌晨 4 点自动刷新，管理员也可手动触发刷新

### R-18 过滤逻辑

| 场景 | R-18 行为 |
|------|-----------|
| 私聊随机 | 正常发送图片 |
| 群聊随机（r18=false） | 仅发送说明文字，不发图片 |
| 群聊随机（r18=true, mosaic=false） | 发送说明文字 + 原图 |
| 群聊随机（r18=true, mosaic=true） | 发送说明文字 + 自动打码图 |
| `/pixiv id i` 指定获取 | 始终发送图片 |

判断依据：`x_restrict >= 1` 或标签包含 `R-18`/`R18`/`R-18G`。当群聊内关闭 R-18 标签显示时，会隐藏消息中的标签行，但保留标题、作者、作品 ID、来源和警告等其他说明文字。

### 动图渲染

动图（ugoira）采用两级渲染策略：
1. **PIL 优先**：使用 Pillow 逐帧合成 GIF
2. **ffmpeg 回退**：PIL 失败时自动尝试 ffmpeg 渲染

### 频率限制

- **命令间隔**：同一用户两次命令之间至少间隔 2 秒
- **API 重试**：遇到 429 限流时自动重试，最多 3 次

## 配置选项

插件内置以下配置（位于 `constants.py`）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DNS_REFRESH_INTERVAL_SECONDS` | 86400 (24小时) | DNS 缓存刷新间隔 |
| `DNS_REFRESH_RETRY_SECONDS` | 60 | DNS 刷新失败重试间隔 |
| `RANDOM_DOWNLOAD_CONCURRENCY` | 3 | 随机图片下载并发数 |
| `MIN_COMMAND_INTERVAL_SECONDS` | 2.0 | 用户命令最小间隔 |
| `MAX_RANDOM_PAGES` | 8 | 随机收藏最大扫描页数 |
| `MAX_RANDOM_WARMUP` | 3 | 随机收藏最大预获取数 |
| `IDLE_CACHE_INTERVAL_SECONDS` | 900 (15分钟) | 空闲缓存执行间隔 |
| `IDLE_CACHE_COUNT` | 5 | 空闲时每个用户缓存数量 |
| `DEFAULT_CACHE_SIZE` | 10 | 每个用户默认维护的缓存数量 |
| `MAX_UNIQUE_SCAN_PAGES` | 9 | 唯一模式最大扫描页数 |
| `MULTI_IMAGE_THRESHOLD` | 3 | 多图片使用合并转发的阈值 |

## 合规声明

本插件仅供个人学习和研究使用，请遵守以下规定：

1. **仅限个人使用**：仅可用于账号本人授权访问与个人查看
2. **禁止批量抓取**：不得用于大规模数据采集
3. **禁止商用转载**：不得将获取的内容用于商业用途
4. **遵守 Pixiv 规则**：不得绕过 Pixiv 的正常使用限制

## 故障排除

### 常见问题

#### 1. Token 校验失败
- **原因**：refresh_token 无效或已过期
- **解决**：重新获取 refresh_token 并登录

#### 2. 请求频繁被限流
- **原因**：短时间内发送过多请求
- **解决**：等待一段时间后重试，或减少请求频率

#### 3. 图片下载失败
- **原因**：网络连接问题或图片已被删除
- **解决**：检查网络连接，或尝试其他作品 ID

#### 4. DNS 解析失败
- **原因**：无法连接到 Pixiv 服务器
- **解决**：检查网络代理设置，或等待 DNS 缓存自动刷新

#### 5. 动图渲染失败
- **原因**：PIL 和 ffmpeg 均无法渲染
- **解决**：确保已安装 ffmpeg（`ffmpeg -version` 检查），或尝试其他动图

### 调试模式

查看 AstrBot 日志获取详细错误信息：

```bash
# 日志文件位置
tail -f {astrbot_data_path}/logs/astrbot.log | grep pixivdirect
```

## 开发信息

- **作者**：Sagiri777
- **版本**：v1.10.2
- **仓库**：https://github.com/Sagiri777/astrbot_plugin_pixivdirect
- **依赖**：requests, astrbot-api, Pillow


## 相关链接

- [AstrBot 官方仓库](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 插件开发文档（中文）](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot 插件开发文档（English）](https://docs.astrbot.app/en/dev/star/plugin-new.html)
- [Pixiv 官方网站](https://www.pixiv.net)
