"""Save a Gemini API key into .env after checking it works. The key is typed hidden and never printed.

    .venv\\Scripts\\python scripts\\set_gemini_key.py
"""

import getpass
import re
import sys
from pathlib import Path

from google import genai

ENV = Path(__file__).resolve().parents[1] / ".env"


def works(key: str) -> str | None:
    """None if the key can make a request; otherwise the reason it can't."""
    try:
        client = genai.Client(api_key=key)
        for model in ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite"):
            try:
                client.models.generate_content(model=model, contents="Reply with: ok")
                return None
            except Exception as exc:
                if "RESOURCE_EXHAUSTED" in str(exc):  # out of today's quota, but the key itself is valid
                    return None
                last = exc
        return f"{type(last).__name__}: {str(last).replace(key, '***')[:200]}"
    except Exception as exc:
        return f"{type(exc).__name__}: {str(exc).replace(key, '***')[:200]}"


def main() -> int:
    key = getpass.getpass("Paste your Gemini API key (hidden), then press Enter: ").strip().strip('"')
    if not key:
        print("Not saved: no key entered.")
        return 1
    error = works(key)
    if error:
        print(f"Not saved: the key didn't work ({error}).")
        return 1
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    line = f"GEMINI_API_KEY={key}"
    if re.search(r"^GEMINI_API_KEY=.*$", text, flags=re.M):
        text = re.sub(r"^GEMINI_API_KEY=.*$", lambda _: line, text, count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    ENV.write_text(text, encoding="utf-8")
    print(f"Key works and was saved to {ENV}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
