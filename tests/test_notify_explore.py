from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from gooddaynews.briefing.models import Briefing, BriefingStory, Profile
from gooddaynews.explore import parse_time_phrase, search_terms
from gooddaynews.notify import service
from gooddaynews.notify.messages import briefing_email, first_sentence, is_due, subject_for
from gooddaynews.notify.senders import OutboxSender

KOLKATA = ZoneInfo("Asia/Kolkata")
LONG_SUMMARY = "First sentence of the summary. Second sentence with more detail that should stay out of the email."


def bstory(id, pillar="science", country="IN"):
    return BriefingStory(id=id, headline=f"Headline {id} <b>bold</b>", summary=LONG_SUMMARY, why_it_matters="w",
                         pillar=pillar, subcategory=None, country=country, place=None,
                         published_at=datetime(2026, 10, 8, tzinfo=UTC), score=7.0,
                         verification_level="single_source", source_count=1,
                         sources=[("BBC", "https://bbc.co.uk/a", "bbc.co.uk")])


def profile(**kw):
    return Profile(**({"id": "u1", "email": "reader@example.com", "display_name": "Asha"} | kw))


def briefing(day: date, *stories):
    return Briefing("u1", day, list(stories) or [bstory(1), bstory(2)], "2 things that went right in the world",
                    thought="Small steps add up.")


# ---------- wording ----------

def test_subject_alternates_between_count_and_story_specific():
    even = date.fromordinal(739900)  # even ordinal: the standard count line
    odd = date.fromordinal(739901)
    assert subject_for(briefing(even), profile(), set()) == "☀️ Good morning. 2 things went right in the world yesterday."
    assert subject_for(briefing(odd, bstory(1, "science")), profile(), set()).startswith("🔬")
    assert subject_for(briefing(odd, bstory(1, "environment")), profile(), set()).startswith("🌱")
    assert subject_for(briefing(odd, bstory(1, "humanity", "IN")), profile(), {"IN"}).startswith("❤️")


def test_email_uses_only_first_sentence_links_back_and_escapes_html():
    msg = briefing_email(briefing(date(2026, 10, 9)), profile(), "https://app.example", set())
    assert "Second sentence" not in msg.text and "Second sentence" not in msg.html
    assert "https://app.example/story?id=1" in msg.text
    assert "https://app.example/preferences" in msg.html
    assert "<b>bold</b>" not in msg.html and "&lt;b&gt;bold&lt;/b&gt;" in msg.html
    assert "Good morning, Asha." in msg.text and "Small steps add up." in msg.text


def test_first_sentence():
    assert first_sentence(LONG_SUMMARY) == "First sentence of the summary."
    assert first_sentence("No full stop") == "No full stop"


# ---------- when to send ----------

def test_is_due_checks_switch_time_frequency_and_duplicates():
    friday_7am = datetime(2026, 10, 9, 7, 0, tzinfo=KOLKATA)
    saturday_7am = datetime(2026, 10, 10, 7, 0, tzinfo=KOLKATA)
    p = profile(notify_time=time(6, 0))
    assert is_due(p, friday_7am, already_sent=False)
    assert not is_due(p, friday_7am, already_sent=True)
    assert not is_due(profile(notify_time=time(8, 0)), friday_7am, False)
    assert not is_due(profile(notify_enabled=False), friday_7am, False)
    assert not is_due(profile(frequency="weekdays"), saturday_7am, False)
    assert is_due(profile(frequency="weekends"), saturday_7am, False)
    assert not is_due(profile(frequency="weekends"), friday_7am, False)


# ---------- sending ----------

class LogConn:
    def __init__(self):
        self.logged = []

    def run(self, sql, **params):
        if "insert into notifications" in sql:
            self.logged.append((params["s"], params["err"]))
        return []


def test_outbox_writes_files_without_email_in_filename(tmp_path):
    sender = OutboxSender(tmp_path)
    ok, where = service.send_briefing_notification(LogConn(), sender, profile(), briefing(date(2026, 10, 9)),
                                                   "https://app.example", set())
    files = sorted(p.name for p in tmp_path.iterdir())
    assert ok and len(files) == 2 and not any("reader" in f for f in files)


def test_failed_send_is_logged_not_raised():
    class Broken:
        channel = "email"

        def send(self, to, msg, for_date):
            raise ConnectionError("SMTP down")

    conn = LogConn()
    ok, error = service.send_briefing_notification(conn, Broken(), profile(), briefing(date(2026, 10, 9)), "u", set())
    assert not ok and "SMTP down" in error and conn.logged == [("failed", error)]


# ---------- search parsing ----------

def test_time_phrases_become_date_filters():
    today = date(2026, 10, 9)
    assert parse_time_phrase("scientific breakthroughs this month", today) == ("scientific breakthroughs", date(2026, 9, 9))
    assert parse_time_phrase("inspiring people today", today) == ("inspiring people", today)
    assert parse_time_phrase("solar in India", today) == ("solar in India", None)


def test_generic_words_are_not_search_terms():
    assert search_terms("positive AI news") == ["ai"]
    assert search_terms("good news Mumbai") == ["mumbai"]
    assert search_terms("good news") == []
