"""Tests for meo._text_utils — truncation and similarity helpers."""

import pytest

from meo._text_utils import (
    truncate_at_sentence,
    char_bigrams,
    jaccard_similarity,
    most_similar_entry,
)


class TestTruncateAtSentence:
    def test_short_text_returned_unchanged(self):
        assert truncate_at_sentence("短い文章です。", 100) == "短い文章です。"

    def test_exact_length_returned_unchanged(self):
        text = "ちょうど5文字"  # 7 chars
        assert truncate_at_sentence(text, 7) == text

    def test_truncates_after_last_maru_in_window(self):
        # 「春です。夏です。秋です。」 — max_chars=9 includes up to the second 。
        text = "春です。夏です。秋です。"
        result = truncate_at_sentence(text, 9)
        assert result == "春です。夏です。"

    def test_truncates_after_exclamation(self):
        text = "いらっしゃいませ！本日も元気に営業中です！お待ちしています！"
        # first ！ is at index 8 (0-based: index 7)
        result = truncate_at_sentence(text, 12)
        assert result.endswith("！")
        assert len(result) <= 12

    def test_truncates_after_question_mark(self):
        # "ご来店いただけますか？" is 11 chars; set max_chars=13 so ？ is in the window
        text = "ご来店いただけますか？詳しくはこちらへ"
        result = truncate_at_sentence(text, 13)
        assert result == "ご来店いただけますか？"

    def test_hard_slice_when_no_sentence_end_in_window(self):
        # No sentence-ending punctuation; should fall back to hard slice
        text = "ABCDEFGHIJKLMNOP"
        assert truncate_at_sentence(text, 5) == "ABCDE"

    def test_empty_string_returned_unchanged(self):
        assert truncate_at_sentence("", 10) == ""

    def test_single_char_returned_unchanged(self):
        assert truncate_at_sentence("あ", 10) == "あ"

    def test_sentence_end_at_exactly_max_chars(self):
        # 。is at position max_chars-1 (0-based), which is the last char of the window
        text = "春です。夏です"  # 。 at index 3 (4th char)
        # max_chars=4 — window is "春です。"
        assert truncate_at_sentence(text, 4) == "春です。"

    def test_multiple_sentence_ends_picks_last_in_window(self):
        text = "春。夏。秋。冬。年中無休"
        result = truncate_at_sentence(text, 7)
        # chars: 春。夏。秋。冬 — last 。 before index 7 is at index 5 (秋。)
        assert result == "春。夏。秋。"
        assert len(result) == 6

    def test_unicode_japanese_punctuation_variants(self):
        # All three sentence-ending characters should work
        for punct in ["。", "！", "？"]:
            text = f"テスト{punct}続き部分"
            result = truncate_at_sentence(text, 5)
            assert result.endswith(punct)


class TestCharBigrams:
    def test_empty_string_returns_empty_frozenset(self):
        assert char_bigrams("") == frozenset()

    def test_single_char_returns_empty_frozenset(self):
        assert char_bigrams("a") == frozenset()

    def test_two_chars_returns_one_bigram(self):
        assert char_bigrams("ab") == frozenset({"ab"})

    def test_three_chars_returns_two_bigrams(self):
        assert char_bigrams("abc") == frozenset({"ab", "bc"})

    def test_duplicate_bigrams_deduplicated(self):
        # "abab" has bigrams ab, ba, ab → {ab, ba}
        assert char_bigrams("abab") == frozenset({"ab", "ba"})

    def test_japanese_text(self):
        bg = char_bigrams("春です")
        assert "春で" in bg
        assert "です" in bg

    def test_returns_frozenset(self):
        result = char_bigrams("test")
        assert isinstance(result, frozenset)


class TestJaccardSimilarity:
    def test_identical_strings_return_one(self):
        assert jaccard_similarity("春です。", "春です。") == pytest.approx(1.0)

    def test_completely_different_strings_return_zero(self):
        # No overlapping bigrams
        assert jaccard_similarity("あいう", "えおか") == pytest.approx(0.0)

    def test_both_empty_returns_one(self):
        assert jaccard_similarity("", "") == pytest.approx(1.0)

    def test_one_empty_one_nonempty_returns_zero(self):
        assert jaccard_similarity("", "abc") == pytest.approx(0.0)
        assert jaccard_similarity("abc", "") == pytest.approx(0.0)

    def test_single_char_strings_with_no_bigrams_and_nonempty_returns_zero(self):
        # single char → no bigrams → one empty set, one empty set → 1.0
        assert jaccard_similarity("a", "a") == pytest.approx(1.0)

    def test_partial_overlap_between_zero_and_one(self):
        sim = jaccard_similarity("春です。夏", "春です。秋")
        assert 0.0 < sim < 1.0

    def test_symmetry(self):
        a = "今週のスタッフおすすめメニューをご紹介します。"
        b = "本日のおすすめメニューはこちらです。"
        assert jaccard_similarity(a, b) == pytest.approx(jaccard_similarity(b, a))

    def test_result_between_zero_and_one(self):
        sim = jaccard_similarity("abcdef", "abcxyz")
        assert 0.0 <= sim <= 1.0

    def test_one_char_vs_multiple_char_returns_zero(self):
        # "a" → no bigrams; "ab" → {"ab"} → union = {"ab"}, intersection = 0 → 0.0
        assert jaccard_similarity("a", "ab") == pytest.approx(0.0)


class TestMostSimilarEntry:
    def _entry(self, text: str) -> dict:
        return {"text": text}

    def test_empty_history_returns_zero_and_empty_string(self):
        sim, snippet = most_similar_entry("テスト", [])
        assert sim == pytest.approx(0.0)
        assert snippet == ""

    def test_single_identical_entry_returns_one(self):
        text = "春のキャンペーン開催中です。"
        sim, snippet = most_similar_entry(text, [self._entry(text)])
        assert sim == pytest.approx(1.0)
        assert snippet == text[:60]

    def test_returns_highest_similarity_across_multiple_entries(self):
        target = "今週のおすすめメニューをご紹介します。"
        history = [
            self._entry("全く異なる内容のテキストです。"),
            self._entry("今週のおすすめメニューをご紹介します。とても人気です。"),  # most similar
            self._entry("別のテキストです。"),
        ]
        sim, snippet = most_similar_entry(target, history)
        assert sim > 0.5
        assert "今週のおすすめ" in snippet

    def test_snippet_capped_at_60_chars(self):
        long_text = "あ" * 100
        _, snippet = most_similar_entry(long_text, [self._entry(long_text)])
        assert len(snippet) == 60

    def test_short_text_snippet_not_truncated(self):
        short_text = "短い"
        _, snippet = most_similar_entry(short_text, [self._entry(short_text)])
        assert snippet == "短い"

    def test_entries_without_text_field_are_skipped(self):
        sim, snippet = most_similar_entry("テスト", [{"date": "2026-01-01"}])
        assert sim == pytest.approx(0.0)
        assert snippet == ""

    def test_entries_with_empty_text_are_skipped(self):
        sim, snippet = most_similar_entry("テスト", [{"text": ""}])
        assert sim == pytest.approx(0.0)
        assert snippet == ""

    def test_mixed_valid_and_empty_entries(self):
        target = "春のおすすめメニュー"
        history = [
            {"text": ""},
            {"date": "2026-01-01"},
            self._entry("春のおすすめメニューです！"),
        ]
        sim, snippet = most_similar_entry(target, history)
        assert sim > 0.0
        assert "春のおすすめ" in snippet

    def test_custom_field_reply_reads_reply_key(self):
        """field='reply' reads the 'reply' key, not 'text'."""
        reply_text = "ご来店いただきありがとうございます。またのご来店をお待ちしております。"
        entry = {"date": "2026-07-20", "reply": reply_text}
        sim, snippet = most_similar_entry(reply_text, [entry], field="reply")
        assert sim == pytest.approx(1.0)
        assert reply_text[:60] in snippet

    def test_custom_field_reply_ignores_text_key(self):
        """field='reply' must not match on the 'text' key."""
        entry = {"text": "今週のおすすめです。", "reply": "全く異なる内容です。"}
        sim, snippet = most_similar_entry("今週のおすすめです。", [entry], field="reply")
        assert sim < 0.5

    def test_custom_field_answer_reads_answer_key(self):
        """field='answer' reads the 'answer' key, not 'text'."""
        answer_text = "営業時間は10時から20時です。お気軽にお越しください。"
        entry = {"date": "2026-07-20", "answer": answer_text}
        sim, snippet = most_similar_entry(answer_text, [entry], field="answer")
        assert sim == pytest.approx(1.0)
        assert answer_text[:60] in snippet

    def test_custom_field_answer_missing_returns_zero(self):
        """field='answer' on an entry without 'answer' key returns 0.0."""
        entry = {"text": "なにかの投稿です。", "reply": "ありがとうございます。"}
        sim, snippet = most_similar_entry("なにかの投稿です。", [entry], field="answer")
        assert sim == pytest.approx(0.0)
        assert snippet == ""
