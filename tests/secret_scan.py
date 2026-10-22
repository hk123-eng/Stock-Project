"""Fail if a tracked file looks like it contains a credential. No dependencies; runs locally and in CI.

python tests/secret_scan.py   (scans `git ls-files`, or every file under the repo if git is unavailable)
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATTERNS = {
    "AWS access key id": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "AWS secret key assignment": re.compile(r"aws_secret_access_key\s*[=:]\s*\S{20,}", re.I),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Alpha Vantage key in a URL": re.compile(r"apikey=(?!\{|\$|<|demo\b)[A-Za-z0-9]{8,}", re.I),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "Slack token": re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
}
SKIP_SUFFIXES = {".png", ".jpg", ".pdf", ".zip", ".tflite", ".pkl"}


def files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return [ROOT / f for f in out.splitlines() if f]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and ".venv" not in p.parts and "build" not in p.parts]


def main():
    hits = []
    for path in files():
        if path.suffix.lower() in SKIP_SUFFIXES or path.name == "secret_scan.py" or not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, rx in PATTERNS.items():
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.relative_to(ROOT)}:{line}: possible {name}")  # never print the match itself
    for h in hits:
        print(h)
    print(f"secret scan: {len(hits)} finding(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
