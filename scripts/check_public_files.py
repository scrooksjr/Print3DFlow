"""Check the staged commit without printing credential values or matching lines."""

import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values


def run(*args):
    return subprocess.check_output(["git", *args])


def main():
    root = Path(__file__).resolve().parents[1]
    staged = (
        run("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
        .decode()
        .split("\0")
    )
    secrets = []
    for key, value in dotenv_values(root / ".env").items():
        if (
            value
            and len(value) >= 8
            and re.search(r"KEY|TOKEN|SECRET|PASSWORD", key, re.I)
        ):
            secrets.append(value.encode())
    blocked_prefixes = (
        "data/",
        "output/",
        "private/",
        "tools/",
        "tmp/",
        ".venv/",
        ".uv-cache/",
        "frontend/dist/",
    )
    private_names = {
        "CALIBRATION.md",
        "DEMO-NARRATION.txt",
        "DEMO-RUNBOOK.md",
        "INTEGRATIONS.md",
        "X2D-PROFILE.md",
        "build-plan-v1.1.md",
        "build_documents.py",
        "profiles/registry.json",
    }
    credential_pattern = re.compile(
        rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
    )
    failures = []
    count = 0
    for name in filter(None, staged):
        count += 1
        path = Path(name)
        if (
            name.startswith(blocked_prefixes)
            or name in private_names
            or "node_modules" in path.parts
            or (path.name.startswith(".env") and path.name != ".env.example")
            or path.suffix.lower()
            in (
                ".db",
                ".sqlite",
                ".sqlite3",
                ".3mf",
                ".gcode",
                ".pem",
                ".key",
                ".p12",
                ".pfx",
                ".png",
                ".jpg",
                ".jpeg",
                ".pdf",
            )
        ):
            failures.append((name, "private/generated path"))
            continue
        content = run("show", ":" + name)
        if any(value in content for value in secrets) or credential_pattern.search(
            content
        ):
            failures.append((name, "credential match"))
        if re.search(rb"C:[/\\]Users[/\\]", content, re.I):
            failures.append((name, "personal absolute path"))
    for name, reason in failures:
        print(f"BLOCKED: {name}: {reason}")
    if failures:
        raise SystemExit(1)
    if not count:
        raise SystemExit("No staged files to review.")
    print(
        f"PASS: {count} staged files; no excluded paths, known local keys, token patterns, or personal absolute paths detected."
    )


if __name__ == "__main__":
    main()
