"""会话持久化路径遍历防护测试。"""

from __future__ import annotations

from GensokyoAI.session.persistence import SessionPersistence


def test_session_path_sanitizes_character_id(tmp_path) -> None:
    persistence = SessionPersistence(tmp_path)
    path = persistence._get_session_path("../../../etc/passwd", "session-1")
    # 净化后不应逃出 base_path
    assert path.resolve().is_relative_to(tmp_path.resolve())
    assert "etc_passwd" in str(path)


def test_session_path_sanitizes_session_id(tmp_path) -> None:
    persistence = SessionPersistence(tmp_path)
    path = persistence._get_session_path("Reimu", "../shadow.json")
    assert path.resolve().is_relative_to(tmp_path.resolve())
    assert "shadow_json" in str(path)
    assert ".." not in path.name


def test_save_messages_does_not_escape_base_path(tmp_path) -> None:
    persistence = SessionPersistence(tmp_path)
    # 即使传入恶意 session_id，也不应在 base_path 外创建文件
    persistence.save_messages("../../../evil", [])
    # 不应存在 evil.json 或其他逃逸文件
    assert not any("evil" in p.name for p in tmp_path.rglob("*") if p.is_file())
