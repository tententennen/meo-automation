"""Tests for review reply flow — fully mocked."""

from unittest.mock import MagicMock, patch
import pytest

from meo.reviews import run_reviews_for_store, _has_reply, _extract_review_id


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
