"""Tell the owner when a newer version exists.

This app is distributed by cloning a git repository, so "am I up to date?" is not
obvious to anyone — there is no package manager and no release notification. This
checks the project's GitHub releases and reports what it finds on the settings page,
where someone changing their configuration will pass it.

Deliberately modest, in four ways:

* **It phones GitHub, and nowhere else.** That is a real, if small, privacy decision:
  it reveals to GitHub that this app is installed somewhere. The repository is public
  regardless, so it tells an observer very little they could not already infer — but
  the check can be switched off entirely, and the setting says what it does.
* **Cached for a day.** A request per page load would be rude to GitHub and would tell
  the owner nothing new.
* **It never blocks or raises.** Offline, rate-limited, DNS broken, GitHub having a
  bad afternoon — all of those report as "couldn't check", which is a state the owner
  can ignore rather than an error they have to resolve.
* **It never auto-updates anything.** Telling someone a new version exists is useful;
  silently changing the code they are relying on is not.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .version import __version__

CACHE_KEY = "inventory:update-check"
CACHE_SECONDS = 24 * 60 * 60
TIMEOUT = 8

DEFAULT_REPO = "sethmills/sethsparts"


@dataclass
class UpdateInfo:
    ok: bool
    current: str = __version__
    latest: str = ""
    url: str = ""
    notes: str = ""
    error: str = ""

    @property
    def update_available(self) -> bool:
        if not self.ok or not self.latest:
            return False
        return _parse(self.latest) > _parse(self.current)


def _parse(text: str) -> tuple:
    """A version string as a comparable tuple. Unparseable becomes (0,).

    Compared as numbers where possible so 0.10.0 correctly beats 0.9.0 — string
    comparison would get that backwards and report a downgrade as an update.
    """
    numbers = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in numbers) if numbers else (0,)


def repo() -> str:
    return getattr(settings, "UPDATE_REPO", DEFAULT_REPO) or DEFAULT_REPO


def enabled() -> bool:
    return bool(getattr(settings, "UPDATE_CHECK_ENABLED", True))


def cached_info() -> UpdateInfo | None:
    """The last result, or None if this install has never checked.

    Reads the cache only. A page render never makes an outbound request, which matters
    beyond tidiness: a settings page that silently phones GitHub every time it is
    opened is a surprise to the person looking at it, and it makes the page depend on
    the internet to draw itself.
    """
    return cache.get(CACHE_KEY)


def check_for_update() -> UpdateInfo:
    """Fetch the latest version and remember it.

    Called only from an explicit action — the button on the settings page, or the
    management command. Never from a page render.
    """
    if not enabled():
        return UpdateInfo(ok=False, error="Updates aren't checked on this install.")

    info = _fetch()
    cache.set(CACHE_KEY, info, CACHE_SECONDS)
    return info


def _fetch() -> UpdateInfo:
    import requests

    from .archiving import USER_AGENT

    base = f"https://api.github.com/repos/{repo()}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}

    for path in ("releases/latest", "tags"):
        try:
            response = requests.get(f"{base}/{path}", headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            return UpdateInfo(ok=False, error=f"Couldn't reach GitHub: {exc}")

        if response.status_code == 404:
            if path == "releases/latest":
                # A repository with no releases yet is normal, not an error — fall through
                # to tags rather than reporting a failure.
                continue
            # GitHub answers 404 (not 403) for a repository an anonymous caller cannot see,
            # deliberately, so that a private repository is indistinguishable from a
            # missing one. This check sends no token, so a private repo lands exactly
            # here — and "GitHub returned HTTP 404" on its own reads like a typo in the
            # repository name, which sends the owner looking in the wrong place.
            #
            # ok stays False on purpose: a check that could not run must never be
            # presented as "you are up to date".
            return UpdateInfo(
                ok=False,
                error=(
                    f"GitHub won't show {repo()} to an unsigned-in request (HTTP 404). "
                    "Either the repository is private — in which case nothing here can "
                    "check for updates until it is made public — or UPDATE_REPO names it "
                    "wrong."
                ),
            )
        if response.status_code == 403:
            return UpdateInfo(ok=False, error="GitHub is rate-limiting this install. Try again later.")
        if response.status_code >= 400:
            return UpdateInfo(ok=False, error=f"GitHub returned HTTP {response.status_code}.")

        try:
            payload = response.json()
        except ValueError:
            return UpdateInfo(ok=False, error="GitHub sent something that wasn't JSON.")

        if path == "tags":
            if not payload:
                return UpdateInfo(ok=False, error="No releases or tags published yet.")
            first = payload[0]
            return UpdateInfo(
                ok=True,
                latest=first.get("name", ""),
                url=f"https://github.com/{repo()}/releases",
            )

        return UpdateInfo(
            ok=True,
            latest=payload.get("tag_name", ""),
            url=payload.get("html_url", f"https://github.com/{repo()}/releases"),
            notes=(payload.get("name") or "").strip(),
        )

    return UpdateInfo(ok=False, error="Couldn't find any versions to compare against.")


def clear_cache() -> None:
    cache.delete(CACHE_KEY)


def describe(info: UpdateInfo) -> str:
    """One sentence for a human, covering every state this can be in."""
    if info.update_available:
        return f"A newer version is available — {info.latest}, and you're on {info.current}."
    if info.ok:
        return f"You're up to date ({info.current})."
    return info.error or "Couldn't check for updates."


def data_dir() -> str:
    """The bind-mounted data directory — the parent of MEDIA_ROOT, where the database
    and media live. In the Docker deploy this is shared with the host, which is what
    lets the web process hand the host an upgrade request through a file."""
    return os.path.dirname(settings.MEDIA_ROOT)


def request_upgrade() -> str:
    """Drop the marker the host-side upgrade agent (deploy/upgrade.sh) watches.

    The web process can't git-pull or rebuild its own container, so "Upgrade now"
    only writes this file; the host applies the upgrade and writes the result back.
    Returns the marker's path."""
    path = os.path.join(data_dir(), "upgrade-request")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"requested {timezone.now().isoformat()}\n")
    return path


def read_upgrade_result() -> str:
    """The host agent's last upgrade result, or '' if it has not run yet."""
    try:
        with open(os.path.join(data_dir(), "upgrade-result"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""
