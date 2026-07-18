"""Pluggable meeting summarizer.

`get_summarizer()` returns the engine selected by the SUMMARIZER_ENGINE env var
(default 'extractive'). The LLM engine is opt-in and self-healing: if it isn't
configured or fails to construct, we silently fall back to the always-available
extractive engine so meeting notes are never blocked on external infrastructure.
"""
import os


def get_summarizer():
    engine = os.environ.get('SUMMARIZER_ENGINE', 'extractive').strip().lower()
    if engine == 'llm':
        try:
            from .llm import LLMSummarizer
            return LLMSummarizer()
        except Exception:
            pass  # not configured / unavailable → use the free default
    from .extractive import ExtractiveSummarizer
    return ExtractiveSummarizer()
