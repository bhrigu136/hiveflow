"""Wave 0 — the summarizer package.

The offline extractive engine is pure and deterministic, so it needs no app
context and no network. get_summarizer() is the plugin factory.
"""
import os

import pytest

from app.summarizer import get_summarizer
from app.summarizer.base import Summarizer
from app.summarizer.extractive import ExtractiveSummarizer

TRANSCRIPT = (
    "Alice: We agreed to ship the release on Friday. "
    "Bob: I will send the deck tomorrow. "
    "Alice: Carol should review the API by end of week."
)
ATTENDEES = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"},
             {"id": 3, "name": "Carol"}]

CONTRACT_KEYS = {"summary", "action_items", "decisions"}


@pytest.mark.unit
class TestContract:
    def test_empty_result_shape(self):
        assert set(Summarizer.empty_result()) == CONTRACT_KEYS

    def test_empty_result_values(self):
        r = Summarizer.empty_result()
        assert r["summary"] == ""
        assert r["action_items"] == []
        assert r["decisions"] == []

    def test_extractive_returns_contract_shape(self):
        r = ExtractiveSummarizer().summarize(TRANSCRIPT, attendees=ATTENDEES)
        assert set(r) == CONTRACT_KEYS
        assert isinstance(r["summary"], str)
        assert isinstance(r["action_items"], list)
        assert isinstance(r["decisions"], list)

    def test_base_summarize_is_abstract(self):
        with pytest.raises(NotImplementedError):
            Summarizer().summarize(TRANSCRIPT)


@pytest.mark.unit
class TestExtractive:
    def test_empty_transcript_gives_empty_result(self):
        r = ExtractiveSummarizer().summarize("", attendees=[])
        assert r["summary"] == ""
        assert r["action_items"] == []
        assert r["decisions"] == []

    def test_produces_some_output_for_real_transcript(self):
        r = ExtractiveSummarizer().summarize(TRANSCRIPT, attendees=ATTENDEES)
        # a non-trivial transcript should yield at least a summary or an item
        assert r["summary"] or r["action_items"] or r["decisions"]

    def test_action_items_are_dicts_with_text(self):
        r = ExtractiveSummarizer().summarize(TRANSCRIPT, attendees=ATTENDEES)
        for item in r["action_items"]:
            assert isinstance(item, dict)
            assert "text" in item

    def test_action_items_capped(self):
        # the extractive engine caps action items at 12
        many = " ".join(f"Person{i}: I will do task number {i} tomorrow." for i in range(40))
        r = ExtractiveSummarizer().summarize(many, attendees=[])
        assert len(r["action_items"]) <= 12

    def test_decisions_capped(self):
        many = " ".join(f"We decided point {i} is approved." for i in range(40))
        r = ExtractiveSummarizer().summarize(many, attendees=[])
        assert len(r["decisions"]) <= 8

    def test_deterministic(self):
        a = ExtractiveSummarizer().summarize(TRANSCRIPT, attendees=ATTENDEES)
        b = ExtractiveSummarizer().summarize(TRANSCRIPT, attendees=ATTENDEES)
        assert a == b

    def test_engine_name(self):
        assert ExtractiveSummarizer.name == "extractive"


@pytest.mark.unit
class TestFactory:
    def test_default_is_extractive(self):
        os.environ.pop("SUMMARIZER_ENGINE", None)
        assert isinstance(get_summarizer(), ExtractiveSummarizer)

    def test_unknown_engine_falls_back_to_extractive(self, monkeypatch):
        monkeypatch.setenv("SUMMARIZER_ENGINE", "does-not-exist")
        assert isinstance(get_summarizer(), ExtractiveSummarizer)

    def test_llm_without_config_falls_back(self, monkeypatch):
        # SUMMARIZER_ENGINE=llm but no LLM_BASE_URL -> construction fails ->
        # the factory returns the extractive engine rather than raising.
        monkeypatch.setenv("SUMMARIZER_ENGINE", "llm")
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        engine = get_summarizer()
        # either the extractive fallback, or an llm engine that will itself fall
        # back at call time — must never raise here
        assert engine is not None
