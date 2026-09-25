#!/usr/bin/env python3
"""Fail CI when the public repository contains common credential artifacts.

The check intentionally scans every reachable Git blob, not only HEAD. A public
repository exposes history as well as the current tree, so removing a secret in
a later commit is not enough.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath

ALLOWED_ENV_FILES = {".env.example"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}
FORBIDDEN_NAME_PATTERNS = (
    re.compile(r"(^|/)credentials[^/]*\.json$", re.IGNORECASE),
    re.compile(r"(^|/).*service[-_]?account[^/]*\.json$", re.IGNORECASE),
    re.compile(r"(^|/)client_secret[^/]*\.json$", re.IGNORECASE),
    re.compile(r"(^|/)gha-creds-[^/]*\.json$", re.IGNORECASE),
)
SECRET_PATTERNS = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GCP service account", re.compile(rb'"type"\s*:\s*"service_account".{0,400}"private_key"\s*:', re.DOTALL)),
    ("GitHub classic token", re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("GitHub fine-grained token", re.compile(rb"github_pat_[A-Za-z0-9_]{40,}")),
    ("Google API key", re.compile(rb"AIza[0-9A-Za-z_-]{30,}")),
    ("AWS access key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("Stripe live secret", re.compile(rb"sk_live_[0-9A-Za-z]{20,}")),
)


def git(*args: str, text: bool = True) -> str | bytes:
    return subprocess.check_output(["git", *args], text=text)


def object_paths() -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    raw = str(git("rev-list", "--objects", "--all"))
    for line in raw.splitlines():
        if not line.strip():
            continue
        oid, _, path = line.partition(" ")
        if path:
            mapping.setdefault(oid, set()).add(path)
    return mapping


def is_forbidden_path(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name
    if name.startswith(".env") and name not in ALLOWED_ENV_FILES:
        return True
    if pure.suffix.lower() in FORBIDDEN_SUFFIXES:
        return True
    return any(pattern.search(path) for pattern in FORBIDDEN_NAME_PATTERNS)


def main() -> int:
    failures: list[str] = []
    paths_by_object = object_paths()

    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        for oid, paths in paths_by_object.items():
            process.stdin.write(f"{oid}\n".encode())
            process.stdin.flush()
            header = process.stdout.readline().decode("utf-8", errors="replace").strip()
            parts = header.split()
            if len(parts) < 3 or parts[1] != "blob":
                if len(parts) >= 3:
                    size = int(parts[2])
                    process.stdout.read(size + 1)
                continue

            size = int(parts[2])
            content = process.stdout.read(size)
            process.stdout.read(1)  # newline inserted by --batch

            for path in sorted(paths):
                if is_forbidden_path(path):
                    failures.append(f"forbidden credential-like file in history: {path} ({oid[:12]})")

            if size > 2_000_000:
                continue
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(content):
                    display_path = sorted(paths)[0] if paths else "<unknown>"
                    failures.append(f"{label} signature found: {display_path} ({oid[:12]})")
    finally:
        process.stdin.close()
        process.wait(timeout=10)

    if failures:
        print("PUBLIC REPOSITORY SAFETY CHECK: FAILED", file=sys.stderr)
        for item in sorted(set(failures)):
            print(f" - {item}", file=sys.stderr)
        print(
            "\nRotate/revoke any real credential first, then purge it from Git history before keeping the repository public.",
            file=sys.stderr,
        )
        return 1

    print(f"PUBLIC REPOSITORY SAFETY CHECK: SUCCESS ({len(paths_by_object)} reachable objects inspected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
