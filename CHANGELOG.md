# 更新日志

## v1.0.0 (2026-11-19)

首个公开版本。

### 新增
- 资料卡点赞：`赞我` / `赞 <QQ号>`（OneBot `send_like`）
- 官方表情：`表情 <名称|id>` / `表情列表`，内置 247 个 QQ 官方表情映射
- 拟人自动发表情：回复时按情绪自动补官方表情（概率/冷却/延迟/群私聊开关可配）
- QQ 空间：`说说赞` / `说说评论` / `发说说`（通过 OneBot `get_cookies` + qzone_bridge 客户端）
- 空友爱看：`爱看` / `爱看赞` / `爱看推` / `爱看评论` / `爱看关注` / `爱看转发` / `爱看能力`
- LLM 工具 8 个：`like_profile`、`send_official_face`、`qzone_like_latest`、`qzone_comment_latest`、`qzone_publish`、`qzone_public_feeds`、`qzone_public_like`、`qzone_public_comment`
- 启动时自动探测空友爱看接口能力（只读，便于排查账号灰度）

### 说明
- 空友爱看命令支持「空友爱看」与「爱看」两种前缀
- 「投稿至空友爱看」为 QQ 手机客户端私有加密协议，插件不支持自动投稿；`发说说` 后需手动在手机 QQ 空间投稿（每天 3 次）
- 依赖随插件附带的 `qzone_bridge`（来自 astrbot_plugin_qzone_ultra，版权归原作者）
