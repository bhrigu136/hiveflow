"""The default, 100%-free summarizer.

Pure Python, standard library only, no model downloads, no external calls — so
it runs anywhere (including Render's free tier) in well under a second and keeps
meeting content private. It does three things:

  • Summary       — frequency-scored extractive summary (TextRank-lite).
  • Action items  — cue-phrase detection ("I'll …", "can you …", "we need to …")
                    with assignee inference (speaker for commitments, the
                    addressed person for delegations) and a due-date guess.
  • Decisions     — sentences that sound like a settled decision.

It is intentionally conservative: the organizer reviews and edits everything on
the review screen before any task is created, so recall matters more than
precision here.
"""
import re

from .base import Summarizer
from . import common

_COMMIT = re.compile(
    r"\b(i'?ll|i will|i'?m going to|i am going to|let me|i'?ll go|i can take|i'?ve got|i got this|on it|i'?ll handle)\b",
    re.I,
)
_DELEGATE = re.compile(
    r"\b(can you|could you|can we|would you|please|we need to|we have to|we should|"
    r"you (?:should|need to|have to|must)|let'?s|make sure|don'?t forget|follow up|"
    r"action item|action:|to-?do|next step)\b",
    re.I,
)
_DECISION = re.compile(
    r"\b(we (?:decided|agreed|will go with|chose|concluded|settled on)|"
    r"decision is|it'?s decided|let'?s go with|we'?ll go with|finali[sz]e|"
    r"finali[sz]ed|signed off|sign off on|agreed to)\b",
    re.I,
)

_MAX_ACTION_ITEMS = 12
_MAX_DECISIONS = 8


class ExtractiveSummarizer(Summarizer):
    name = "extractive"

    def summarize(self, transcript, attendees=None, meeting_start=None):
        pairs = common.parse_transcript(transcript)          # [(speaker, sentence)]
        if not pairs:
            return self.empty_result()

        name_index = common.build_name_index(attendees)
        sentences = [s for _, s in pairs]

        return {
            "summary": self._summary(sentences),
            "action_items": self._action_items(pairs, name_index, meeting_start),
            "decisions": self._decisions(sentences),
        }

    # ── Summary ────────────────────────────────────────────────────────────
    def _summary(self, sentences):
        # Drop trivially short utterances ("yeah", "ok cool") from scoring.
        candidates = [s for s in sentences if len(common.words(s)) >= 4]
        if not candidates:
            return ' '.join(sentences[:2])

        freqs = {}
        for s in candidates:
            for w in common.words(s):
                if w in common.STOPWORDS:
                    continue
                freqs[w] = freqs.get(w, 0) + 1
        if not freqs:
            return ' '.join(candidates[:3])

        peak = max(freqs.values())
        norm = {w: c / peak for w, c in freqs.items()}

        scored = []
        for i, s in enumerate(candidates):
            content = [w for w in common.words(s) if w not in common.STOPWORDS]
            if not content:
                continue
            score = sum(norm.get(w, 0) for w in content) / len(content)
            scored.append((score, i, s))

        n = max(3, min(7, len(candidates) // 4 or 3))
        top = sorted(scored, key=lambda x: x[0], reverse=True)[:n]
        top.sort(key=lambda x: x[1])             # restore chronological order
        return ' '.join(s for _, _, s in top)

    # ── Action items ───────────────────────────────────────────────────────
    def _action_items(self, pairs, name_index, meeting_start):
        items = []
        seen = set()
        for speaker, sentence in pairs:
            if len(common.words(sentence)) < 3:
                continue

            is_commit = bool(_COMMIT.search(sentence))
            is_delegate = bool(_DELEGATE.search(sentence))
            if not (is_commit or is_delegate):
                continue

            key = re.sub(r'\s+', ' ', sentence.lower()).strip()
            if key in seen:
                continue

            assignee = None
            if is_delegate:
                assignee = common.match_vocative(sentence, name_index)
            if assignee is None and is_commit:
                assignee = common.match_speaker(speaker, name_index)

            due_hint, due_label = common.parse_due(sentence, meeting_start)

            items.append({
                "text": self._clean_item_text(sentence),
                "suggested_assignee_id": assignee['id'] if assignee else None,
                "suggested_assignee_name": assignee['name'] if assignee else None,
                "due_hint": due_hint,
                "due_label": due_label,
                "source_quote": (f"{speaker}: " if speaker else "") + sentence,
            })
            seen.add(key)
            if len(items) >= _MAX_ACTION_ITEMS:
                break
        return items

    def _clean_item_text(self, sentence):
        # Trim common lead-ins so the task title reads like an instruction.
        s = sentence.strip()
        s = re.sub(r"^(so|okay|ok|um|uh|well|yeah|and|but|i think|maybe|also)[\s,]+", "", s, flags=re.I)
        s = s[:1].upper() + s[1:] if s else s
        return s[:140]

    # ── Decisions ──────────────────────────────────────────────────────────
    def _decisions(self, sentences):
        out = []
        seen = set()
        for s in sentences:
            if not _DECISION.search(s):
                continue
            key = re.sub(r'\s+', ' ', s.lower()).strip()
            if key in seen:
                continue
            out.append(s.strip()[:200])
            seen.add(key)
            if len(out) >= _MAX_DECISIONS:
                break
        return out
