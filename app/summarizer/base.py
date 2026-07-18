"""Summarizer interface.

Every backend takes the assembled, speaker-labeled transcript and returns the
same shape, so the route never cares which engine ran:

    {
        "summary":      "<a few sentences>",
        "action_items": [ {text, suggested_assignee_id, suggested_assignee_name,
                           due_hint, due_label, source_quote}, ... ],
        "decisions":    ["<decision sentence>", ...],
    }

`attendees` is a list of {"id": int, "name": str} used to map a spoken name to a
real user. `meeting_start` (a datetime) anchors relative due-dates like
"tomorrow" or "by Friday".
"""


class Summarizer:
    name = "base"

    def summarize(self, transcript, attendees=None, meeting_start=None):
        raise NotImplementedError

    @staticmethod
    def empty_result():
        return {"summary": "", "action_items": [], "decisions": []}
