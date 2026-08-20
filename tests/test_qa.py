"""Tests for the Q&A module — fully mocked (no real network calls)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call
import pytest
import requests

from meo.qa import (
    run_qa_for_store,
    _has_owner_answer,
    _extract_question_id,
    _question_age_days,
)
from meo.business_profile import BusinessProfileClient, _qa_location_name


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STORE = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
    "location_id": "accounts/1/locations/42",
    "drive_folder_id": "folder_abc",
}

_Q_UNANSWERED = {
    "name": "locations/42/questions/q001",
    "author": {"displayName": "田中太郎", "type": "REGULAR_USER"},
    "text": "駐車場はありますか？",
    "createTime": "2026-08-01T09:00:00.000Z",
    "updateTime": "2026-08-01T09:00:00.000Z",
    "upvoteCount": 1,
    "totalAnswerCount": 0,
    "topAnswers": [],
}

_Q_OWNER_ANSWERED = {
    "name": "locations/42/questions/q002",
    "author": {"displayName": "鈴木花子", "type": "REGULAR_USER"},
    "text": "予約はどうやってすれば良いですか？",
    "createTime": "2026-08-02T09:00:00.000Z",
    "updateTime": "2026-08-02T09:00:00.000Z",
    "upvoteCount": 3,
    "totalAnswerCount": 1,
    "topAnswers": [
        {"text": "公式サイトからご予約いただけます。", "author": {"type": "MERCHANT"}}
    ],
}

_Q_USER_ANSWERED_ONLY = {
    "name": "locations/42/questions/q003",
    "author": {"displayName": "山本一郎", "type": "REGULAR_USER"},
    "text": "定休日はいつですか？",
    "createTime": "2026-08-03T09:00:00.000Z",
    "updateTime": "2026-08-03T09:00:00.000Z",
    "upvoteCount": 0,
    "totalAnswerCount": 1,
    "topAnswers": [
        {"text": "日曜日です", "author": {"type": "REGULAR_USER"}}
    ],
}


@pytest.fixture(autouse=True)
def patch_state_functions(monkeypatch):
    """Silence all state I/O for every test in this module."""
    monkeypatch.setattr("meo.qa.get_answered_questions", lambda *a: [])
    monkeypatch.setattr("meo.qa.record_answered_question", lambda *a: None)
    monkeypatch.setattr("meo.qa.record_answer_content", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# _has_owner_answer
# ---------------------------------------------------------------------------

def test_has_owner_answer_no_answers_at_all():
    assert _has_owner_answer(_Q_UNANSWERED) is False


def test_has_owner_answer_merchant_in_top_answers():
    assert _has_owner_answer(_Q_OWNER_ANSWERED) is True


def test_has_owner_answer_regular_user_only():
    assert _has_owner_answer(_Q_USER_ANSWERED_ONLY) is False


def test_has_owner_answer_empty_top_answers_but_count_nonzero():
    q = {**_Q_UNANSWERED, "totalAnswerCount": 2, "topAnswers": []}
    assert _has_owner_answer(q) is False


def test_has_owner_answer_case_insensitive_merchant():
    q = {
        "totalAnswerCount": 1,
        "topAnswers": [{"author": {"type": "merchant"}}],
    }
    assert _has_owner_answer(q) is True


def test_has_owner_answer_missing_author_type():
    q = {
        "totalAnswerCount": 1,
        "topAnswers": [{"author": {}}],
    }
    assert _has_owner_answer(q) is False


# ---------------------------------------------------------------------------
# _extract_question_id
# ---------------------------------------------------------------------------

def test_extract_question_id_normal():
    assert _extract_question_id(_Q_UNANSWERED) == "q001"


def test_extract_question_id_empty_name():
    assert _extract_question_id({"name": ""}) == ""


def test_extract_question_id_missing_name():
    assert _extract_question_id({}) == ""


# ---------------------------------------------------------------------------
# _question_age_days
# ---------------------------------------------------------------------------

def test_question_age_days_recent_is_small():
    # A question created 1 hour ago should have age close to 0.
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    q = {"createTime": recent.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    age = _question_age_days(q)
    assert age is not None
    assert 0 <= age < 1


def test_question_age_days_old_is_large():
    q = {"createTime": "2020-01-01T00:00:00.000Z"}
    age = _question_age_days(q)
    assert age is not None
    assert age > 365


def test_question_age_days_with_offset():
    q = {"createTime": "2020-01-01T09:00:00+09:00"}
    age = _question_age_days(q)
    assert age is not None
    assert age > 365


def test_question_age_days_invalid_timestamp():
    assert _question_age_days({"createTime": "not-a-date"}) is None


def test_question_age_days_missing_create_time():
    assert _question_age_days({}) is None


# ---------------------------------------------------------------------------
# _qa_location_name (helper in business_profile)
# ---------------------------------------------------------------------------

def test_qa_location_name_full_path():
    assert _qa_location_name("accounts/123/locations/456") == "locations/456"


def test_qa_location_name_already_short():
    assert _qa_location_name("locations/456") == "locations/456"


def test_qa_location_name_no_locations_segment():
    assert _qa_location_name("accounts/123") == "accounts/123"


# ---------------------------------------------------------------------------
# run_qa_for_store — main integration logic
# ---------------------------------------------------------------------------

def test_dry_run_does_not_call_upsert_answer():
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_UNANSWERED]
    with patch("meo.qa.generate_answer", return_value="駐車場はございません。"):
        result = run_qa_for_store(_STORE, gbp, dry_run=True)
    gbp.upsert_answer.assert_not_called()
    assert result["answered"] == 1


def test_live_run_posts_answer():
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_UNANSWERED]
    gbp.upsert_answer.return_value = {"text": "駐車場はございません。"}
    with patch("meo.qa.generate_answer", return_value="駐車場はございません。"):
        result = run_qa_for_store(_STORE, gbp, dry_run=False)
    gbp.upsert_answer.assert_called_once_with(
        "locations/42/questions/q001", "駐車場はございません。"
    )
    assert result["answered"] == 1
    assert result["errors"] == []


def test_already_answered_by_owner_are_skipped():
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_OWNER_ANSWERED, _Q_UNANSWERED]
    with patch("meo.qa.generate_answer", return_value="テスト回答"):
        result = run_qa_for_store(_STORE, gbp, dry_run=True)
    assert result["skipped"] == 1
    assert result["answered"] == 1


def test_all_questions_answered_nothing_to_do():
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_OWNER_ANSWERED]
    result = run_qa_for_store(_STORE, gbp, dry_run=False)
    gbp.upsert_answer.assert_not_called()
    assert result["answered"] == 0
    assert result["skipped"] == 1


def test_empty_question_list():
    gbp = MagicMock()
    gbp.list_questions.return_value = []
    result = run_qa_for_store(_STORE, gbp, dry_run=False)
    assert result["answered"] == 0
    assert result["skipped"] == 0
    assert result["errors"] == []


def test_locally_answered_skip(monkeypatch):
    monkeypatch.setattr("meo.qa.get_answered_questions", lambda key: ["q001"])
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_UNANSWERED]
    result = run_qa_for_store(_STORE, gbp, dry_run=False)
    gbp.upsert_answer.assert_not_called()
    assert result["answered"] == 0


def test_age_filter_skips_old_questions():
    old_q = {**_Q_UNANSWERED, "createTime": "2000-01-01T00:00:00.000Z"}
    gbp = MagicMock()
    gbp.list_questions.return_value = [old_q]
    result = run_qa_for_store(_STORE, gbp, dry_run=False)
    gbp.upsert_answer.assert_not_called()
    assert result["answered"] == 0


def test_max_qa_per_run_cap():
    questions = [
        {**_Q_UNANSWERED, "name": f"locations/42/questions/q{i:03d}", "createTime": "2026-08-10T00:00:00.000Z"}
        for i in range(15)
    ]
    gbp = MagicMock()
    gbp.list_questions.return_value = questions
    gbp.upsert_answer.return_value = {"text": "回答"}
    with patch("meo.qa.generate_answer", return_value="回答"):
        result = run_qa_for_store(_STORE, gbp, dry_run=True)
    assert result["answered"] == 10   # default max_qa_per_run
    assert result["deferred"] == 5


def test_generate_answer_exception_is_recorded():
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_UNANSWERED]
    with patch("meo.qa.generate_answer", side_effect=RuntimeError("LLM down")):
        result = run_qa_for_store(_STORE, gbp, dry_run=False)
    assert result["answered"] == 0
    assert len(result["errors"]) == 1
    assert "q001" in result["errors"][0]


def test_upsert_answer_exception_is_recorded():
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_UNANSWERED]
    gbp.upsert_answer.side_effect = requests.HTTPError("403 Forbidden")
    with patch("meo.qa.generate_answer", return_value="回答テキスト"):
        result = run_qa_for_store(_STORE, gbp, dry_run=False)
    assert result["answered"] == 0
    assert len(result["errors"]) == 1


def test_user_only_answered_question_is_treated_as_unanswered():
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_USER_ANSWERED_ONLY]
    gbp.upsert_answer.return_value = {"text": "日曜日が定休日です。"}
    with patch("meo.qa.generate_answer", return_value="日曜日が定休日です。"):
        result = run_qa_for_store(_STORE, gbp, dry_run=False)
    assert result["answered"] == 1


def test_result_keys_are_all_present():
    gbp = MagicMock()
    gbp.list_questions.return_value = []
    result = run_qa_for_store(_STORE, gbp, dry_run=True)
    assert set(result.keys()) == {"store_key", "answered", "skipped", "deferred", "errors"}


def test_answered_question_recorded_in_live_run(monkeypatch):
    recorded: list[tuple] = []
    monkeypatch.setattr(
        "meo.qa.record_answered_question",
        lambda key, qid: recorded.append((key, qid)),
    )
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_UNANSWERED]
    gbp.upsert_answer.return_value = {"text": "回答"}
    with patch("meo.qa.generate_answer", return_value="回答"):
        run_qa_for_store(_STORE, gbp, dry_run=False)
    assert recorded == [("the_body_kyoto", "q001")]


def test_answered_question_not_recorded_in_dry_run(monkeypatch):
    recorded: list = []
    monkeypatch.setattr(
        "meo.qa.record_answered_question",
        lambda key, qid: recorded.append(qid),
    )
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_UNANSWERED]
    with patch("meo.qa.generate_answer", return_value="回答"):
        run_qa_for_store(_STORE, gbp, dry_run=True)
    assert recorded == []


def test_multiple_questions_answered_in_order():
    q2 = {**_Q_UNANSWERED, "name": "locations/42/questions/q002", "createTime": "2026-08-10T00:00:00.000Z"}
    gbp = MagicMock()
    gbp.list_questions.return_value = [_Q_UNANSWERED, q2]
    gbp.upsert_answer.return_value = {"text": "回答"}
    with patch("meo.qa.generate_answer", return_value="回答"):
        result = run_qa_for_store(_STORE, gbp, dry_run=False)
    assert result["answered"] == 2
    assert gbp.upsert_answer.call_count == 2


# ---------------------------------------------------------------------------
# BusinessProfileClient.list_questions / upsert_answer
# ---------------------------------------------------------------------------

def _ok(body: dict):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = body
    return resp


@pytest.fixture
def mock_session():
    session = MagicMock()
    with patch("meo.business_profile._AuthSession", return_value=session):
        yield session


@pytest.fixture
def client(mock_session):
    return BusinessProfileClient(MagicMock())


def test_list_questions_returns_flat_list(client, mock_session):
    mock_session.get.return_value = _ok({"questions": [_Q_UNANSWERED, _Q_OWNER_ANSWERED]})
    result = client.list_questions("accounts/1/locations/42")
    assert len(result) == 2


def test_list_questions_paginates(client, mock_session):
    page1 = _ok({"questions": [_Q_UNANSWERED], "nextPageToken": "tok123"})
    page2 = _ok({"questions": [_Q_OWNER_ANSWERED]})
    mock_session.get.side_effect = [page1, page2]
    result = client.list_questions("accounts/1/locations/42")
    assert len(result) == 2
    assert mock_session.get.call_count == 2


def test_list_questions_uses_correct_qa_url(client, mock_session):
    mock_session.get.return_value = _ok({"questions": []})
    client.list_questions("accounts/1/locations/42")
    url = mock_session.get.call_args.args[0]
    assert "mybusinessqanda.googleapis.com" in url
    assert "locations/42/questions" in url


def test_list_questions_empty(client, mock_session):
    mock_session.get.return_value = _ok({"questions": []})
    result = client.list_questions("accounts/1/locations/42")
    assert result == []


def test_list_questions_missing_questions_key(client, mock_session):
    mock_session.get.return_value = _ok({})
    result = client.list_questions("accounts/1/locations/42")
    assert result == []


def test_list_questions_http_error(client, mock_session):
    err_resp = MagicMock()
    err_resp.ok = False
    err_resp.status_code = 403
    err_resp.raise_for_status.side_effect = requests.HTTPError("403")
    err_resp.json.return_value = {"error": {"message": "PERMISSION_DENIED"}}
    mock_session.get.return_value = err_resp
    with pytest.raises(requests.HTTPError):
        client.list_questions("accounts/1/locations/42")


def test_upsert_answer_posts_correct_body(client, mock_session):
    mock_session.post.return_value = _ok({"text": "駐車場あります。"})
    result = client.upsert_answer("locations/42/questions/q001", "駐車場あります。")
    body = mock_session.post.call_args.kwargs["json"]
    assert body == {"answer": {"text": "駐車場あります。"}}
    assert result["text"] == "駐車場あります。"


def test_upsert_answer_uses_correct_url(client, mock_session):
    mock_session.post.return_value = _ok({"text": "回答"})
    client.upsert_answer("locations/42/questions/q001", "回答")
    url = mock_session.post.call_args.args[0]
    assert "mybusinessqanda.googleapis.com" in url
    assert "locations/42/questions/q001:upsertAnswer" in url


def test_upsert_answer_http_error(client, mock_session):
    err_resp = MagicMock()
    err_resp.ok = False
    err_resp.status_code = 404
    err_resp.raise_for_status.side_effect = requests.HTTPError("404")
    err_resp.json.return_value = {"error": {"message": "NOT_FOUND"}}
    mock_session.post.return_value = err_resp
    with pytest.raises(requests.HTTPError):
        client.upsert_answer("locations/42/questions/qX", "回答")


# ---------------------------------------------------------------------------
# State functions — record_answered_question / get_answered_questions /
#                  record_answer_content / get_answer_history
# ---------------------------------------------------------------------------

def test_record_answered_question_and_retrieve(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("meo.state._STATE_FILE", state_file)

    from meo.state import record_answered_question, get_answered_questions
    record_answered_question("the_body_kyoto", "q001")
    ids = get_answered_questions("the_body_kyoto")
    assert "q001" in ids


def test_get_answered_questions_empty(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("meo.state._STATE_FILE", state_file)

    from meo.state import get_answered_questions
    assert get_answered_questions("the_body_kyoto") == []


def test_record_answer_content_and_retrieve(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("meo.state._STATE_FILE", state_file)

    from meo.state import record_answer_content, get_answer_history
    record_answer_content(
        "the_body_kyoto", "q001", "駐車場はありますか？", "申し訳ございません、駐車場はありません。"
    )
    history = get_answer_history("the_body_kyoto")
    assert len(history) == 1
    assert history[0]["question_id"] == "q001"
    assert "駐車場" in history[0]["question"]
    assert "申し訳" in history[0]["answer"]


def test_get_answer_history_empty(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("meo.state._STATE_FILE", state_file)

    from meo.state import get_answer_history
    assert get_answer_history("the_body_kyoto") == []


# ---------------------------------------------------------------------------
# content.generate_answer
# ---------------------------------------------------------------------------

def test_generate_answer_calls_llm_and_returns_text():
    store = {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
    }
    with patch("meo.content._call_llm", return_value="駐車場はございません。") as mock_llm:
        from meo.content import generate_answer
        result = generate_answer("駐車場はありますか？", store)
    mock_llm.assert_called_once()
    assert result == "駐車場はございません。"


def test_generate_answer_truncates_to_max_chars():
    store = {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
    }
    long_text = "あ" * 2000
    with patch("meo.content._call_llm", return_value=long_text):
        from meo.content import generate_answer
        result = generate_answer("質問？", store)
    assert len(result) == 1000


def test_generate_answer_warns_on_banned_word(caplog):
    store = {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
    }
    import logging
    with patch("meo.content._call_llm", return_value="激安で試せます"):
        from meo.content import generate_answer
        with caplog.at_level(logging.WARNING, logger="meo.content"):
            generate_answer("値段は？", store)
    assert any("banned" in r.message.lower() or "激安" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# tools/qa.py — main() paths
# ---------------------------------------------------------------------------

_CONFIGURED_STORES = [
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
        "location_id": "accounts/1/locations/42",
        "drive_folder_id": "folder_abc",
    }
]


def _make_gbp_mock(questions=None):
    gbp = MagicMock(spec=BusinessProfileClient)
    gbp.list_questions.return_value = questions or []
    gbp.upsert_answer.return_value = {"text": "回答"}
    return gbp


def test_main_no_args_exits_0(monkeypatch):
    monkeypatch.setattr("sys.argv", ["meo-qa"])
    monkeypatch.setattr("meo.tools.qa.get_credentials", lambda: MagicMock())
    monkeypatch.setattr("meo.tools.qa.cfg.store_list", lambda: _CONFIGURED_STORES)
    gbp_mock = _make_gbp_mock()
    monkeypatch.setattr("meo.tools.qa.BusinessProfileClient", lambda c: gbp_mock)
    with patch("meo.tools.qa.run_qa_for_store", return_value={
        "answered": 0, "skipped": 0, "deferred": 0, "errors": []
    }):
        with pytest.raises(SystemExit) as exc_info:
            from meo.tools.qa import main
            main()
    assert exc_info.value.code == 0


def test_main_dry_run_exits_0(monkeypatch):
    monkeypatch.setattr("sys.argv", ["meo-qa", "--dry-run"])
    monkeypatch.setattr("meo.tools.qa.get_credentials", lambda: MagicMock())
    monkeypatch.setattr("meo.tools.qa.cfg.store_list", lambda: _CONFIGURED_STORES)
    gbp_mock = _make_gbp_mock()
    monkeypatch.setattr("meo.tools.qa.BusinessProfileClient", lambda c: gbp_mock)
    with patch("meo.tools.qa.run_qa_for_store", return_value={
        "answered": 1, "skipped": 0, "deferred": 0, "errors": []
    }):
        with pytest.raises(SystemExit) as exc_info:
            from meo.tools.qa import main
            main()
    assert exc_info.value.code == 0


def test_main_unknown_store_exits_1(monkeypatch):
    monkeypatch.setattr("sys.argv", ["meo-qa", "--store", "not_a_real_store"])
    with pytest.raises(SystemExit) as exc_info:
        from meo.tools.qa import main
        main()
    assert exc_info.value.code == 1


def test_main_auth_failure_exits_1(monkeypatch):
    monkeypatch.setattr("sys.argv", ["meo-qa"])
    monkeypatch.setattr("meo.tools.qa.cfg.store_list", lambda: _CONFIGURED_STORES)
    monkeypatch.setattr(
        "meo.tools.qa.get_credentials",
        lambda: (_ for _ in ()).throw(EnvironmentError("No token")),
    )
    with pytest.raises(SystemExit) as exc_info:
        from meo.tools.qa import main
        main()
    assert exc_info.value.code == 1


def test_main_with_errors_exits_1(monkeypatch):
    monkeypatch.setattr("sys.argv", ["meo-qa"])
    monkeypatch.setattr("meo.tools.qa.get_credentials", lambda: MagicMock())
    monkeypatch.setattr("meo.tools.qa.cfg.store_list", lambda: _CONFIGURED_STORES)
    gbp_mock = _make_gbp_mock()
    monkeypatch.setattr("meo.tools.qa.BusinessProfileClient", lambda c: gbp_mock)
    with patch("meo.tools.qa.run_qa_for_store", return_value={
        "answered": 0, "skipped": 0, "deferred": 0,
        "errors": ["Failed to answer question q001: HTTP Error"],
    }):
        with pytest.raises(SystemExit) as exc_info:
            from meo.tools.qa import main
            main()
    assert exc_info.value.code == 1


def test_main_list_only_exits_0(monkeypatch):
    monkeypatch.setattr("sys.argv", ["meo-qa", "--list-only"])
    monkeypatch.setattr("meo.tools.qa.get_credentials", lambda: MagicMock())
    monkeypatch.setattr("meo.tools.qa.cfg.store_list", lambda: _CONFIGURED_STORES)
    gbp_mock = _make_gbp_mock(questions=[_Q_UNANSWERED, _Q_OWNER_ANSWERED])
    monkeypatch.setattr("meo.tools.qa.BusinessProfileClient", lambda c: gbp_mock)
    with pytest.raises(SystemExit) as exc_info:
        from meo.tools.qa import main
        main()
    assert exc_info.value.code == 0


def test_main_exception_in_run_qa_exits_1(monkeypatch):
    monkeypatch.setattr("sys.argv", ["meo-qa"])
    monkeypatch.setattr("meo.tools.qa.get_credentials", lambda: MagicMock())
    monkeypatch.setattr("meo.tools.qa.cfg.store_list", lambda: _CONFIGURED_STORES)
    gbp_mock = _make_gbp_mock()
    monkeypatch.setattr("meo.tools.qa.BusinessProfileClient", lambda c: gbp_mock)
    with patch("meo.tools.qa.run_qa_for_store", side_effect=RuntimeError("Unexpected")):
        with pytest.raises(SystemExit) as exc_info:
            from meo.tools.qa import main
            main()
    assert exc_info.value.code == 1
