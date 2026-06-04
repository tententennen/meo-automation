"""Tests for the meo-report CLI (tools/report.py)."""

from unittest.mock import patch
import pytest

from meo.tools.report import run_report, main


_FAKE_POSTS = [
    {
        "date": "2026-06-04",
        "theme": "季節のお手入れ情報",
        "text": "梅雨の季節に向けて、しっかりとしたヘアケアが大切です。",
        "post_name": "accounts/1/locations/2/localPosts/5",
    },
]

_FAKE_REPLIES = [
    {
        "date": "2026-06-03",
        "review_id": "rev001",
        "reviewer": "田中太郎",
        "stars": "FIVE",
        "reply": "ありがとうございます！またのご来店をお待ちしております。",
    },
]


def _patch_history(posts=None, replies=None):
    """Return a context manager that patches get_post_history and get_reply_history."""
    return (
        patch("meo.tools.report.get_post_history", return_value=posts or []),
        patch("meo.tools.report.get_reply_history", return_value=replies or []),
    )


# ---------------------------------------------------------------------------
# run_report() unit tests
# ---------------------------------------------------------------------------

def test_run_report_contains_store_names():
    """Report text should contain all store names."""
    post_p, reply_p = _patch_history()
    with post_p, reply_p:
        text, code = run_report()
    assert code == 0
    assert "THE BODY 大阪 心斎橋店" in text
    assert "THE BODY 京都店" in text
    assert "MYBEAR STUDIO 京都店" in text


def test_run_report_shows_post_history():
    """When post history exists, the report includes the post text preview."""
    post_p, reply_p = _patch_history(posts=_FAKE_POSTS)
    with post_p, reply_p:
        text, code = run_report(store_filter="the_body_kyoto")
    assert code == 0
    assert "季節のお手入れ情報" in text
    assert "梅雨の季節" in text


def test_run_report_shows_reply_history():
    """When reply history exists, the report includes the reviewer name."""
    post_p, reply_p = _patch_history(replies=_FAKE_REPLIES)
    with post_p, reply_p:
        text, code = run_report(store_filter="the_body_kyoto")
    assert code == 0
    assert "田中太郎" in text
    assert "FIVE" in text or "★★★★★" in text


def test_run_report_no_history_shows_placeholder():
    """When no history is archived, the report shows a friendly placeholder."""
    post_p, reply_p = _patch_history()
    with post_p, reply_p:
        text, code = run_report(store_filter="the_body_kyoto")
    assert code == 0
    assert "no posts archived" in text or "まだ" in text or "(no" in text


def test_run_report_unknown_store_returns_code_1():
    """Filtering on an unknown store key returns exit code 1."""
    post_p, reply_p = _patch_history()
    with post_p, reply_p:
        text, code = run_report(store_filter="nonexistent_store")
    assert code == 1
    assert "Unknown store key" in text


def test_run_report_store_filter_limits_output():
    """Filtering on one store excludes the other stores from the report."""
    post_p, reply_p = _patch_history()
    with post_p, reply_p:
        text, code = run_report(store_filter="the_body_kyoto")
    assert code == 0
    assert "THE BODY 京都店" in text
    assert "THE BODY 大阪 心斎橋店" not in text
    assert "MYBEAR STUDIO 京都店" not in text


# ---------------------------------------------------------------------------
# main() CLI tests
# ---------------------------------------------------------------------------

def test_main_exits_0_on_success(capsys):
    post_p, reply_p = _patch_history()
    with patch("sys.argv", ["meo-report"]), post_p, reply_p:
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "MEO Automation" in out


def test_main_exits_1_on_unknown_store(capsys):
    post_p, reply_p = _patch_history()
    with patch("sys.argv", ["meo-report", "--store", "bad_key"]), post_p, reply_p:
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


def test_main_output_flag_saves_file(tmp_path):
    out_file = tmp_path / "report.txt"
    post_p, reply_p = _patch_history(posts=_FAKE_POSTS)
    with patch("sys.argv", ["meo-report", "--output", str(out_file)]), post_p, reply_p:
        with pytest.raises(SystemExit):
            main()
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "MEO Automation" in content
