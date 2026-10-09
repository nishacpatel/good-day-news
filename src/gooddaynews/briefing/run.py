"""Build morning briefings for users whose briefing time has arrived (run this hourly).

    python -m gooddaynews.briefing.run                 # every user who is due and has no briefing today
    python -m gooddaynews.briefing.run --user a@b.com  # one user, now, replacing today's briefing
"""

import argparse
import json
import sys

from gooddaynews.briefing import store
from gooddaynews.briefing.models import load_briefing_config
from gooddaynews.briefing.service import build_briefing
from gooddaynews.db import connect
from gooddaynews.llm import GeminiLLM
from gooddaynews.process.config import load_scoring


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user", help="build for this email now, even if not due")
    args = p.parse_args(argv)

    cfg, scoring, llm = load_briefing_config(), load_scoring(), GeminiLLM()
    conn = connect()
    try:
        run_id = conn.run("insert into run_log (stage) values ('briefing') returning id")[0][0]
        if args.user:
            profile = store.get_profile(conn, args.user)
            if profile is None:
                print(f"No profile for {args.user}")
                return 1
            due = [profile]
        else:
            due = []
            for profile in store.all_profiles(conn):
                existing = store.load_briefing(conn, profile.id, profile.local_date())
                has_today = existing is not None and not existing.is_fallback
                if not has_today and profile.local_now().time() >= profile.notify_time:
                    due.append(profile)

        built, empty, errors = 0, 0, []
        for profile in due:
            try:
                b = build_briefing(conn, llm, profile, cfg, scoring)
                if b:
                    built += 1
                    print(f"  {profile.email}: {b.title} (last {b.window_hours}h)")
                else:
                    empty += 1
                    print(f"  {profile.email}: no stories available")
            except Exception as exc:
                errors.append({"user": profile.id, "error": f"{type(exc).__name__}: {exc}"[:300]})
                print(f"  {profile.email}: FAILED {exc}")
        conn.run(
            "update run_log set finished_at = now(), counts = cast(:c as jsonb), errors = cast(:e as jsonb) where id = :id",
            c=json.dumps({"due": len(due), "built": built, "no_stories": empty, "llm_calls": llm.calls}),
            e=json.dumps(errors), id=run_id,
        )
        print(f"Done: {built} built, {empty} without stories, {len(errors)} failed")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
