"""Streamlit 入口:幻想乡聊天界面。

修复要点:
- 不用 session_state 差异 + st.rerun 的"按钮+rerun"组合,改用 on_change 回调,避免循环
- 所有 init / refresh 都不主动 rerun,让 Streamlit 自己一帧一帧自然重渲染
- init_log 始终在主区底部显示(无论 agent_ready 是啥)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from streamlit_app.api_client import (
    GensokyoRuntimeClient,
    GensokyoRuntimeError,
)

# ----------------- 页面配置 -----------------
st.set_page_config(
    page_title="幻想乡聊天 · GensokyoAI",
    page_icon="\U0001f338",
    layout="wide",
)


# ----------------- 常量 -----------------
RUNTIME_HTTP = "http://127.0.0.1:8765"
RUNTIME_WS = "ws://127.0.0.1:8765/ws"
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CHARACTER = "characters/zh_cn/KirisameMarisa.yaml"


# ----------------- Session State 初始化 -----------------
def init_state() -> None:
    ss = st.session_state
    ss.setdefault("client", GensokyoRuntimeClient(RUNTIME_HTTP, RUNTIME_WS))
    ss.setdefault("runtime_ok", False)
    # 角色
    ss.setdefault("characters", [])
    ss.setdefault("character_path", DEFAULT_CHARACTER)
    ss.setdefault("character_name", "雾雨魔理沙")
    # 会话
    ss.setdefault("sessions", [])
    ss.setdefault("session_id", None)
    # Agent
    ss.setdefault("agent_ready", False)
    # 消息
    ss.setdefault("messages", [])
    ss.setdefault("streaming", False)
    ss.setdefault("draft_text", "")
    ss.setdefault("draft_status", "")
    # 调试
    ss.setdefault("init_log", [])


init_state()


# ----------------- Runtime 异步操作(全部为 awaitable) -----------------
async def _check_runtime() -> dict:
    return await st.session_state.client.health()


async def _list_characters() -> list[dict]:
    res = await st.session_state.client.call("character.list")
    return res if isinstance(res, list) else []


async def _list_sessions() -> list[dict]:
    res = await st.session_state.client.call("session.list")
    return res if isinstance(res, list) else []


async def _agent_init(character_path: str, session_id: str | None = None) -> dict:
    params: dict[str, Any] = {
        "character_path": character_path,
        "config_path": str(PROJECT_ROOT / "config" / "default.yaml"),
    }
    if session_id:
        params["session_id"] = session_id
        params["new_session"] = False
    else:
        params["new_session"] = True
    return await st.session_state.client.call("agent.init", params)


async def _send_blocking(message: str) -> dict:
    return await st.session_state.client.send_message(message)


async def _get_session_messages() -> list[dict]:
    try:
        res = await st.session_state.client.call("session.messages", {})
    except Exception:
        return []
    if not isinstance(res, dict):
        return []
    msgs = res.get("messages") or []
    out: list[dict] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = m.get("role") or "user"
        content = m.get("content")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str):
            content = str(content) if content is not None else ""
        out.append({"role": role, "content": content})
    return out


def _extract_content(result) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return str(result)
    for key in ("content", "message", "text", "reply", "response", "output"):
        v = result.get(key)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, dict):
                msg = first.get("message") or first
                if isinstance(msg, dict):
                    c = msg.get("content")
                    if isinstance(c, str):
                        return c
    return ""


# ----------------- 业务动作(同步执行异步,不 rerun) -----------------
def do_refresh_all() -> None:
    """Runtime 状态 + 角色 + 会话列表,全部刷新一次。"""
    try:
        asyncio.run(_check_runtime())
        st.session_state.runtime_ok = True
    except Exception:
        st.session_state.runtime_ok = False
        return
    try:
        st.session_state.characters = asyncio.run(_list_characters())
    except Exception as e:
        st.session_state.init_log.append(f"列角色失败:{e}")
    try:
        st.session_state.sessions = asyncio.run(_list_sessions())
    except Exception as e:
        st.session_state.init_log.append(f"列会话失败:{e}")


def do_agent_init(character_path: str, session_id: str | None = None) -> None:
    """初始化或恢复会话。不触发 rerun。"""
    action = "恢复会话" if session_id else "新建会话"
    st.session_state.init_log = [f"[{action}] character={character_path} session_id={session_id}"]

    # 先把会话列表清空,防止 selectbox 还指着旧 index 触发 on_change
    # 注意:这次 init 是用户主动行为,on_change 已经触发了
    try:
        result = asyncio.run(_agent_init(character_path, session_id))
        st.session_state.init_log.append(f"agent.init 返回: {str(result)[:300]}")

        st.session_state.agent_ready = True
        # 角色显示名
        char_match = next(
            (c for c in st.session_state.characters if c.get("path") == character_path),
            None,
        )
        st.session_state.character_name = (
            char_match.get("name") if char_match else None
        ) or character_path.split("/")[-1].replace(".yaml", "")
        # 会话 id
        sess = (result or {}).get("session") or {}
        st.session_state.session_id = sess.get("id") or (result or {}).get("session_id")
        st.session_state.messages = []
        st.session_state.draft_text = ""
        st.session_state.draft_status = ""
        # 重新拉会话列表
        try:
            st.session_state.sessions = asyncio.run(_list_sessions())
        except Exception as e:
            st.session_state.init_log.append(f"刷新会话列表失败:{e}")
        # 加载历史消息
        try:
            msgs = asyncio.run(_get_session_messages())
            st.session_state.messages = msgs
            st.session_state.init_log.append(f"加载历史消息 {len(msgs)} 条")
        except Exception as e:
            st.session_state.init_log.append(f"加载历史消息失败(忽略):{e}")
        st.session_state.init_log.append(
            f"✅ {action}成功:{st.session_state.character_name} "
            f"session={st.session_state.session_id}"
        )
    except GensokyoRuntimeError as e:
        st.session_state.agent_ready = False
        st.session_state.init_log.append(f"❌ 初始化失败:{e}")
    except Exception as e:
        st.session_state.agent_ready = False
        st.session_state.init_log.append(f"❌ 连接失败:{e}")


def do_clear_chat() -> None:
    st.session_state.messages = []
    st.session_state.draft_text = ""
    st.session_state.draft_status = ""


# ----------------- selectbox / button 回调 -----------------
def _on_character_change() -> None:
    """角色下拉框变化时触发。"""
    new_label = st.session_state.character_select
    label_to_path = {
        c.get("name") or c.get("id") or c.get("path"): c.get("path")
        for c in st.session_state.characters
    }
    new_path = label_to_path.get(new_label)
    if new_path and new_path != st.session_state.character_path:
        st.session_state.character_path = new_path
        # 切角色 = 开新会话(不传 session_id)
        do_agent_init(new_path)


def _on_session_change() -> None:
    """会话下拉框变化时触发。"""
    new_label = st.session_state.session_select
    sess_options = st.session_state.sessions or []
    sess_map = {_format_session_label(s): s for s in sess_options}
    sess = sess_map.get(new_label)
    if not sess:
        return
    new_sid = sess.get("session_id")
    if not new_sid or new_sid == st.session_state.session_id:
        return
    # 找这个会话对应的角色 path
    sess_char = sess.get("character_id")
    target_path = st.session_state.character_path
    target_name = st.session_state.character_name
    if sess_char and st.session_state.characters:
        char_match = next(
            (
                c
                for c in st.session_state.characters
                if c.get("name") == sess_char or c.get("id") == sess_char
            ),
            None,
        )
        if char_match:
            target_path = char_match.get("path") or target_path
            target_name = char_match.get("name") or target_name
    do_agent_init(target_path, session_id=new_sid)
    st.session_state.character_name = target_name


def _on_new_session_click() -> None:
    """「＋ 新会话」按钮:用当前角色开一个新会话。"""
    do_agent_init(st.session_state.character_path)


def _on_refresh_click() -> None:
    """「刷新」按钮:重拉会话列表。"""
    try:
        st.session_state.sessions = asyncio.run(_list_sessions())
        st.session_state.init_log.append(f"刷新:共 {len(st.session_state.sessions)} 个会话")
    except Exception as e:
        st.session_state.init_log.append(f"刷新失败:{e}")


def _on_recheck_click() -> None:
    """「重新检测 / 刷新列表」按钮。"""
    do_refresh_all()


def _on_clear_click() -> None:
    do_clear_chat()


def _format_session_label(s: dict) -> str:
    sid = s.get("session_id") or "?"
    last_active = s.get("last_active") or ""
    try:
        dt = datetime.fromisoformat(last_active)
        ts = dt.strftime("%m-%d %H:%M")
    except Exception:
        ts = last_active[:16] if last_active else ""
    turns = s.get("total_turns", 0)
    cid = s.get("character_id") or "?"
    return f"[{ts}] {cid} · {turns}轮 · {sid[:8]}"


# ----------------- 侧边栏 -----------------
def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### \U0001f338 幻想乡聊天")
        st.caption("GensokyoAI · Streamlit 前端")

        st.divider()

        # Runtime
        st.markdown("**Runtime**")
        if st.session_state.runtime_ok:
            st.success("已连接 127.0.0.1:8765", icon="\u2705")
        else:
            st.error("未连接", icon="\u26a0\ufe0f")
        st.button(
            "重新检测 / 刷新列表",
            use_container_width=True,
            on_click=_on_recheck_click,
        )

        st.divider()

        # 角色
        st.markdown("**角色**")
        char_options = st.session_state.characters or []
        if char_options:
            label_to_path = {
                c.get("name") or c.get("id") or c.get("path"): c.get("path") for c in char_options
            }
            labels = list(label_to_path.keys())
            # 找当前 path 对应的 label
            current_label = None
            for lab, pth in label_to_path.items():
                if pth == st.session_state.character_path:
                    current_label = lab
                    break
            if current_label is None:
                current_label = labels[0]
            st.selectbox(
                "选择角色",
                options=labels,
                index=labels.index(current_label),
                key="character_select",
                on_change=_on_character_change,
                disabled=st.session_state.streaming,
            )
        else:
            st.caption("(暂无角色列表,先点「重新检测」)")

        st.divider()

        # 会话
        st.markdown("**会话**")
        c1, c2 = st.columns(2)
        with c1:
            st.button(
                "＋ 新会话",
                type="primary",
                use_container_width=True,
                on_click=_on_new_session_click,
                disabled=st.session_state.streaming,
            )
        with c2:
            st.button(
                "刷新",
                use_container_width=True,
                on_click=_on_refresh_click,
                disabled=st.session_state.streaming,
            )

        sess_options = st.session_state.sessions or []
        if sess_options:
            # 按 last_active 倒序
            sess_options = sorted(
                sess_options,
                key=lambda s: s.get("last_active") or "",
                reverse=True,
            )
            labels = [_format_session_label(s) for s in sess_options]
            current_sid = st.session_state.session_id
            current_label = None
            for s in sess_options:
                if s.get("session_id") == current_sid:
                    current_label = _format_session_label(s)
                    break
            if current_label is None:
                current_label = labels[0]
            st.selectbox(
                "切换会话",
                options=labels,
                index=labels.index(current_label),
                key="session_select",
                on_change=_on_session_change,
                disabled=st.session_state.streaming,
            )
        else:
            st.caption("(暂无会话)")

        st.divider()
        st.button(
            "清空当前对话视图",
            use_container_width=True,
            on_click=_on_clear_click,
            disabled=st.session_state.streaming,
        )

        st.divider()
        with st.expander("启动命令", expanded=False):
            st.code(
                "cd D:\\minimaxFile\\gensokyoAI\\GensokyoAI\npython runtime_http.py",
                language="bash",
            )


# ----------------- 主区域 -----------------
def render_main() -> None:
    # 启动时拉一次
    if not st.session_state.runtime_ok and not st.session_state.characters:
        do_refresh_all()

    if st.session_state.character_name:
        st.markdown(f"## \U0001f338 幻想乡聊天 · {st.session_state.character_name}")
    else:
        st.markdown("## \U0001f338 幻想乡聊天")

    if not st.session_state.runtime_ok:
        st.warning(
            "Runtime 未连接。请先在另一个终端启动后端:\n\n"
            "```\ncd D:\\minimaxFile\\gensokyoAI\\GensokyoAI\n"
            "python runtime_http.py\n```",
            icon="\u26a0\ufe0f",
        )
        _render_init_log()
        return

    if not st.session_state.agent_ready:
        st.info(
            "在左侧选择角色,点「＋ 新会话」或选择已有会话开始聊天。",
            icon="\U0001f4da",
        )
        _render_init_log()
        return

    # 历史消息
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 思考中占位
    if st.session_state.streaming:
        with st.chat_message("assistant"):
            st.caption(st.session_state.draft_status or "正在思考...")

    # 输入框
    user_input = st.chat_input(
        "说点什么...",
        disabled=st.session_state.streaming,
    )
    if user_input:
        _handle_user_input(user_input)

    _render_init_log()


def _render_init_log() -> None:
    if st.session_state.init_log:
        with st.expander("最近一次初始化日志", expanded=False):
            for line in st.session_state.init_log:
                st.text(line)


def _handle_user_input(user_input: str) -> None:
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.session_state.streaming = True
    st.session_state.draft_text = ""
    st.session_state.draft_status = "正在思考..."
    st.rerun()


def _consume(user_input: str) -> None:
    final_text = ""
    raw_result = None
    had_error = False
    err_msg = ""

    try:
        raw_result = asyncio.run(_send_blocking(user_input))
        final_text = _extract_content(raw_result)
    except GensokyoRuntimeError as e:
        had_error = True
        err_msg = str(e)
    except Exception as e:
        had_error = True
        err_msg = f"未知错误:{e}"
    finally:
        st.session_state.streaming = False
        if had_error:
            content = f"(出错:{err_msg})"
        elif final_text:
            content = final_text
        else:
            content = (
                "(无回复)\n\n"
                f"**用户输入**: `{user_input}`\n\n"
                f"**后端返回**: `{type(raw_result).__name__}`\n\n"
                f"```\n{str(raw_result)[:1500]}\n```"
            )
        st.session_state.messages.append({"role": "assistant", "content": content})
        st.session_state.draft_text = ""
        st.session_state.draft_status = ""
        st.rerun()


# ----------------- 入口 -----------------
render_sidebar()
render_main()

if (
    st.session_state.streaming
    and st.session_state.messages
    and st.session_state.messages[-1]["role"] == "user"
):
    last_user = st.session_state.messages[-1]["content"]
    _consume(last_user)
