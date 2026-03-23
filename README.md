# astrbot-plugin-pixivdirect

PixivDirect 插件，用于直连访问 Pixiv，支持查询作品详情、作者信息和随机获取收藏图片。

## 功能特性

- **用户认证**：通过 refresh_token 绑定 Pixiv 账号
- **作品查询**：根据作品 ID 获取详细信息和预览图
- **作者查询**：根据作者 ID 获取作者信息和作品统计
- **随机收藏**：从个人收藏中随机获取图片，支持多条件筛选
- **智能缓存**：自动缓存图片和 API 响应，提升响应速度
- **空闲缓存**：程序空闲时自动为所有用户预缓存随机图片
- **收藏分享**：支持与其他用户分享收藏内容（可配置）
- **频率限制**：内置请求频率控制，避免 API 限流
- **DNS 优化**：支持 PixEz 风格的 DNS 代理，绕过地区限制

## 安装与配置

### 前置条件

1. 已安装 AstrBot（版本 >= v4.5.0）
2. 拥有 Pixiv 账号并获取 refresh_token

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
根据作品 ID 获取详细信息，包括标题、作者、标签、浏览量、收藏数等。

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

**示例**：
```
# 无筛选随机获取
/pixiv random

# 按标签筛选
/pixiv random tag=风景

# 按作者筛选
/pixiv random author=画师名

# 组合筛选
/pixiv random tag=猫 author_id=1234567 restrict=private max_pages=5
```

**返回信息**：
- 作品 ID 和标题
- 作者名称和 ID
- 页数、浏览量、收藏数
- 标签列表（以 # 前缀显示）
- 匹配数量和扫描页数
- 图片文件

**缓存机制**：
- 优先从缓存中发送图片，提升响应速度
- 缓存为空时再进行新鲜获取
- 程序空闲时自动为所有绑定了的用户预缓存随机图片

#### 6. 查看其他用户的收藏
```
/pixiv random @{用户名称} [筛选条件]
```
查看指定用户的收藏内容（需要先开启分享功能）。

**示例**：
```
/pixiv random @用户名
/pixiv random @用户名 tag=风景
```

#### 7. 开启/关闭收藏分享
```
/pixiv random share true/false
```
控制是否允许其他用户查看自己的收藏内容。

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
   - 缓存管理
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
- **图片缓存**：`{temp_path}/pixivdirect/`
- **缓存索引**：`{temp_path}/pixivdirect/cache_index.json`

### 缓存机制

- **随机收藏缓存**：每次随机请求会预获取多张图片（默认 2 张），后续请求优先使用缓存
- **空闲自动缓存**：程序空闲时自动为所有绑定了的用户预缓存随机图片，默认每 5 分钟执行一次
- **图片缓存**：下载的图片会保存在临时目录，避免重复下载
- **DNS 缓存**：PixEz 的 IP 映射会定期刷新（默认 24 小时）

### 频率限制

- **命令间隔**：同一用户两次命令之间至少间隔 2 秒
- **API 重试**：遇到 429 限流时自动重试，最多 3 次

## 配置选项

插件内置以下配置（位于 `main.py` 顶部）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DNS_REFRESH_INTERVAL_SECONDS` | 86400 (24小时) | DNS 缓存刷新间隔 |
| `DNS_REFRESH_RETRY_SECONDS` | 60 | DNS 刷新失败重试间隔 |
| `RANDOM_DOWNLOAD_CONCURRENCY` | 3 | 随机图片下载并发数 |
| `MIN_COMMAND_INTERVAL_SECONDS` | 2.0 | 用户命令最小间隔 |
| `MAX_RANDOM_PAGES` | 8 | 随机收藏最大扫描页数 |
| `MAX_RANDOM_WARMUP` | 3 | 随机收藏最大预获取数 |
| `IDLE_CACHE_INTERVAL_SECONDS` | 300 (5分钟) | 空闲缓存执行间隔 |
| `IDLE_CACHE_COUNT` | 2 | 空闲时每个用户缓存数量 |
| `DEFAULT_CACHE_SIZE` | 10 | 每个用户默认维护的缓存数量 |

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

### 调试模式

查看 AstrBot 日志获取详细错误信息：

```bash
# 日志文件位置
tail -f {astrbot_data_path}/logs/astrbot.log | grep pixivdirect
```

## 开发信息

- **作者**：Sagiri777
- **版本**：v0.1.0
- **仓库**：https://github.com/Sagiri777/astrbot_plugin_pixivdirect
- **依赖**：requests, astrbot-api

## 更新日志

### v0.2.0
- 新增空闲时自动缓存功能，程序空闲时自动为所有绑定了的用户预缓存随机图片
- 新增收藏分享功能，支持 `/pixiv random @{用户名称}` 查看其他用户的收藏
- 新增 `/pixiv random share true/false` 命令控制分享功能开关
- 优化缓存机制，优先从缓存中发送图片，提升响应速度
- 更新帮助文档和 README

### v0.1.0
- 初始版本
- 支持用户登录、作品查询、作者查询、随机收藏
- 内置缓存和频率限制
- 支持 PixEz DNS 代理

## 相关链接

- [AstrBot 官方仓库](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 插件开发文档（中文）](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot 插件开发文档（English）](https://docs.astrbot.app/en/dev/star/plugin-new.html)
- [Pixiv 官方网站](https://www.pixiv.net)
