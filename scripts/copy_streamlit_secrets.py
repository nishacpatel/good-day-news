"""Copy the Streamlit Cloud secrets (TOML) to the clipboard from .env, without printing them.

    .venv\\Scripts\\python scripts\\copy_streamlit_secrets.py [https://your-app.streamlit.app]

Then paste into Streamlit Cloud: app settings > Secrets.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"
KEYS = ("DATABASE_URL", "GEMINI_API_KEY")


def copy_to_clipboard(text: str) -> None:
    if sys.platform == "win32":
        # Set-Clipboard keeps Unicode intact; the value goes in on stdin, never on the command line.
        subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                       input=text, text=True, encoding="utf-8", check=True)
    else:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)


def main(argv: list[str]) -> int:
    values = dict(re.findall(r"^([A-Z_]+)=(.*)$", ENV.read_text(encoding="utf-8"), flags=re.M))
    missing = [k for k in KEYS if not values.get(k, "").strip()]
    if missing:
        print(f"Not copied: {', '.join(missing)} missing in .env.")
        return 1
    lines = [f"{k} = {json.dumps(values[k].strip())}" for k in KEYS]  # json quoting is valid TOML for strings
    if argv:
        lines.append(f"APP_URL = {json.dumps(argv[0].rstrip('/'))}")
    toml = "\n".join(lines) + "\n"
    copy_to_clipboard(toml)
    print(f"Copied {len(lines)} secrets to the clipboard. Paste them into Streamlit Cloud > Secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
