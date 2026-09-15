"""The setup wizard: the pages that turn a fresh clone into someone's workshop.

Two jobs in one set of pages, deliberately:

* **First run.** A brand-new install has no account, no name and no hardware settings,
  and its root URL used to lead to a login page with nothing to log in with. These are
  the pages a new owner lands on instead.
* **Settings.** The same pages stay reachable afterwards, because "change my workshop's
  name" and "point the app at a different printer" should not need a rebuild or a trip
  into /admin/. A wizard you can only run once is a wizard people work around.

Every step is skippable, and that is a feature rather than a compromise. An install
with no lights, no printer and no interest in the community map is a perfectly good
workshop; those steps exist to be declined as much as accepted, and nothing later
depends on them having been accepted.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    blurb: str
    url_name: str
    # Required steps are the ones with nothing sensible to default: you cannot have a
    # site without a name, or a login you can get back into without an account.
    required: bool = False


ACCOUNT = Step(
    "account",
    "Your account",
    "The login you'll use from now on. This is the only step that isn't optional.",
    "inventory:setup_account",
    required=True,
)
SITE = Step(
    "site",
    "Name and place",
    "What this workshop is called, and which timezone its timestamps are in.",
    "inventory:setup_site",
    required=True,
)
LIGHTS = Step(
    "lights",
    "Lights",
    "Tell the app about your LED controller, so it can point at a drawer.",
    "inventory:setup_lights",
)
FLASH = Step(
    "flash",
    "Flash the LED controller",
    "Put the firmware on the board that drives the strips. The app walks you through it.",
    "inventory:setup_flash",
)
PRINTER = Step(
    "printer",
    "Labels",
    "Tell the app about your label printer, so it can print shelf labels.",
    "inventory:setup_printer",
)
REFERENCE = Step(
    "reference",
    "Reference library",
    "Optionally start with a set of charts, pinouts and guides.",
    "inventory:setup_reference",
)
COMMUNITY = Step(
    "community",
    "Community",
    "Whether other workshops nearby can see that you exist.",
    "inventory:setup_community",
)
EMAIL = Step(
    "email",
    "Email notifications",
    "Get an email when you're messaged, connected to, or searched — so you don't miss things when you're not logged in.",
    "inventory:setup_email",
)
AI = Step(
    "ai",
    "Research & AI",
    "Set the AI keys that power enrichment and web research — both optional.",
    "inventory:setup_ai",
)
ACCESS = Step(
    "access",
    "Reaching it from outside",
    "How to use this from your phone, or on your own domain.",
    "inventory:setup_access",
)
FINISH = Step("finish", "Done", "That's everything.", "inventory:setup_finish")

# Order matters: it is the order the pages are presented in, and the order "what's
# next" follows. Flashing sits right after Lights because that is the order the physical
# job happens in: point the app at the controller, then put firmware on the board.
_ALL_STEPS = [ACCOUNT, SITE, LIGHTS, FLASH, PRINTER, REFERENCE, COMMUNITY, EMAIL, AI, ACCESS]


def account_exists() -> bool:
    """Whether anyone can log in yet.

    The account step is only offered while this is false. Once an account exists the
    step disappears rather than sitting there inviting a second one — creating
    additional users is an /admin/ job, not part of setting up a workshop.
    """
    try:
        from django.contrib.auth import get_user_model

        return get_user_model().objects.exists()
    except Exception:
        # No auth tables yet (mid-migrate). Reporting "an account exists" hides the
        # step rather than offering one that would fail, and the setup gate treats
        # this same case as "not virgin", so the two agree.
        return True


def visible_steps() -> list[Step]:
    return [step for step in _ALL_STEPS if step.key != "account" or not account_exists()]


def step_by_key(key: str) -> Step | None:
    for step in _ALL_STEPS + [FINISH]:
        if step.key == key:
            return step
    return None


def next_step_after(key: str) -> Step | None:
    """The step after this one in the visible order, or the finish page at the end."""
    steps = visible_steps()
    for index, step in enumerate(steps):
        if step.key == key:
            return steps[index + 1] if index + 1 < len(steps) else FINISH
    return FINISH


def required_outstanding() -> list[Step]:
    """Required steps that still have nothing filled in.

    Used for the "you haven't quite finished" nudge, never to block anyone — see the
    setup gate in middleware, which deliberately only cares whether an account exists.
    """
    from .site_config import get_site_settings

    outstanding = []
    site = get_site_settings()
    for step in _ALL_STEPS:
        if not step.required:
            continue
        if step.key == "account" and account_exists():
            continue
        if step.key == "site" and site and site.site_name:
            continue
        outstanding.append(step)
    return outstanding
