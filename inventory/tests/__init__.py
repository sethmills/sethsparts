"""Test package for the inventory app.

Installs a process-wide guard against unintended real HTTP POSTs.

Why this exists: the LED controller and the label print-bridge drive PHYSICAL
HARDWARE in the workshop, and the production container loads a real `.env` with
`LED_CONTROLLER_URL` pointing at the live Pi. A test that forgets to mock
`requests.post` therefore doesn't fail -- it succeeds, by switching the actual
cabinet lights on. That is not hypothetical: an earlier version of
`test_led.py` did exactly this while the suite was run inside the production
image, and had to be undone by hand.

So: any test that wants to exercise the request path must patch
`requests.post` explicitly (see the `LED_ON` / `PRINTER_ON` decorators in
test_led.py and test_labels.py), and any test that doesn't gets a loud
AssertionError instead of a physical side effect.

`mock.patch` saves and restores whatever is at `requests.post` when it enters
and exits, so explicitly-patched tests are unaffected by this guard.
"""
import requests

_original_post = requests.post


def _blocked_post(*args, **kwargs):
    target = args[0] if args else kwargs.get("url", "(no url)")
    raise AssertionError(
        f"A test attempted a REAL HTTP POST to {target!r}. Tests must mock "
        "requests.post -- these endpoints drive physical hardware (the workshop "
        "LEDs and the label printer). Add @mock.patch('requests.post'), or, if "
        "the test is about the 'not configured' path, blank the URL with "
        "override_settings(LED_CONTROLLER_URL='') / (LABEL_PRINTER_URL='')."
    )


requests.post = _blocked_post
