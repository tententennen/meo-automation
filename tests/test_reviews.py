"""Tests for review reply flow — fully mocked."""

from unittest.mock import MagicMock, patch
import pytest

from meo.reviews import run_reviews_for_store, _has_reply, _extract_review_id, _star_to_int


@pytest.fixture(autouse=True)
def patch_record_reply_content(monkeypatch):
    """Silence record_reply_content for all tests — archiving is tested in test_state.py."""
    monkeypatch.setattr("meo.reviews.record_reply_content", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def patch_replied_review_state(monkeypatch):
    """Silence replied-review state I/O for all tests — guard is tested separately."""
    monkeypatch.setattr("meo.reviews.get_replied_reviews", lambda *a: [])
    monkeypatch.setattr("meo.reviews.record_replied_review", lambda *a: None)


@pytest.fixture(autouse=True)
def patch_record_held_reviews(monkeypatch):
    """Silence record_held_reviews for all tests — snapshot is tested in test_state.py."""
    monkeypatch.setattr("meo.reviews.record_held_reviews", lambda *a, **kw: None)


_STORE = {
    "key": "the_body_osaka_shinsaibashi",
    "name": "THE BODY 大阪 心斎橋店",
    "industry": "beauty_salon",
    "location_id": "accounts/1/locations/1",
    "drive_folder_id": "folder_xyz",
}

_REVIEW_UNREPLIED = {
    "name": "accounts/1/locations/1/reviews/rev001",
    "reviewId": "rev001",
    "reviewer": {"displayName": "山田花子"},
    "starRating": "FOUR",
    "comment": "とても良かったです！",
}

_REVIEW_WITH_REPLY = {
    "name": "accounts/1/locations/1/reviews/rev002",
    "reviewId": "rev002",
    "reviewer": {"displayName": "鈴木一郎"},
    "starRating": "FIVE",
    "comment": "最高でした。",
    "reviewReply": {"comment": "ありがとうございます！"},
}


def test_has_reply_true():
    assert _has_reply(_REVIEW_WITH_REPLY) is True


def test_has_reply_false():
    assert _has_reply(_REVIEW_UNREPLIED) is False


def test_extract_review_id():
    assert _extract_review_id(_REVIEW_UNREPLIED) == "rev001"


def test_dry_run_does_not_post_reply():
    gbp = MagicMock()
    gbp.list_reviews.return_value = [_REVIEW_UNREPLIED, _REVIEW_WITH_REPLY]
    with patch("meo.reviews.generate_reply", return_value="ありがとうございます！"):
        result = run_reviews_for_store(_STORE, gbp, dry_run=True)
    gbp.reply_to_review.assert_not_called()
    assert result["replied"] == 1
    assert result["skipped"] == 1


def test_live_run_replies_to_unreplied():
    gbp = MagicMock()
    gbp.list_reviews.return_value = [_REVIEW_UNREPLIED, _REVIEW_WITH_REPLY]
    gbp.reply_to_review.return_value = {"comment": "返信しました。"}
    with patch("meo.reviews.generate_reply", return_value="返信テスト"):
        result = run_reviews_for_store(_STORE, gbp, dry_run=False)
    gbp.reply_to_review.assert_called_once_with(
        _STORE["location_id"], "rev001", "返信テスト"
    )
    assert result["replied"] == 1
    assert result["errors"] == []


def test_reply_error_is_isolated():
    gbp = MagicMock()
    gbp.list_reviews.return_value = [_REVIEW_UNREPLIED]
    gbp.reply_to_review.side_effect = Exception("API error")
    with patch("meo.reviews.generate_reply", return_value="返信"):
        result = run_reviews_for_store(_STORE, gbp, dry_run=False)
    assert result["replied"] == 0
    assert len(result["errors"]) == 1


def test_max_replies_per_run_limits_replies():
    gbp = MagicMock()
    gbp.list_reviews.return_value = [
        {
            "name": f"accounts/1/locations/1/reviews/rev{i:03d}",
            "reviewId": f"rev{i:03d}",
            "reviewer": {"displayName": f"User{i}"},
            "starRating": "FIVE",
            "comment": f"Great! {i}",
        }
        for i in range(5)
    ]
    gbp.reply_to_review.return_value = {}
    with patch("meo.reviews.generate_reply", return_value="返信") as mock_gen, \
         patch("meo.config.content", return_value={"defaults": {"max_replies_per_run": 2}}):
        result = run_reviews_for_store(_STORE, gbp, dry_run=False)
    assert result["replied"] == 2
    assert mock_gen.call_count == 2
    assert gbp.reply_to_review.call_count == 2
    # 5 unreplied total, cap=2 → 3 deferred to next run, 0 already-replied (skipped)
    assert result["deferred"] == 3
    assert result["skipped"] == 0


def test_skipped_counts_only_already_replied():
    """skipped must reflect already-replied reviews, not deferred ones."""
    gbp = MagicMock()
    already_replied = {
        "name": "accounts/1/locations/1/reviews/rev999",
        "reviewId": "rev999",
        "reviewer": {"displayName": "既返信"},
        "starRating": "FIVE",
        "comment": "良い",
        "reviewReply": {"comment": "ありがとう"},
    }
    unreplied_reviews = [
        {
            "name": f"accounts/1/locations/1/reviews/rev{i:03d}",
            "reviewId": f"rev{i:03d}",
            "reviewer": {"displayName": f"User{i}"},
            "starRating": "FIVE",
            "comment": f"Great! {i}",
        }
        for i in range(4)
    ]
    gbp.list_reviews.return_value = unreplied_reviews + [already_replied]
    gbp.reply_to_review.return_value = {}
    with patch("meo.reviews.generate_reply", return_value="返信"), \
         patch("meo.config.content", return_value={"defaults": {"max_replies_per_run": 2}}):
        result = run_reviews_for_store(_STORE, gbp, dry_run=False)
    # 5 total, 4 unreplied (cap=2 → 2 deferred), 1 already-replied
    assert result["skipped"] == 1
    assert result["deferred"] == 2
    assert result["replied"] == 2


# ---------------------------------------------------------------------------
# Content archiving test
# ---------------------------------------------------------------------------

def test_record_reply_content_called_after_live_reply():
    """record_reply_content must be called with correct args after a live reply."""
    gbp = MagicMock()
    gbp.list_reviews.return_value = [_REVIEW_UNREPLIED]
    gbp.reply_to_review.return_value = {}
    with patch("meo.reviews.generate_reply", return_value="テスト返信"), \
         patch("meo.reviews.record_reply_content") as mock_archive:
        run_reviews_for_store(_STORE, gbp, dry_run=False)

    mock_archive.assert_called_once()
    args = mock_archive.call_args.args
    assert args[0] == _STORE["key"]
    assert args[1] == "rev001"
    assert args[2] == "山田花子"
    assert args[3] == "FOUR"
    assert args[4] == "テスト返信"


def test_record_reply_content_not_called_on_dry_run():
    """Dry run must not archive any reply content."""
    gbp = MagicMock()
    gbp.list_reviews.return_value = [_REVIEW_UNREPLIED]
    with patch("meo.reviews.generate_reply", return_value="返信"), \
         patch("meo.reviews.record_reply_content") as mock_archive:
        run_reviews_for_store(_STORE, gbp, dry_run=True)

    mock_archive.assert_not_called()


# ---------------------------------------------------------------------------
# Duplicate-reply guard tests
# ---------------------------------------------------------------------------

def test_locally_replied_review_is_skipped():
    """A review already in the local replied set must not be replied to again."""
    gbp = MagicMock()
    gbp.list_reviews.return_value = [_REVIEW_UNREPLIED]  # GBP still shows it unreplied
    with patch("meo.reviews.generate_reply", return_value="返信"), \
         patch("meo.reviews.get_replied_reviews", return_value=["rev001"]):
        result = run_reviews_for_store(_STORE, gbp, dry_run=False)
    gbp.reply_to_review.assert_not_called()
    assert result["replied"] == 0


def test_record_replied_review_called_after_live_reply():
    """record_replied_review must be called with store_key and review_id after a live reply."""
    gbp = MagicMock()
    gbp.list_reviews.return_value = [_REVIEW_UNREPLIED]
    gbp.reply_to_review.return_value = {}
    with patch("meo.reviews.generate_reply", return_value="返信テスト"), \
         patch("meo.reviews.record_replied_review") as mock_guard:
        run_reviews_for_store(_STORE, gbp, dry_run=False)
    mock_guard.assert_called_once_with(_STORE["key"], "rev001")


def test_record_replied_review_not_called_on_dry_run():
    """Dry run must not update the local replied-review set."""
    gbp = MagicMock()
    gbp.list_reviews.return_value = [_REVIEW_UNREPLIED]
    with patch("meo.reviews.generate_reply", return_value="返信"), \
         patch("meo.reviews.record_replied_review") as mock_guard:
        run_reviews_for_store(_STORE, gbp, dry_run=True)
    mock_guard.assert_not_called()


# ---------------------------------------------------------------------------
# Star-threshold (min_star_autoreply) tests
# ---------------------------------------------------------------------------

def test_star_to_int_known_values():
    assert _star_to_int("ONE") == 1
    assert _star_to_int("TWO") == 2
    assert _star_to_int("THREE") == 3
    assert _star_to_int("FOUR") == 4
    assert _star_to_int("FIVE") == 5


def test_star_to_int_unknown_defaults_to_three():
    assert _star_to_int("") == 3
    assert _star_to_int("UNKNOWN") == 3


def test_low_star_review_held_for_manual_when_threshold_set():
    """A 1★ review must not be auto-replied when min_star_autoreply=3."""
    gbp = MagicMock()
    low_star_review = {
        "name": "accounts/1/locations/1/reviews/rev_low",
        "reviewId": "rev_low",
        "reviewer": {"displayName": "不満なお客様"},
        "starRating": "ONE",
        "comment": "最悪でした。",
    }
    gbp.list_reviews.return_value = [low_star_review, _REVIEW_UNREPLIED]  # FOUR = above threshold
    gbp.reply_to_review.return_value = {}
    conf = {"defaults": {"max_replies_per_run": 10, "min_star_autoreply": 3}}
    with patch("meo.reviews.generate_reply", return_value="返信") as mock_gen, \
         patch("meo.config.content", return_value=conf):
        result = run_reviews_for_store(_STORE, gbp, dry_run=False)
    # Only the FOUR-star review should have been replied to
    assert result["replied"] == 1
    assert result["manual"] == 1
    assert mock_gen.call_count == 1  # only called for the FOUR-star review


def test_manual_zero_when_threshold_is_one():
    """Default threshold (1) means all unreplied reviews are auto-replied; manual==0."""
    gbp = MagicMock()
    low_star_review = {
        "name": "accounts/1/locations/1/reviews/rev_low",
        "reviewId": "rev_low",
        "reviewer": {"displayName": "不満なお客様"},
        "starRating": "ONE",
        "comment": "最悪でした。",
    }
    gbp.list_reviews.return_value = [low_star_review]
    gbp.reply_to_review.return_value = {}
    conf = {"defaults": {"max_replies_per_run": 10, "min_star_autoreply": 1}}
    with patch("meo.reviews.generate_reply", return_value="返信"), \
         patch("meo.config.content", return_value=conf):
        result = run_reviews_for_store(_STORE, gbp, dry_run=False)
    assert result["manual"] == 0
    assert result["replied"] == 1


def test_all_reviews_held_when_all_below_threshold():
    """When every unreplied review is below the threshold, replied==0, manual==N."""
    gbp = MagicMock()
    reviews = [
        {
            "name": f"accounts/1/locations/1/reviews/rev{i}",
            "reviewId": f"rev{i}",
            "reviewer": {"displayName": f"User{i}"},
            "starRating": "TWO",
            "comment": f"Bad {i}",
        }
        for i in range(3)
    ]
    gbp.list_reviews.return_value = reviews
    gbp.reply_to_review.return_value = {}
    conf = {"defaults": {"max_replies_per_run": 10, "min_star_autoreply": 4}}
    with patch("meo.reviews.generate_reply", return_value="返信") as mock_gen, \
         patch("meo.config.content", return_value=conf):
        result = run_reviews_for_store(_STORE, gbp, dry_run=False)
    assert result["replied"] == 0
    assert result["manual"] == 3
    mock_gen.assert_not_called()
    gbp.reply_to_review.assert_not_called()


# ---------------------------------------------------------------------------
# Per-store override tests
# ---------------------------------------------------------------------------

def test_per_store_max_replies_override():
    """A store with overrides.max_replies_per_run caps at the per-store value, not the global."""
    store_with_override = {**_STORE, "overrides": {"max_replies_per_run": 1}}
    gbp = MagicMock()
    gbp.list_reviews.return_value = [
        {
            "name": f"accounts/1/locations/1/reviews/rev{i:03d}",
            "reviewId": f"rev{i:03d}",
            "reviewer": {"displayName": f"User{i}"},
            "starRating": "FIVE",
            "comment": f"Good {i}",
        }
        for i in range(3)
    ]
    with patch("meo.reviews.generate_reply", return_value="返信"):
        result = run_reviews_for_store(store_with_override, gbp, dry_run=True)
    assert result["replied"] == 1
    assert result["deferred"] == 2


def test_per_store_min_star_override():
    """A store with overrides.min_star_autoreply holds low-rated reviews for manual handling."""
    store_with_override = {**_STORE, "overrides": {"min_star_autoreply": 4}}
    gbp = MagicMock()
    low_star = {
        "name": "accounts/1/locations/1/reviews/rev_low",
        "reviewId": "rev_low",
        "reviewer": {"displayName": "不満"},
        "starRating": "TWO",
        "comment": "まあまあ",
    }
    gbp.list_reviews.return_value = [low_star]
    with patch("meo.reviews.generate_reply", return_value="返信") as mock_gen:
        result = run_reviews_for_store(store_with_override, gbp, dry_run=False)
    assert result["replied"] == 0
    assert result["manual"] == 1
    mock_gen.assert_not_called()


# ---------------------------------------------------------------------------
# Held review snapshot tests
# ---------------------------------------------------------------------------

_LOW_STAR_REVIEW = {
    "name": "accounts/1/locations/1/reviews/rev_low",
    "reviewId": "rev_low",
    "reviewer": {"displayName": "不満なお客様"},
    "starRating": "ONE",
    "comment": "残念でした。",
}


def test_record_held_reviews_called_with_manual_reviews():
    """record_held_reviews must be called with pre-processed snapshot when min_star>1 and live."""
    gbp = MagicMock()
    gbp.list_reviews.return_value = [_LOW_STAR_REVIEW]
    gbp.reply_to_review.return_value = {}
    conf = {"defaults": {"max_replies_per_run": 10, "min_star_autoreply": 3}}
    with patch("meo.reviews.generate_reply", return_value="返信"), \
         patch("meo.config.content", return_value=conf), \
         patch("meo.reviews.record_held_reviews") as mock_held:
        run_reviews_for_store(_STORE, gbp, dry_run=False)
    mock_held.assert_called_once()
    store_key_arg, snapshots_arg = mock_held.call_args.args
    assert store_key_arg == _STORE["key"]
    assert len(snapshots_arg) == 1
    assert snapshots_arg[0]["review_id"] == "rev_low"
    assert snapshots_arg[0]["stars"] == "ONE"
    assert snapshots_arg[0]["reviewer"] == "不満なお客様"


def test_record_held_reviews_not_called_in_dry_run():
    """Dry run must not persist the held-review snapshot."""
    gbp = MagicMock()
    gbp.list_reviews.return_value = [_LOW_STAR_REVIEW]
    conf = {"defaults": {"max_replies_per_run": 10, "min_star_autoreply": 3}}
    with patch("meo.reviews.generate_reply", return_value="返信"), \
         patch("meo.config.content", return_value=conf), \
         patch("meo.reviews.record_held_reviews") as mock_held:
        run_reviews_for_store(_STORE, gbp, dry_run=True)
    mock_held.assert_not_called()


def test_record_held_reviews_called_with_empty_list_when_all_resolved():
    """When min_star>1 but no reviews are below threshold, snapshot is cleared (empty list)."""
    gbp = MagicMock()
    high_star_review = {**_REVIEW_UNREPLIED, "starRating": "FIVE"}
    gbp.list_reviews.return_value = [high_star_review]
    gbp.reply_to_review.return_value = {}
    conf = {"defaults": {"max_replies_per_run": 10, "min_star_autoreply": 3}}
    with patch("meo.reviews.generate_reply", return_value="返信"), \
         patch("meo.config.content", return_value=conf), \
         patch("meo.reviews.record_held_reviews") as mock_held:
        run_reviews_for_store(_STORE, gbp, dry_run=False)
    mock_held.assert_called_once()
    _, snapshots_arg = mock_held.call_args.args
    assert snapshots_arg == []
