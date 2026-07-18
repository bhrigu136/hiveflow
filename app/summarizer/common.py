"""Shared, dependency-free NLP helpers used by both the extractive and the LLM
summarizer (the LLM backend reuses the name/date resolution so its output is
normalized the same way).
"""
import re
from datetime import timedelta

# A small stopword list — enough to make frequency scoring meaningful without
# pulling in nltk or downloading corpora (keeps the Render build clean).
STOPWORDS = {
    'a', 'an', 'and', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'to', 'of', 'in', 'on', 'at', 'for', 'with', 'as', 'by', 'from', 'that',
    'this', 'these', 'those', 'it', 'its', 'i', 'you', 'we', 'they', 'he', 'she',
    'me', 'us', 'them', 'him', 'her', 'my', 'our', 'your', 'their', 'so', 'but',
    'or', 'if', 'then', 'than', 'too', 'very', 'can', 'will', 'just', 'do',
    'does', 'did', 'have', 'has', 'had', 'not', 'no', 'yes', 'okay', 'ok',
    'yeah', 'um', 'uh', 'like', 'really', 'gonna', 'wanna', 'kind', 'sort',
    'about', 'into', 'over', 'out', 'up', 'down', 'there', 'here', 'what',
    'which', 'who', 'when', 'where', 'how', 'all', 'any', 'some', 'thing',
    'things', 'get', 'got', 'go', 'going', 'right', 'well', 'now', 'also',
}

WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

_MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7,
    'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}

# Matches an assembled transcript line:  "[09:05] Priya: let's ship it"
_SPEAKER_LINE = re.compile(r'^\s*(?:\[\d{1,2}:\d{2}\]\s*)?([^:]{1,40}?):\s*(.*)$')

_WORD = re.compile(r"[a-zA-Z][a-zA-Z'\-]+")
_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')


def words(text):
    return [w.lower() for w in _WORD.findall(text)]


def split_sentences(text):
    """Split a chunk of speech into sentences. Speech often has no punctuation,
    so a line with no terminator is treated as one sentence."""
    text = (text or '').strip()
    if not text:
        return []
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def parse_transcript(transcript):
    """Return [(speaker, sentence), ...] from an assembled transcript.

    Lines that don't carry a "Speaker:" prefix inherit the previous speaker.
    """
    out = []
    last_speaker = None
    for raw in (transcript or '').splitlines():
        raw = raw.strip()
        if not raw:
            continue
        m = _SPEAKER_LINE.match(raw)
        if m:
            last_speaker = m.group(1).strip()
            body = m.group(2).strip()
        else:
            body = raw
        for sent in split_sentences(body):
            out.append((last_speaker, sent))
    return out


def first_name(name):
    if not name:
        return ''
    return name.strip().split()[0]


def build_name_index(attendees):
    """first-name (lower) -> {'id', 'name'} for quick speaker/vocative lookup."""
    idx = {}
    for a in (attendees or []):
        fn = first_name(a.get('name', '')).lower()
        if fn and len(fn) >= 2 and fn not in idx:
            idx[fn] = a
    return idx


def match_speaker(speaker, name_index):
    """Map a transcript speaker label to an attendee {'id','name'} or None."""
    if not speaker:
        return None
    return name_index.get(first_name(speaker).lower())


def match_vocative(sentence, name_index):
    """Detect 'Priya, can you …' / 'can you do this, Priya' style delegation and
    return the addressed attendee, or None."""
    low = sentence.lower()
    for fn, a in name_index.items():
        if re.search(r'\b' + re.escape(fn) + r'\b\s*,', low) or \
           re.search(r'\b' + re.escape(fn) + r'\b\s+(can|could|please|will|would|should)\b', low) or \
           re.search(r',\s*' + re.escape(fn) + r'\b', low):
            return a
    return None


def parse_due(text, meeting_start):
    """Resolve a relative due-date phrase to (iso_date, human_label) or (None, None)."""
    if not meeting_start:
        return None, None
    base = meeting_start.date() if hasattr(meeting_start, 'date') else meeting_start
    t = text.lower()

    if 'tomorrow' in t:
        d = base + timedelta(days=1)
        return d.isoformat(), 'tomorrow'
    if 'today' in t or 'tonight' in t or 'end of day' in t or re.search(r'\beod\b', t):
        return base.isoformat(), 'today'
    if 'end of week' in t or re.search(r'\beow\b', t):
        days = (4 - base.weekday()) % 7          # upcoming Friday
        return (base + timedelta(days=days)).isoformat(), 'end of week'
    if 'next week' in t:
        d = base + timedelta(days=7)
        return d.isoformat(), 'next week'

    for i, wd in enumerate(WEEKDAYS):
        if re.search(r'\b' + wd + r'\b', t):
            days = (i - base.weekday()) % 7
            if days == 0:
                days = 7                         # "by Monday" said on a Monday → next one
            return (base + timedelta(days=days)).isoformat(), wd.capitalize()

    # explicit "jun 28" / "28 jun"
    m = re.search(r'\b(' + '|'.join(_MONTHS) + r')[a-z]*\s+(\d{1,2})\b', t)
    if not m:
        m2 = re.search(r'\b(\d{1,2})\s+(' + '|'.join(_MONTHS) + r')[a-z]*\b', t)
        if m2:
            day, mon = int(m2.group(1)), _MONTHS[m2.group(2)]
            return _safe_date(base.year, mon, day)
    else:
        mon, day = _MONTHS[m.group(1)], int(m.group(2))
        return _safe_date(base.year, mon, day)

    return None, None


def _safe_date(year, month, day):
    from datetime import date
    try:
        return date(year, month, day).isoformat(), date(year, month, day).strftime('%b %d')
    except ValueError:
        return None, None
