"""Small offline guard for known credential formats; no matched values are printed.

This is a repository hygiene check, not proof that all possible secrets are absent.
"""

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}\b"),
    re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
]
FORBIDDEN_NAMES = {"auth.json", "credentials.json", ".env"}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    ).split(b"\0")
    failures = []
    count = 0
    for raw in paths:
        if not raw:
            continue
        path = root / raw.decode()
        if not path.is_file() or path.is_symlink():
            continue
        count += 1
        if path.name in FORBIDDEN_NAMES or path.suffix in {".gguf", ".safetensors", ".sqlite3"}:
            failures.append(str(path.relative_to(root)))
            continue
        if any(pattern.search(path.read_bytes()) for pattern in PATTERNS):
            failures.append(str(path.relative_to(root)))
    if failures:
        for path in failures:
            print(f"Credential/artifact guard failed: {path}", file=sys.stderr)
        return 1
    print(f"Credential/artifact guard: {count} repository files checked; no known patterns found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
