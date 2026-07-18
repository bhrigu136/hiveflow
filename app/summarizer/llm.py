"""Optional, opt-in LLM summarizer (same interface as the extractive default).

Enabled with `SUMMARIZER_ENGINE=llm` plus:
    LLM_BASE_URL   e.g. http://localhost:11434/v1   (Ollama, OpenAI-compatible)
                   or   https://api.groq.com/openai/v1
    LLM_MODEL      e.g. llama3.2:3b  /  llama-3.1-8b-instant  /  gpt-4o-mini
    LLM_API_KEY    (optional for local Ollama)

It calls any OpenAI-compatible /chat/completions endpoint using the `requests`
library already in requirements.txt — so true zero-cost is possible by pointing
it at a self-hosted Ollama. If anything goes wrong (not configured, timeout, bad
JSON) it RAISES, and the factory falls back to the extractive engine, so a
meeting never fails to produce notes.
"""
import json
import os
import re

import requests

from .base import Summarizer
from . import common

_TIMEOUT = 30  # seconds — local models can be slow on first token

_SYSTEM = (
    "You summarize a team meeting transcript. Reply with STRICT JSON only, no prose, "
    "no code fences. Schema: {\"summary\": string, \"action_items\": "
    "[{\"text\": string, \"assignee_name\": string|null, \"due_label\": string|null}], "
    "\"decisions\": [string]}. action_items are concrete tasks someone must do. "
    "assignee_name must be a person named in the transcript or null. "
    "due_label is a short phrase like 'Friday' or 'tomorrow' or null."
)


class LLMSummarizer(Summarizer):
    name = "llm"

    def __init__(self):
        self.base_url = os.environ.get('LLM_BASE_URL', '').rstrip('/')
        self.model = os.environ.get('LLM_MODEL', '')
        self.api_key = os.environ.get('LLM_API_KEY', '')
        if not self.base_url or not self.model:
            raise RuntimeError('LLM summarizer not configured (LLM_BASE_URL / LLM_MODEL)')

    def summarize(self, transcript, attendees=None, meeting_start=None):
        raw = self._chat(transcript)
        data = self._parse_json(raw)
        return self._normalize(data, attendees, meeting_start)

    def _chat(self, transcript):
        # Bound the transcript so a marathon meeting can't blow the context window.
        clipped = transcript[-12000:]
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        body = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': _SYSTEM},
                {'role': 'user', 'content': clipped},
            ],
            'temperature': 0.2,
            'stream': False,
        }
        resp = requests.post(f'{self.base_url}/chat/completions',
                             headers=headers, json=body, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']

    def _parse_json(self, content):
        content = content.strip()
        # Strip ```json ... ``` fences if the model added them.
        content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content, flags=re.I).strip()
        # Grab the outermost {...} in case the model wrapped it in text.
        start, end = content.find('{'), content.rfind('}')
        if start != -1 and end != -1:
            content = content[start:end + 1]
        return json.loads(content)

    def _normalize(self, data, attendees, meeting_start):
        name_index = common.build_name_index(attendees)
        result = self.empty_result()
        result['summary'] = (data.get('summary') or '').strip()
        result['decisions'] = [str(d).strip()[:200] for d in (data.get('decisions') or []) if str(d).strip()][:8]

        items = []
        for raw in (data.get('action_items') or [])[:12]:
            text = (raw.get('text') or '').strip()
            if not text:
                continue
            assignee = None
            aname = (raw.get('assignee_name') or '').strip()
            if aname:
                assignee = name_index.get(common.first_name(aname).lower())
            label = (raw.get('due_label') or '')
            due_hint, due_label = common.parse_due(f"{label} {text}", meeting_start)
            items.append({
                "text": text[:140],
                "suggested_assignee_id": assignee['id'] if assignee else None,
                "suggested_assignee_name": assignee['name'] if assignee else (aname or None),
                "due_hint": due_hint,
                "due_label": due_label or (label or None),
                "source_quote": text,
            })
        result['action_items'] = items
        return result
