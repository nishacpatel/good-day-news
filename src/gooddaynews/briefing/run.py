"""Build morning briefings and send notifications for users whose time has arrived (run this hourly).

    python -m gooddaynews.briefing.run                  # every user who is due
    python -m gooddaynews.briefing.run --user a@b.com   # build this user's briefing now (notify only if due)
    python -m gooddaynews.briefing.run --user a@b.com --notify-now   # ...and send the notification now
"""

import argparse
import json
import sys

from gooddaynews.briefing import store
from gooddaynews.briefing.builder import user_countries
from gooddaynews.briefing.models import load_briefing_config
from gooddaynews.briefing.service import build_briefing
from gooddaynews.db import connect
from gooddaynews.llm import GeminiLLM
from gooddaynews.notify.messages import is_due
from gooddaynews.notify.senders import get_sender
from gooddaynews.notify.service import already_handled, send_briefing_notification
from gooddaynews.process.config import load_scoring
from gooddaynews.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user", help="only this email; builds the briefing now even if not due")
    p.add_argument("--notify-now", action="store_true", help="with --user: send the notification now")
    args = p.parse_args(argv)

    cfg, scoring, llm, sender = load_briefing_config(), load_scoring(), GeminiLLM(), get_sender()
    app_url = get_settings().app_url
    conn = connect()
    counts = {"built": 0, "no_stories": 0, "notified": 0, "notify_failed": 0}
    errors = []
    try:
        run_id = conn.run("insert into run_log (stage) values ('briefing') returning id")[0][0]
        if args.user:
            profile = store.get_profile(conn, args.user)
            if profile is None:
                print(f"No profile for {args.user}")
                return 1
            profiles = [profile]
        else:
            profiles = store.all_profiles(conn)

        for profile in profiles:
            today, now = profile.local_date(), profile.local_now()
            try:
                saved = store.load_briefing(conn, profile.id, today)
                briefing = saved if saved and not saved.is_fallback else None
                if args.user or (briefing is None and now.time() >= profile.notify_time):
                    briefing = build_briefing(conn, llm, profile, cfg, scoring)
                    if briefing:
                        counts["built"] += 1
                        print(f"  {profile.email}: {briefing.title} (last {briefing.window_hours}h)")
                    else:
                        counts["no_stories"] += 1
                        print(f"  {profile.email}: no stories available")
                if briefing is None:
                    continue

                handled = already_handled(conn, profile, today, sender.channel)
                if (args.notify_now and not handled) or is_due(profile, now, handled):
                    ok, detail = send_briefing_notification(conn, sender, profile, briefing, app_url,
                                                            user_countries(profile, cfg) or set())
                    counts["notified" if ok else "notify_failed"] += 1
                    print(f"  {profile.email}: notification {'sent via ' + sender.channel if ok else 'FAILED'}"
                          f" ({detail})")
            except Exception as exc:
                errors.append({"user": profile.id, "error": f"{type(exc).__name__}: {exc}"[:300]})
                print(f"  {profile.email}: FAILED {exc}")

        conn.run(
            "update run_log set finished_at = now(), counts = cast(:c as jsonb), errors = cast(:e as jsonb) where id = :id",
            c=json.dumps(counts | {"llm_calls": llm.calls}), e=json.dumps(errors), id=run_id,
        )
        print(f"Done: {counts}, {len(errors)} failed")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
