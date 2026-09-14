#!/usr/bin/env python3
"""Check what making this repository public would expose.

    python3 scripts/audit_public_repo.py

Run it before flipping a private repository to public, or any time you want to know whether
something secret-shaped has ever been committed.

**Why every commit and not just the working tree:** publishing a repository publishes its
history too, so a token committed once and deleted in the next commit is still there for
anyone to fetch. The scan that matters covers every blob that has ever existed on any ref.

What it reports, separately:

* **Content** — private key headers, common token shapes (GitHub, Cloudflare, AWS, Google,
  Slack, OpenAI-style), `NAME=value` assignments, long high-entropy strings, bearer headers.
  Obvious placeholders (`example`, `placeholder`, `os.environ`, `{{ … }}`, `$( … )`, `…`) are
  ignored, so the output is signal.
* **Paths** — files that should never be tracked at all: `.env`, `*.pem`, `*.key`, `id_rsa*`,
  `*.sqlite3`, deploy keys, backups, `data/`, `media/`.

Vendored and binary files are skipped for content (a minified map library contains
base64 that looks exactly like a secret) but still checked by path.

Exit code is 1 when anything is found, so it can gate a release.

Known-good findings in this repository, so they don't alarm anyone re-running it: a couple of
test fixtures and the empty assignments in `.env.example`. See the dated entries in
`docs/HANDOFF.md` for the audit that cleared this repo for publication.
"""
import re
import subprocess
import sys

# Third-party or binary: content is not worth scanning (minified JS in particular is full of
# base64 that matches secret patterns), but the path still gets checked.
SKIP_CONTENT = re.compile(
    r"\.(js|css|png|jpg|jpeg|gif|svg|ico|woff2?|ttf|otf|pdf|xlsx|zip|pyc|map)$", re.I
)

CONTENT_PATTERNS = (
    ("private key", r"BEGIN [A-Z ]*PRIVATE KEY"),
    ("SSH public key", r"ssh-(rsa|ed25519) [A-Za-z0-9+/=]{40,}"),
    ("GitHub token", r"gh[pousr]_[A-Za-z0-9]{30,}"),
    ("AWS access key", r"AKIA[0-9A-Z]{16}"),
    ("OpenAI-style key", r"sk-[A-Za-z0-9]{20,}"),
    ("Google API key", r"AIza[0-9A-Za-z_-]{30,}"),
    ("Slack token", r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("bearer header", r"Bearer [A-Za-z0-9_\-.]{20,}"),
    ("assigned secret", r"(SECRET_KEY|API_KEY|ACCESS_KEY|TOKEN|PASSWORD|PASSWD|_KEY)[ \t]*[=:][ \t]*['\"]?([A-Za-z0-9_\-/+]{12,})"),
    ("Django insecure default", r"django-insecure-[A-Za-z0-9]{10,}"),
    ("64-char hex string", r"\b[0-9a-f]{64}\b"),
)

# Values that are obviously placeholders rather than secrets. Filtering these is what keeps
# the output usable — a scanner that cries wolf gets ignored, which is worse than no scanner.
BENIGN = re.compile(
    r"(example|placeholder|changeme|your[-_]|xxxx|dummy|fake|sample|insecure-dev|"
    r"yoursecret|abc123|not-a-|redacted|TODO|\$\(|os\.environ|getenv|\{\{|%s|\$\{|…)",
    re.I,
)

SENSITIVE_PATHS = re.compile(
    r"(\.env$|\.env\.|deploy_key|\.pem$|\.key$|id_rsa|id_ed25519|\.sqlite3|secret|credential|"
    r"\.bak$|\.pfx$|\.p12$|/data/|^data/|/media/|^media/)",
    re.I,
)

# Sensitive-shaped paths that belong in a public repo on purpose. Named rather than
# pattern-matched so that adding one is a deliberate act with a reason next to it.
DELIBERATE = {
    ".env.example": "documents every variable the app reads; values are empty by definition",
}

# Files whose secret-shaped content is known, deliberate, and not a credential. The point of
# listing them is that everything *else* still fails the run: a tool that always says "found
# something" is a tool nobody reads. Their findings are printed every time rather than
# swallowed, so a new one in these files is visible too.
KNOWN_BENIGN = {
    "inventory/tests/test_kiosk_auth.py": 'TOKEN = "kiosk-shared-secret…" — a fixture, not a real kiosk token',
    "inventory/tests/test_login.py": 'PASSWORD = "correct-horse-battery-…" — a throwaway test login',
    "inventory/tests/test_setup_wizard.py": 'PASSWORD = "Sh0pFull-0f-P4rts…" — a strength-check fixture',
    "docs/HANDOFF.md": "quotes those three fixtures while describing this very audit",
    "inventory/tests/test_audit_public_repo.py": (
        "holds sample credentials on purpose — it is the test for this scanner, so a "
        "sample AWS key and a sample token are the fixtures"
    ),
    # A list of (needle, reason) pairs excuses only those strings, not the whole file. Used
    # here because this scanner's own explanations name the fixtures above — including in the
    # earlier version of this file that is still in history. Scoping to the needles keeps the
    # important property: a *new*, unseen secret committed to any file in this list still
    # fails the run. A whole-file exemption would quietly swallow it.
    "scripts/audit_public_repo.py": [
        ("kiosk-shared-secret", "names the kiosk test fixture while explaining this audit"),
        ("correct-horse-battery-", "names the throwaway test password while explaining this audit"),
        ("Sh0pFull-0f-P4rts", "names the strength-check fixture while explaining this audit"),
    ],
}


def benign_reason(where: str, snippet: str) -> str | None:
    """Why this finding is known-benign, or None if it wants a look.

    A path maps either to a single reason (the whole file is deliberately full of fixtures,
    like this scanner's own test) or to a list of (needle, reason) pairs, which excuses only
    findings containing one of those needles.
    """
    entry = KNOWN_BENIGN.get(where)
    if entry is None:
        return None
    if isinstance(entry, str):
        return entry
    for needle, reason in entry:
        if needle in snippet:
            return reason
    return None


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def path_findings(paths) -> list[str]:
    return sorted({p for p in paths if SENSITIVE_PATHS.search(p) and p not in DELIBERATE})


def findings_in(text: str) -> list[tuple[str, str]]:
    """Every secret-shaped thing in one blob's content, placeholders excluded.

    Pure, and the only part worth unit-testing — the rest is git plumbing.
    """
    found = []
    for label, pattern in CONTENT_PATTERNS:
        for match in re.finditer(pattern, text):
            snippet = match.group(0)
            if BENIGN.search(snippet):
                continue
            found.append((label, snippet[:80]))
    return found


def main() -> int:
    raw = git("rev-list", "--objects", "--all")
    blobs: dict[str, set[str]] = {}
    for line in raw.splitlines():
        sha, _, path = line.partition(" ")
        if path:
            blobs.setdefault(sha, set()).add(path)

    every_path = {p for paths in blobs.values() for p in paths}
    print(f"blobs in history: {len(blobs)}   distinct paths ever committed: {len(every_path)}")

    paths = path_findings(every_path)
    print(f"\npaths that look like they should never be tracked: {len(paths)}")
    for p in paths[:40]:
        print(f"    {p}")

    findings, skipped, checked = [], 0, 0
    for sha, blob_paths in blobs.items():
        text_paths = [p for p in blob_paths if not SKIP_CONTENT.search(p)]
        if not text_paths:
            skipped += 1
            continue
        body = subprocess.run(["git", "cat-file", "blob", sha], capture_output=True).stdout
        if len(body) > 400_000:
            skipped += 1
            continue
        try:
            content = body.decode("utf-8")
        except UnicodeDecodeError:
            skipped += 1
            continue
        checked += 1
        for label, snippet in findings_in(content):
            where = sorted(text_paths)[0]
            commits = git("log", "--all", "--oneline", "--find-object", sha, "--max-count=2").splitlines()
            findings.append((label, where, snippet, commits[0] if commits else "?"))

    print(f"blobs checked for content: {checked}   skipped (binary/vendored/huge): {skipped}")

    ignored = []
    surprises = []
    for label, where, snippet, commit in findings:
        reason = benign_reason(where, snippet)
        if reason is None:
            surprises.append((label, where, snippet, commit))
        else:
            ignored.append((label, where, snippet, commit, reason))

    if ignored:
        print(f"\nignored as known-benign, listed so a new one is obvious: {len(ignored)}")
        for label, where, snippet, _commit, reason in ignored:
            print(f"    [{label}] {where}: {snippet!r}")
            print(f"        reason: {reason}")

    print(f"\nfindings needing a look: {len(surprises)}")
    for label, where, snippet, commit in surprises:
        print(f"    [{label}] {where}: {snippet!r}   ({commit})")

    if paths or surprises:
        print("\nVERDICT: something above wants a look before this repository is public.")
        return 1
    print("\nVERDICT: nothing secret-shaped found in history or in the tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
