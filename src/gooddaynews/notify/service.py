"""Send a user's daily notification once, log it, and retry failures on later runs."""

from datetime import date

from gooddaynews.briefing.models import Briefing, Profile
from gooddaynews.notify.messages import briefing_email

MAX_ATTEMPTS = 3


def notification_state(conn, user_id: str, for_date: date, channel: str) -> tuple[str | None, int]:
    rows = conn.run(
        "select status, attempts from notifications where user_id = cast(:u as uuid) and for_date = :d and channel = :c",
        u=user_id, d=for_date, c=channel,
    )
    return (rows[0][0], rows[0][1]) if rows else (None, 0)


def _log(conn, user_id: str, for_date: date, channel: str, status: str, subject: str, error: str | None) -> None:
    conn.run(
        """insert into notifications (user_id, for_date, channel, status, subject, error)
           values (cast(:u as uuid), :d, :c, :s, :subj, :err)
           on conflict (user_id, for_date, channel) do update set
               status = excluded.status, subject = excluded.subject, error = excluded.error,
               attempts = notifications.attempts + 1, sent_at = now()""",
        u=user_id, d=for_date, c=channel, s=status, subj=subject, err=error,
    )


def already_handled(conn, profile: Profile, for_date: date, channel: str) -> bool:
    """Sent, or failed too many times to keep trying today."""
    status, attempts = notification_state(conn, profile.id, for_date, channel)
    return status == "sent" or attempts >= MAX_ATTEMPTS


def send_briefing_notification(conn, sender, profile: Profile, b: Briefing, app_url: str,
                               home_countries: set[str]) -> tuple[bool, str]:
    msg = briefing_email(b, profile, app_url, home_countries)
    try:
        where = sender.send(profile.email, msg, b.for_date)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
        _log(conn, profile.id, b.for_date, sender.channel, "failed", msg.subject, error)
        return False, error
    _log(conn, profile.id, b.for_date, sender.channel, "sent", msg.subject, None)
    return True, where
