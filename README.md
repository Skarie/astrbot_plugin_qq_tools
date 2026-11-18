# astrbot_plugin_qq_tools

一个面向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的 **QQ 工具箱**插件，通过 OneBot v11 / aiocqhttp 提供：

- 资料卡点赞
- QQ 官方表情发送（247 个官方表情）
- 拟人自动发表情（机器人回复时按情绪自动补官方表情）
- QQ 空间：说说点赞、评论、发说说
- 空友爱看（QQ 公域推荐流）：浏览、点赞、推、评论、蹲作者、转发

## 功能特性

| 模块 | 说明 |
|---|---|
| 资料卡点赞 | 通过 OneBot `send_like` 给自己/指定 QQ 的资料卡点赞 |
| 官方表情 | 内置 247 个 QQ 官方表情映射（名称 ↔ emojiId），支持按名字或 id 发送 |
| 拟人自动发表情 | 监听回复结果，按回复内容情绪匹配并自动补发一个官方表情（概率/冷却/延迟可调） |
| QQ 空间说说 | 从 OneBot 获取 Cookie（`get_cookies`），调用 qzone_bridge 客户端完成点赞/评论/发布 |
| 空友爱看 | 浏览推荐流 + 点赞/推/评论/关注作者/转发（调用 NapCat 内置 `get_qzone_public_*` / `set_qzone_public_*` 接口） |
| LLM 工具 | 注册多个 function-calling 工具，AI 可自主调用点赞、发表情、空间互动等 |

## 指令一览

指令用正则匹配，**无需**加 `/` 前缀：

| 指令 | 说明 |
|---|---|
| `赞我` | 给自己资料卡点赞 |
| `赞 <QQ号>` | 给指定 QQ 资料卡点赞 |
| `表情 <名称或id>` | 发送官方表情，如 `表情 微笑`、`表情 14` |
| `表情列表 [关键词]` | 查询/搜索官方表情 |
| `说说赞 [QQ号]` | 给（自己/指定人）最新一条说说点赞 |
| `说说评论 <内容>` | 评论自己最新一条说说 |
| `发说说 <内容>` | 发布一条 QQ 空间说说 |
| `爱看` / `空友爱看` | 拉取空友爱看推荐流 |
| `爱看赞 <序号>` | 给第 N 条空友动态点赞 |
| `爱看推 <序号>` | 给第 N 条「推」 |
| `爱看评论 <序号> <内容>` | 评论第 N 条空友动态 |
| `爱看关注 <序号>` | 蹲第 N 条作者 |
| `爱看转发 <序号> [附言]` | 转发第 N 条到自己空间 |
| `爱看能力` | 查询账号的空友爱看接口能力（只读） |
| `帮助` | 显示帮助 |

### LLM 工具

| 工具名 | 作用 |
|---|---|
| `like_profile` | 给 QQ 资料卡点赞 |
| `send_official_face` | 发送官方表情 |
| `qzone_like_latest` | 点赞最新说说 |
| `qzone_comment_latest` | 评论最新说说 |
| `qzone_publish` | 发布说说 |
| `qzone_public_feeds` | 获取空友爱看推荐流 |
| `qzone_public_like` | 点赞空友爱看动态 |
| `qzone_public_comment` | 评论空友爱看动态 |

## 安装

### 方式一：AstrBot 插件市场（推荐）

1. 打开 AstrBot WebUI → **插件** → **插件市场** → 右上角「添加插件源」或「从 URL 安装」
2. 填入本仓库地址：`https://github.com/Skarie/astrbot_plugin_qq_tools`
3. 安装后重启 AstrBot，在插件列表启用本插件

### 方式二：手动安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/Skarie/astrbot_plugin_qq_tools
pip install -r astrbot_plugin_qq_tools/requirements.txt
# 重启 AstrBot
```

重启后日志会输出：

```
[qq_tools] 已加载 | qzone_bridge=OK | 官方表情=247
```

## 依赖

- Python 3.10+
- AstrBot `>=4.16,<5`
- OneBot v11 / aiocqhttp（推荐 NapCat）
- `httpx`、`aiohttp`、`Pillow`（见 `requirements.txt`）
- 使用 QQ 空间功能需机器人端支持 OneBot `get_cookies` / `get_credentials`（NapCat 支持）

## 配置

插件配置在 **AstrBot WebUI → 插件 → QQ 工具箱**：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `enabled` | `true` | 总开关 |
| `allowed_users` | 空 | 允许使用指令的 QQ，逗号分隔；空 = 所有人 |
| `like_times` | `10` | 资料卡点赞默认次数 |
| `qzone_cookie_domain` | `qzone.qq.com` | 获取 Cookie 的域 |
| `auto_emoji_enable` | `true` | 拟人自动发表情开关 |
| `auto_emoji_probability` | `35` | 自动发表情触发概率（%） |
| `auto_emoji_cooldown` | `30` | 同一会话冷却时间（秒） |
| `auto_emoji_delay_min` | `400` | 发表情前最小延迟（毫秒） |
| `auto_emoji_delay_max` | `1600` | 发表情前最大延迟（毫秒） |
| `auto_emoji_in_group` | `true` | 群聊是否自动发表情 |
| `auto_emoji_in_private` | `true` | 私聊是否自动发表情 |

## 兼容性

- 平台：`aiocqhttp`（NapCat / LLOneBot 等 OneBot v11 实现）
- 兼容 AstrBot 4.x（`astrbot_version: >=4.16,<5`），已在 AstrBot 4.x + NapCat 环境验证
- QQ 官方表情映射取自 QQ 客户端内置表情表；QQ 大版本更新后可能需要重新生成 `faces.py`

## 注意事项

1. **QQ 空间功能依赖 Cookie**：插件通过 OneBot `get_cookies` 从机器人账号取 Cookie，约 15 分钟缓存；若失败会自动重取。
2. **频率限制**：QQ 空间接口有风控，请勿高频操作。
3. 本插件会忽略机器人自己发送的消息，避免自触发。

## 致谢

- `qzone_bridge`（QQ 空间协议实现，随插件附带）来自 [diaomin66/astrbot_plugin_qzone_ultra](https://github.com/diaomin66/astrbot_plugin_qzone_ultra)（作者：雪碧bir），本插件仅使用其中的客户端/Cookie/解析等模块，版权归原作者。
- 空友爱看接口能力来自 NapCat 的 `qzone-public` 实现。
- 感谢 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 与 [NapCat](https://github.com/NapNeko/NapCatQQ)。

## 许可

本插件自身代码以 MIT License 发布（见 [LICENSE](LICENSE)）。
`qzone_bridge/` 目录版权归其原作者，遵循原仓库许可，详见 [NOTICE.md](NOTICE.md)。
