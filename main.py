# -*- coding: utf-8 -*-
"""QQ 工具箱（AstrBot 插件）

功能：
1. 资料卡点赞：赞我 / 赞 <QQ号>（OneBot action send_like）
2. 官方表情：表情 <名称|id>、表情列表 [关键词]（247 个官方表情名）
3. 自动发表情（拟人）：机器人每次文字回复后按概率补一个官方表情（情绪关键词匹配 + 随机延迟 + 会话冷却）
4. QQ空间：说说赞 / 说说评论 / 发说说（自动从 OneBot 取 Cookie，复用 qzone_bridge 客户端）

依赖：AstrBot >= 4.16（Face 组件 / filter.regex / on_decorating_result / register_web_api 均已在 4.28.2 验证）
      qzone_bridge 包（随插件附带，来自 astrbot_plugin_qzone_ultra，协议实现由原作者提供）
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Face, Image, Plain
from astrbot.api.star import Context, Star, register

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faces import FACE_MAP, resolve_face_id, search_faces  # noqa: E402

try:
    from qzone_bridge.client import QzoneClient  # noqa: E402
    from qzone_bridge.models import SessionState  # noqa: E402
    from qzone_bridge.onebot_cookie import (  # noqa: E402
        call_onebot_action,
        fetch_cookie_text,
        fetch_login_uin,
        iter_onebot_action_callers,
    )
    from qzone_bridge.parser import extract_feed_entry, parse_cookie_text, unwrap_payload  # noqa: E402

    QZONE_OK = True
except Exception as _e:  # pragma: no cover - 仅依赖缺失时
    QZONE_OK = False
    QZONE_IMPORT_ERROR = str(_e)

# ==================== 自动发表情：情绪规则 ====================

EMOTION_RULES: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"晚安|睡了|困|累了|休息|早点睡"), ["月亮", "睡", "困", "哈欠"]),
    (re.compile(r"哈哈|嘿嘿|笑死|好笑|开心|高兴|好耶|太好了|棒|耶|笑"), ["憨笑", "偷笑", "嘿嘿", "笑哭", "呲牙", "狂笑"]),
    (re.compile(r"谢谢|感谢|多谢|谢啦|thx|辛苦"), ["收到", "好的", "合十", "抱拳", "可爱"]),
    (re.compile(r"生气|气死|烦|可恶|讨厌|无语|哼"), ["生气", "发怒", "咒骂", "白眼", "哼哼"]),
    (re.compile(r"哭|难过|伤心|委屈|呜呜|失落|可怜"), ["流泪", "大哭", "泪奔", "委屈", "快哭了"]),
    (re.compile(r"喜欢|爱你|想你|么么|亲亲|抱抱|贴贴|撒娇"), ["爱心", "示爱", "亲亲", "飞吻", "贴贴", "比心"]),
    (re.compile(r"惊|震惊|居然|竟然|不会吧|天呐|吓"), ["惊讶", "惊吓", "惊恐", "瞪眼"]),
    (re.compile(r"牛|厉害|优秀|强|赞|太棒"), ["赞", "厉害", "666", "牛啊", "你真棒棒", "崇拜"]),
    (re.compile(r"吃|饭|饿|奶茶|美食|喝|干杯"), ["蛋糕", "咖啡", "茶", "拉面", "干杯", "吃糖"]),
    (re.compile(r"加油|冲|努力|上班|工作|学习"), ["奋斗", "坚强", "肌肉", "打call"]),
    (re.compile(r"再见|拜拜|溜了|走了"), ["再见", "挥手"]),
    (re.compile(r"疑问|嗯？|为什么|啥|怎么|真的吗"), ["疑问", "问号", "咦", "问号脸"]),
    (re.compile(r"摸鱼|划水|闲|无聊|躺平"), ["摸鱼", "悠闲", "暗中观察", "托腮"]),
    (re.compile(r"得意|骄傲|酷|厉害吧"), ["得意", "傲慢", "酷", "doge"]),
    (re.compile(r"好|好的|行|可以|收到|OK|ok|没问题|嗯嗯"), ["OK", "好的", "收到", "耶", "胜利", "赞"]),
]

GENERAL_FACES = [
    "微笑", "憨笑", "可爱", "得意", "调皮", "呲牙", "偷笑", "酷", "doge",
    "吃瓜", "摸鱼", "耶", "666", "赞", "玫瑰", "爱心", "庆祝", "烟花", "嘿嘿", "卖萌",
]

HELP_TEXT = """🧰 QQ 工具箱
【点赞】赞我 / 赞 <QQ号>
【官方表情】表情 <名称|id>　表情列表 [关键词]
【QQ空间】说说赞 [QQ号]　说说评论 <内容>　发说说 <内容>
【空友爱看】爱看 / 爱看赞 <序号> / 爱看推 <序号> / 爱看评论 <序号> <内容> / 爱看关注 <序号> / 爱看转发 <序号> [附言] / 爱看能力
【拟人】聊天时会自动补表情，无需指令
【帮助】发「帮助」查看本说明"""


def _is_allowed(allow_text: str, uid: str) -> bool:
    allow = [x.strip() for x in re.split(r"[,，\s]+", allow_text or "") if x.strip()]
    if not allow:
        return True
    return uid in allow


def _rand_int(a: int, b: int) -> int:
    a, b = int(a), int(b)
    if b <= a:
        return a
    return a + random.randint(0, b - a)


# ==================== 空友爱看：JSON 粗解析工具 ====================

def _walk_kv(obj: Any, depth: int = 0):
    """递归产出 (key, value)，key 统一小写"""
    if depth > 8 or obj is None:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k).lower(), v
            if isinstance(v, (dict, list)):
                yield from _walk_kv(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                yield from _walk_kv(v, depth + 1)


def _clean_text(s: Any) -> str:
    t = re.sub(r"<[^>]+>", "", str(s or ""))
    t = re.sub(r"\[em\]e\d+\[/em\]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _feed_author(feed: Any) -> str:
    best = ""
    for k, v in _walk_kv(feed):
        if isinstance(v, str) and 0 < len(v) <= 32 and k in ("nick", "nickname", "showname", "name", "uin"):
            if k in ("nick", "nickname"):
                return _clean_text(v)
            if not best and k in ("showname", "name"):
                best = _clean_text(v)
    return best or "?"


_SUMMARY_KEYS = ("content", "summary", "text", "plain_text", "desc", "title", "abstract")


def _feed_summary(feed: Any) -> str:
    best, best_score = "", -1
    for k, v in _walk_kv(feed):
        if not isinstance(v, str):
            continue
        t = _clean_text(v)
        if not (2 <= len(t) <= 200):
            continue
        if t.startswith("http") or t in ("[图片]", "[视频]", "[转发]"):
            continue
        score = 0
        for idx, key in enumerate(_SUMMARY_KEYS):
            if key in k:
                score = 100 - idx
                break
        if score == 0 and "comment" in k:
            continue
        if score > best_score or (score == best_score and len(t) > len(best)):
            best, best_score = t, score
    return best[:80] if best else "[无文字内容]"


def _feed_count(feed: Any, name: str) -> int:
    for k, v in _walk_kv(feed):
        if name not in k:
            continue
        try:
            n = int(v)
        except Exception:
            continue
        if 0 <= n < 10 ** 9:
            return n
    return 0


@register(
    "astrbot_plugin_qq_tools",
    "fnos-napcat-maintainer",
    "QQ 工具箱：资料卡点赞 / 官方表情自动发（拟人）/ QQ空间赞评发",
    "1.0.0",
)
class QqToolsPlugin(Star):
    """QQ 工具箱 AstrBot 插件"""

    def __init__(self, context: Context, config: Any = None) -> None:
        super().__init__(context)
        self.context = context
        self.cfg = config if config is not None else {}
        self._qzone: Any = None
        self._qzone_ts: float = 0.0
        self._qzone_lock = asyncio.Lock()
        self._last_auto: dict[str, float] = {}
        self._kan_cache: dict[str, tuple[float, list[dict]]] = {}
        self._stats = {
            "likes": 0,
            "faces": 0,
            "auto_emoji": 0,
            "auto_skipped": 0,
            "qzone_like": 0,
            "qzone_comment": 0,
            "qzone_publish": 0,
        }
        logger.info(
            "[qq_tools] 已加载 | qzone_bridge=%s | 官方表情=%d",
            "OK" if QZONE_OK else f"MISSING({QZONE_IMPORT_ERROR})",
            len(FACE_MAP),
        )

    # ==================== 配置 & 工具 ====================

    def cfg_get(self, key: str, default: Any = None) -> Any:
        cfg = self.cfg
        try:
            if cfg is None:
                return default
            if hasattr(cfg, "get"):
                val = cfg.get(key, None)
                if val is not None:
                    return val
            return default
        except Exception:
            return default

    def _find_bot(self, event: AstrMessageEvent | None = None) -> Any:
        owners: list[Any] = []
        if event is not None:
            for attr in ("bot", "platform", "adapter"):
                try:
                    obj = getattr(event, attr, None)
                except Exception:
                    obj = None
                if obj is not None:
                    owners.append(obj)
            msg_obj = getattr(event, "message_obj", None)
            if msg_obj is not None:
                owners.append(msg_obj)
                for attr in ("bot", "platform"):
                    try:
                        obj = getattr(msg_obj, attr, None)
                    except Exception:
                        obj = None
                    if obj is not None:
                        owners.append(obj)
        pm = getattr(self.context, "platform_manager", None)
        if pm is not None:
            for attr in ("platform_insts", "platforms", "adapters", "instances"):
                try:
                    val = getattr(pm, attr, None)
                except Exception:
                    val = None
                if val:
                    try:
                        owners.extend(list(val))
                    except Exception:
                        pass
        for owner in owners:
            try:
                if iter_onebot_action_callers(owner):
                    return owner
            except Exception:
                continue
        return owners[0] if owners else None

    async def _action(self, event: AstrMessageEvent, action: str, **params: Any) -> Any:
        bot = self._find_bot(event)
        if bot is None:
            raise RuntimeError("找不到 OneBot 客户端（确认 NapCat 已连接）")
        return await call_onebot_action(bot, action, **params)

    async def _qzone_client(self, event: AstrMessageEvent) -> Any:
        if not QZONE_OK:
            raise RuntimeError(f"qzone_bridge 未就绪: {QZONE_IMPORT_ERROR}")
        async with self._qzone_lock:
            now = time.time()
            if self._qzone is not None and now - self._qzone_ts < 900:
                return self._qzone
            bot = self._find_bot(event)
            if bot is None:
                raise RuntimeError("找不到 OneBot 客户端，无法获取 QQ 空间 Cookie")
            domain = str(self.cfg_get("qzone_cookie_domain", "qzone.qq.com") or "qzone.qq.com")
            try:
                cookie_text = await fetch_cookie_text(bot, domain=domain)
            except Exception as exc:
                raise RuntimeError(
                    "获取 QQ 空间 Cookie 失败（确认机器人已登录且 NapCat 支持 get_cookies/get_credentials）: "
                    f"{exc}"
                ) from exc
            cookies = parse_cookie_text(cookie_text or "")
            if not cookies:
                raise RuntimeError("QQ 空间 Cookie 为空（确认已登录、并且 NapCat 支持 get_cookies）")
            uin = 0
            try:
                uin = int(await fetch_login_uin(bot) or 0)
            except Exception:
                pass
            session = SessionState(uin=uin, cookies=cookies, source="onebot")
            client = QzoneClient(session)
            self._qzone = client
            self._qzone_ts = now
            logger.info("[qq_tools] qzone session ready uin=%s cookies=%s", uin, len(cookies))
            return client

    @staticmethod
    def _dig_list(payload: Any) -> list[dict]:
        """从 QQ 空间返回里找 msglist / feeds 列表"""
        if isinstance(payload, dict):
            for key in ("msglist", "msgList", "feeds", "data", "result"):
                val = payload.get(key)
                if isinstance(val, list) and val:
                    return [x for x in val if isinstance(x, dict)]
                if isinstance(val, dict):
                    found = QqToolsPlugin._dig_list(val)
                    if found:
                        return found
        return []

    async def _latest_post(self, client: Any, hostuin: int) -> Any:
        payload = unwrap_payload(await client.legacy_feeds(int(hostuin), page=1, num=5))
        items = self._dig_list(payload)
        if not items:
            raise RuntimeError("没有找到说说（该用户可能没有动态，或空间有访问限制）")
        return extract_feed_entry(items[0], default_hostuin=int(hostuin))

    def _sender_uin(self, event: AstrMessageEvent) -> str:
        try:
            uid = event.get_sender_id()
            if uid:
                return str(uid)
        except Exception:
            pass
        try:
            uid = getattr(event.message_obj, "sender", None)
            if uid is not None:
                return str(getattr(uid, "user_id", "") or uid)
        except Exception:
            pass
        return ""

    def _check_user(self, event: AstrMessageEvent) -> bool:
        return _is_allowed(str(self.cfg_get("allowed_users", "") or ""), self._sender_uin(event))

    # ==================== 资料卡点赞 ====================

    async def _do_like_profile(self, event: AstrMessageEvent, target_uin: str) -> str:
        if not re.fullmatch(r"\d{5,12}", target_uin or ""):
            return "目标 QQ 号不合法"
        times = int(self.cfg_get("like_times", 10) or 10)
        times = max(1, min(times, 50))
        await self._action(event, "send_like", user_id=target_uin, times=times)
        self._stats["likes"] += times
        logger.info("[qq_tools] 名片赞 %s x%s", target_uin, times)
        return f"已给 {target_uin} 的资料卡点赞 +{times} ✅"

    @filter.regex(r"^赞我$")
    async def cmd_like_me(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        try:
            yield event.plain_result(await self._do_like_profile(event, self._sender_uin(event)))
        except Exception as exc:
            yield event.plain_result(f"点赞失败：{exc}")

    @filter.regex(r"^赞\s*(\d{5,12})$")
    async def cmd_like_uid(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        target = re.search(r"(\d{5,12})", event.message_str or "")
        try:
            yield event.plain_result(await self._do_like_profile(event, target.group(1) if target else ""))
        except Exception as exc:
            yield event.plain_result(f"点赞失败：{exc}")

    # ==================== 官方表情 ====================

    @filter.regex(r"^表情列表(?:\s+(.+))?$")
    async def cmd_face_list(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        kw = (event.message_str or "").replace("表情列表", "", 1).strip()
        names = search_faces(kw, 30)
        if not names:
            yield event.plain_result(f"没有匹配「{kw}」的官方表情")
        else:
            yield event.plain_result(
                f"官方表情{('（含「' + kw + '」）') if kw else ''} {len(names)} 个：\n"
                + "、".join(names)
                + "\n发「表情 <名称>」使用"
            )

    @filter.regex(r"^表情\s+(.+)$")
    async def cmd_face_send(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        arg = re.sub(r"^表情\s+", "", event.message_str or "", count=1).strip()
        fid = resolve_face_id(arg)
        if not fid:
            yield event.plain_result(f"没有找到表情「{arg}」，可以发「表情列表 {arg}」看看")
            return
        self._stats["faces"] += 1
        yield event.chain_result([Face(id=int(fid))])

    # ==================== QQ 空间 ====================

    @filter.regex(r"^说说赞(?:\s*(\d{5,12}))?$")
    async def cmd_qzone_like(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        m = re.search(r"(\d{5,12})", event.message_str or "")
        try:
            client = await self._qzone_client(event)
            hostuin = int(m.group(1)) if m else int(client.login_uin or 0)
            post = await self._latest_post(client, hostuin)
            await client.like_post(
                post.hostuin or hostuin,
                post.fid,
                appid=post.appid or 311,
                curkey=post.curkey,
                unikey=post.unikey,
            )
            self._stats["qzone_like"] += 1
            logger.info("[qq_tools] 空间点赞 hostuin=%s fid=%s", post.hostuin, post.fid)
            snippet = (post.summary or "")[:30]
            yield event.plain_result(f"已给 {post.hostuin} 的最新说说点赞 ✅\n内容：{snippet}")
        except Exception as exc:
            logger.warning("[qq_tools] 空间点赞失败: %s", exc)
            yield event.plain_result(f"空间点赞失败：{exc}")

    @filter.regex(r"^说说评论\s+(.+)$")
    async def cmd_qzone_comment(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        content = re.sub(r"^说说评论\s+", "", event.message_str or "", count=1).strip()
        if not content:
            yield event.plain_result("用法：说说评论 <评论内容>")
            return
        try:
            client = await self._qzone_client(event)
            post = await self._latest_post(client, int(client.login_uin or 0))
            await client.add_comment(
                post.hostuin or int(client.login_uin or 0),
                post.fid,
                content,
                appid=post.appid or 311,
                busi_param=post.busi_param or None,
            )
            self._stats["qzone_comment"] += 1
            logger.info("[qq_tools] 空间评论 hostuin=%s fid=%s", post.hostuin, post.fid)
            yield event.plain_result(f"已评论最新说说 ✅\n评论内容：{content}")
        except Exception as exc:
            logger.warning("[qq_tools] 空间评论失败: %s", exc)
            yield event.plain_result(f"空间评论失败：{exc}")

    @filter.regex(r"^发说说\s+(.+)$")
    async def cmd_qzone_publish(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        content = re.sub(r"^发说说\s+", "", event.message_str or "", count=1).strip()
        if not content:
            yield event.plain_result("用法：发说说 <内容>")
            return
        try:
            client = await self._qzone_client(event)
            await client.publish_mood(content)
            self._stats["qzone_publish"] += 1
            logger.info("[qq_tools] 发布说说成功 len=%s", len(content))
            yield event.plain_result(f"已发布说说 ✅\n{content}")
        except Exception as exc:
            logger.warning("[qq_tools] 发布说说失败: %s", exc)
            yield event.plain_result(f"发布说说失败：{exc}")

    # ==================== 空友爱看（公域推荐流） ====================

    async def _kan_fetch(self, event: AstrMessageEvent, cursor: str | None = None) -> tuple[dict, list[dict]]:
        params: dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor
        data = await self._action(event, "get_qzone_public_feeds", **params)
        if not isinstance(data, dict):
            raise RuntimeError("空友爱看返回格式异常")
        feeds = [x for x in (data.get("feeds") or []) if isinstance(x, dict)]
        self._kan_cache[event.unified_msg_origin] = (time.time(), feeds)
        return data, feeds

    def _kan_pick(self, event: AstrMessageEvent, index: int) -> dict:
        cached = self._kan_cache.get(event.unified_msg_origin)
        if not cached or time.time() - cached[0] > 600:
            raise RuntimeError("请先发「爱看」拉取推荐流")
        feeds = cached[1]
        if not (1 <= index <= len(feeds)):
            raise RuntimeError(f"序号超出范围（当前列表 1-{len(feeds)}）")
        return feeds[index - 1]

    def _format_kan_feeds(self, feeds: list[dict], has_more: bool = False) -> str:
        if not feeds:
            return "空友爱看没有返回内容（可能服务端限制或账号无权限）"
        lines = [f"🫂 空友爱看 · {len(feeds)} 条（发「爱看赞 1」「爱看评论 1 内容」操作）"]
        for i, feed in enumerate(feeds[:10], 1):
            author = _feed_author(feed)
            text = _feed_summary(feed)
            like = _feed_count(feed, "like")
            cmt = _feed_count(feed, "comment")
            extra = f" 赞{like} 评{cmt}" if (like or cmt) else ""
            lines.append(f"{i}. {author}：{text}{extra}")
        if len(feeds) > 10:
            lines.append(f"… 共 {len(feeds)} 条")
        if has_more:
            lines.append("（还有更多，可继续发「爱看」翻页）")
        return "\n".join(lines)

    @filter.regex(r"^(?:空友)?爱看(?:列表)?$")
    async def cmd_kan_list(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        try:
            data, feeds = await self._kan_fetch(event)
            yield event.plain_result(self._format_kan_feeds(feeds, bool(data.get("has_more"))))
        except Exception as exc:
            logger.warning("[qq_tools] 拉取空友爱看失败: %s", exc)
            yield event.plain_result(f"拉取空友爱看失败：{exc}")

    @filter.regex(r"^(?:空友)?爱看赞\s*(\d+)$")
    async def cmd_kan_like(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        try:
            feed = self._kan_pick(event, int(re.search(r"(\d+)$", event.message_str or "").group(1)))
            await self._action(event, "set_qzone_public_like", feed=feed, enable=True)
            yield event.plain_result("已给该空友动态点赞 ✅")
        except Exception as exc:
            yield event.plain_result(f"空友爱看点赞失败：{exc}")

    @filter.regex(r"^(?:空友)?爱看推\s*(\d+)$")
    async def cmd_kan_upvote(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        try:
            feed = self._kan_pick(event, int(re.search(r"(\d+)$", event.message_str or "").group(1)))
            await self._action(event, "set_qzone_public_upvote", feed=feed, enable=True)
            yield event.plain_result("已推该空友动态 ✅")
        except Exception as exc:
            yield event.plain_result(f"推失败：{exc}")

    @filter.regex(r"^(?:空友)?爱看关注\s*(\d+)$")
    async def cmd_kan_follow(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        try:
            feed = self._kan_pick(event, int(re.search(r"(\d+)$", event.message_str or "").group(1)))
            await self._action(event, "set_qzone_public_follow", feed=feed, enable=True)
            yield event.plain_result("已蹲该作者 ✅（再发一次取消，需要时告诉我）")
        except Exception as exc:
            yield event.plain_result(f"关注失败：{exc}")

    @filter.regex(r"^(?:空友)?爱看评论\s+(\d+)\s+(.+)$")
    async def cmd_kan_comment(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        m = re.match(r"^(?:空友)?爱看评论\s+(\d+)\s+(.+)$", event.message_str or "", re.S)
        if not m:
            return
        try:
            feed = self._kan_pick(event, int(m.group(1)))
            content = m.group(2).strip()
            await self._action(event, "comment_qzone_public_feed", feed=feed, content=content)
            self._stats["qzone_comment"] += 1
            yield event.plain_result(f"已评论该空友动态 ✅\n{content}")
        except Exception as exc:
            yield event.plain_result(f"空友爱看评论失败：{exc}")

    @filter.regex(r"^(?:空友)?爱看转发\s+(\d+)(?:\s+(.+))?$")
    async def cmd_kan_forward(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        m = re.match(r"^(?:空友)?爱看转发\s+(\d+)(?:\s+(.+))?$", event.message_str or "", re.S)
        if not m:
            return
        try:
            feed = self._kan_pick(event, int(m.group(1)))
            reason = (m.group(2) or "").strip()
            await self._action(event, "forward_qzone_public_feed", feed=feed, reason=reason)
            yield event.plain_result("已转发该空友动态到自己的空间 ✅")
        except Exception as exc:
            yield event.plain_result(f"转发失败：{exc}")

    @filter.regex(r"^(?:空友)?爱看能力$")
    async def cmd_kan_capabilities(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        if not self._check_user(event):
            return
        try:
            data = await self._action(event, "get_qzone_public_capabilities")
            text = json.dumps(data, ensure_ascii=False)
            yield event.plain_result(f"空友爱看接口能力：\n{text[:900]}")
        except Exception as exc:
            yield event.plain_result(f"查询能力失败：{exc}")

    # ==================== LLM tools（空友爱看） ====================

    @filter.llm_tool(name="qzone_public_feeds")
    async def tool_kan_feeds(self, event: AstrMessageEvent):
        """获取「空友爱看」公域推荐流的动态列表（可用来找内容、互动）。"""
        try:
            data, feeds = await self._kan_fetch(event)
            return self._format_kan_feeds(feeds, bool(data.get("has_more")))
        except Exception as exc:
            return f"拉取空友爱看失败：{exc}"

    @filter.llm_tool(name="qzone_public_like")
    async def tool_kan_like(self, event: AstrMessageEvent, index: int):
        """给「空友爱看」列表里第 index 条动态点赞（先用 qzone_public_feeds 拉列表）。

        Args:
            index(number): 列表序号，从 1 开始
        """
        try:
            feed = self._kan_pick(event, int(index))
            await self._action(event, "set_qzone_public_like", feed=feed, enable=True)
            return f"已给空友爱看第 {index} 条动态点赞"
        except Exception as exc:
            return f"空友爱看点赞失败：{exc}"

    @filter.llm_tool(name="qzone_public_comment")
    async def tool_kan_comment(self, event: AstrMessageEvent, index: int, content: str):
        """评论「空友爱看」列表里第 index 条动态（先用 qzone_public_feeds 拉列表）。

        Args:
            index(number): 列表序号，从 1 开始
            content(string): 评论内容
        """
        try:
            feed = self._kan_pick(event, int(index))
            await self._action(event, "comment_qzone_public_feed", feed=feed, content=str(content))
            return f"已评论空友爱看第 {index} 条动态：{content}"
        except Exception as exc:
            return f"空友爱看评论失败：{exc}"

    @filter.regex(r"^(帮助|qq工具|QQ工具)$")
    async def cmd_help(self, event: AstrMessageEvent):
        event.should_call_llm(False)
        yield event.plain_result(HELP_TEXT)

    # ==================== LLM tools ====================

    @filter.llm_tool(name="like_profile")
    async def tool_like_profile(self, event: AstrMessageEvent, user_id: str, times: int = 10):
        """给指定 QQ 的资料卡点赞。

        Args:
            user_id(string): 目标 QQ 号
            times(number): 点赞次数，默认 10
        """
        try:
            saved = int(self.cfg_get("like_times", 10) or 10)
            if int(times) == 10:
                times = saved
            return await self._do_like_profile(event, str(user_id))
        except Exception as exc:
            return f"点赞失败：{exc}"

    @filter.llm_tool(name="send_official_face")
    async def tool_send_face(self, event: AstrMessageEvent, name: str):
        """发送 QQ 官方表情（小黄脸/超级表情）。可用名称见配置或「表情列表」指令。

        Args:
            name(string): 表情名称，如 微笑 / 赞 / 流泪；也可传数字 id
        """
        fid = resolve_face_id(name)
        if not fid:
            near = "、".join(search_faces(name, 8))
            return f"没有找到「{name}」这个官方表情。相近的有：{near}"
        self._stats["faces"] += 1
        # 通过消息链直接发送（工具结果会作为下一条消息）
        try:
            await event.send(MessageChain(chain=[Face(id=int(fid))]))
        except Exception:
            pass
        return f"已发送官方表情：{name}"

    @filter.llm_tool(name="qzone_like_latest")
    async def tool_qzone_like(self, event: AstrMessageEvent, hostuin: int = 0):
        """给指定 QQ（默认自己）最新一条 QQ 空间说说点赞。

        Args:
            hostuin(number): 目标 QQ 号，0 表示自己
        """
        try:
            client = await self._qzone_client(event)
            target = int(hostuin) if hostuin else int(client.login_uin or 0)
            post = await self._latest_post(client, target)
            await client.like_post(
                post.hostuin or target,
                post.fid,
                appid=post.appid or 311,
                curkey=post.curkey,
                unikey=post.unikey,
            )
            self._stats["qzone_like"] += 1
            return f"已给 {post.hostuin} 的最新说说点赞。内容摘要：{(post.summary or '')[:40]}"
        except Exception as exc:
            return f"空间点赞失败：{exc}"

    @filter.llm_tool(name="qzone_comment_latest")
    async def tool_qzone_comment(self, event: AstrMessageEvent, content: str, hostuin: int = 0):
        """评论指定 QQ（默认自己）最新一条 QQ 空间说说。

        Args:
            content(string): 评论内容
            hostuin(number): 目标 QQ 号，0 表示自己
        """
        try:
            client = await self._qzone_client(event)
            target = int(hostuin) if hostuin else int(client.login_uin or 0)
            post = await self._latest_post(client, target)
            await client.add_comment(
                post.hostuin or target,
                post.fid,
                content,
                appid=post.appid or 311,
                busi_param=post.busi_param or None,
            )
            self._stats["qzone_comment"] += 1
            return f"已评论 {post.hostuin} 的最新说说：{content}"
        except Exception as exc:
            return f"空间评论失败：{exc}"

    @filter.llm_tool(name="qzone_publish")
    async def tool_qzone_publish(self, event: AstrMessageEvent, content: str):
        """发布一条 QQ 空间说说（文字）。

        Args:
            content(string): 说说正文
        """
        try:
            client = await self._qzone_client(event)
            await client.publish_mood(content)
            self._stats["qzone_publish"] += 1
            return f"已发布说说：{content}"
        except Exception as exc:
            return f"发布说说失败：{exc}"

    # ==================== 自动发表情（拟人） ====================

    def _pick_auto_face(self, text: str) -> tuple[int, str] | None:
        pool: list[str] = []
        for pattern, faces in EMOTION_RULES:
            if pattern.search(text or ""):
                pool = faces
                break
        if not pool:
            pool = GENERAL_FACES
        for _ in range(8):
            name = random.choice(pool)
            fid = resolve_face_id(name)
            if fid:
                return int(fid), name
        return None

    @filter.on_decorating_result()
    async def auto_emoji(self, event: AstrMessageEvent):
        if not bool(self.cfg_get("auto_emoji_enable", True)):
            return
        try:
            result = event.get_result()
            chain = getattr(result, "chain", None) if result is not None else None
            if not chain:
                return
            # 只在纯文字回复后补（已有表情/图片则跳过）
            if any(isinstance(c, (Face, Image)) for c in chain):
                return
            text = "".join(c.text for c in chain if isinstance(c, Plain)).strip()
            if len(text) < 2:
                return
            # 群聊/私聊开关
            umo = event.unified_msg_origin or ""
            is_group = "group" in umo.lower() or "Group" in umo
            if is_group and not bool(self.cfg_get("auto_emoji_in_group", True)):
                return
            if (not is_group) and not bool(self.cfg_get("auto_emoji_in_private", True)):
                return
            now = time.time()
            cooldown = float(self.cfg_get("auto_emoji_cooldown", 30) or 30)
            if cooldown > 0 and now - self._last_auto.get(umo, 0.0) < cooldown:
                self._stats["auto_skipped"] += 1
                return
            prob = float(self.cfg_get("auto_emoji_probability", 35) or 35)
            if random.random() * 100 >= prob:
                self._stats["auto_skipped"] += 1
                return
            picked = self._pick_auto_face(text)
            if not picked:
                return
            fid, name = picked
            delay_min = int(self.cfg_get("auto_emoji_delay_min", 400) or 400)
            delay_max = int(self.cfg_get("auto_emoji_delay_max", 1600) or 1600)

            async def _send_later() -> None:
                await asyncio.sleep(_rand_int(delay_min, delay_max) / 1000.0)
                try:
                    await event.send(MessageChain(chain=[Face(id=fid)]))
                    self._stats["auto_emoji"] += 1
                    self._last_auto[umo] = time.time()
                    logger.info("[qq_tools] 自动补发表情「%s」-> %s", name, umo)
                except Exception as exc:
                    logger.warning("[qq_tools] 自动补发表情失败: %s", exc)

            asyncio.create_task(_send_later())
        except Exception as exc:
            logger.warning("[qq_tools] auto_emoji 异常: %s", exc)

    @filter.on_astrbot_loaded()
    async def _probe_qzone_public(self, event: Any = None):
        """启动后探测空友爱看接口能力（只读，不执行任何写操作）"""
        await asyncio.sleep(10)
        bot = None
        try:
            bot = self._find_bot(None)
            if bot is None:
                logger.info("[qq_tools] 启动探测：暂未找到 OneBot 客户端")
            else:
                try:
                    data = await call_onebot_action(bot, "get_qzone_public_capabilities")
                    logger.info("[qq_tools] 空友爱看能力: %s", json.dumps(data, ensure_ascii=False)[:3000])
                except BaseException as exc:
                    logger.warning("[qq_tools] 空友爱看能力探测失败: %r", exc)
        except BaseException as exc:
            logger.warning("[qq_tools] 启动探测异常: %r", exc)

    # ==================== 状态 ====================

    async def status(self) -> dict[str, Any]:
        return {
            "stats": dict(self._stats),
            "face_count": len(FACE_MAP),
            "qzone_ready": self._qzone is not None,
            "qzone_ok": QZONE_OK,
        }

    async def terminate(self):
        logger.info("[qq_tools] 插件卸载")
