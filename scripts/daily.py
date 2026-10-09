"""Orchestrator: run the whole pipeline once. Schedule it every few hours (Task Scheduler, cron, GitHub Actions).

    python scripts/daily.py                 # fetch -> process -> briefings for users who are due
    python scripts/daily.py --skip-fetch    # process and build briefings only

Each step is retried once after a short wait. A failed step is logged and the next step still runs, so a
broken feed or a busy AI service never stops users from getting a briefing built from what is already stored.
"""

import argparse
import sys
import time
import traceback

from gooddaynews.briefing import run as briefing_run
from gooddaynews.ingest import run as ingest_run
from gooddaynews.process import run as process_run

RETRY_WAIT_SECONDS = 60


def run_step(name: str, fn, attempts: int = 2) -> bool:
    for attempt in range(1, attempts + 1):
        print(f"\n=== {name} (attempt {attempt}) ===", flush=True)
        try:
            code = fn()
            if code in (0, None):
                return True
            print(f"{name} exited with code {code}")
        except Exception:
            traceback.print_exc()
        if attempt < attempts:
            time.sleep(RETRY_WAIT_SECONDS)
    print(f"{name} FAILED after {attempts} attempts; continuing with the next step")
    return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--skip-fetch", action="store_true")
    args = p.parse_args(argv)

    results = {}
    if not args.skip_fetch:
        results["fetch"] = run_step("fetch", lambda: ingest_run.main([]))
    results["process"] = run_step("process", lambda: process_run.main(["--limit", "150"]))
    results["briefings"] = run_step("briefings", lambda: briefing_run.main([]))
    print("\nSummary:", ", ".join(f"{k} {'ok' if v else 'FAILED'}" for k, v in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
