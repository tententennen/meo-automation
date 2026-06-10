"""Tests for config loading."""

import pytest
from meo import config as cfg


def test_stores_returns_three_stores():
    stores = cfg.stores()
    assert set(stores.keys()) == {
        "the_body_osaka_shinsaibashi",
        "the_body_kyoto",
        "mybear_studio_kyoto",
    }


def test_store_list_has_key_field():
    for store in cfg.store_list():
        assert "key" in store
        assert "name" in store
        assert "location_id" in store
        assert "drive_folder_id" in store


def test_content_has_required_keys():
    conf = cfg.content()
    assert "defaults" in conf
    assert "industry_tones" in conf
    assert "llm" in conf
    assert conf["defaults"]["language"] == "ja"


def test_content_industry_tones():
    conf = cfg.content()
    for industry in ("beauty_salon", "fitness_studio"):
        assert industry in conf["industry_tones"]
        tone = conf["industry_tones"][industry]
        assert "tone" in tone
        assert "themes" in tone


# ---------------------------------------------------------------------------
# effective_defaults — per-store override merging
# ---------------------------------------------------------------------------

def test_effective_defaults_returns_global_defaults_when_no_overrides():
    store = {"key": "store_a", "name": "A", "industry": "beauty_salon"}
    defaults = cfg.effective_defaults(store)
    global_defaults = cfg.content()["defaults"]
    assert defaults["post_cadence_days"] == global_defaults["post_cadence_days"]
    assert defaults["max_post_chars"] == global_defaults["max_post_chars"]


def test_effective_defaults_merges_store_overrides():
    store = {
        "key": "store_a",
        "name": "A",
        "industry": "beauty_salon",
        "overrides": {"post_cadence_days": 3, "min_star_autoreply": 4},
    }
    defaults = cfg.effective_defaults(store)
    assert defaults["post_cadence_days"] == 3
    assert defaults["min_star_autoreply"] == 4
    # Keys not overridden retain global values
    assert defaults["max_post_chars"] == cfg.content()["defaults"]["max_post_chars"]


def test_effective_defaults_does_not_mutate_global_config():
    original_cadence = cfg.content()["defaults"]["post_cadence_days"]
    store = {"key": "store_a", "overrides": {"post_cadence_days": 99}}
    cfg.effective_defaults(store)
    # Global default must be unchanged after the call
    assert cfg.content()["defaults"]["post_cadence_days"] == original_cadence
