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
