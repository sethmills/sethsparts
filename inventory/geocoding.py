"""Turn a postcode or ZIP code into a deliberately coarse point.

Whatever the owner types, what gets stored is a postcode-AREA centroid: a UK outcode
(``SW1A``) or a US ZIP. **Even when they type a full postcode**, this resolves it to
its outcode first and looks up the outcode's centroid. That is the whole privacy
mechanism, and doing it here rather than asking the owner to type less is what makes
it reliable: a full UK postcode identifies roughly fifteen households, so publishing
one publishes a doorstep, and people type their own postcode by reflex.

There is no rounding or grid-snapping step anywhere in this feature. The coarseness
comes from the source being an area, which is why there is nothing to tune and
nothing to get wrong.

Three providers, tried in order, because no single free one covers everything —
Zippopotam, verified directly, returns 404 for UK postcodes:

1. **postcodes.io** — UK outcodes. Free, no key, no registration.
2. **Zippopotam.us** — US ZIP codes. Free, no key.
3. **Nominatim** (OpenStreetMap) — anything else. Free, but asks for a genuine
   User-Agent and low request volume, which one setup step comfortably satisfies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

import requests

from .archiving import USER_AGENT

TIMEOUT = 10

# A UK postcode: outward code, then the inward code. The outward code is the part
# that is safe to publish — it is a district, not a street.
UK_POSTCODE = re.compile(r"^([A-Z]{1,2}[0-9][A-Z0-9]?)([0-9][A-Z]{2})?$")


@dataclass
class GeoResult:
    ok: bool
    lat: float | None = None
    lon: float | None = None
    label: str = ""
    source: str = ""
    error: str = ""

    @property
    def has_point(self) -> bool:
        return self.lat is not None and self.lon is not None


def uk_outcode(text: str) -> str:
    """The outward code from a UK postcode, or the outcode itself if that's all there is.

    Returns "" for anything that isn't shaped like a UK postcode, so the caller can
    fall through to the next provider rather than being told a wrong answer.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", text or "").upper()
    match = UK_POSTCODE.match(cleaned)
    return match.group(1) if match else ""


def lookup(text: str, country: str = "") -> GeoResult:
    """Find a coarse point for whatever the owner typed. Never raises."""
    raw = (text or "").strip()
    if not raw:
        return GeoResult(ok=False, error="Nothing to look up.")

    country = (country or "").upper()

    # Try the UK outcode first when the input even slightly resembles one, because a
    # UK outcode is a much more specific signal than a ZIP and misrouting it to the
    # US provider is a guaranteed 404.
    outcode = uk_outcode(raw)
    if outcode and country in ("", "GB", "UK"):
        result = _postcodes_io(outcode)
        if result.ok:
            return result

    if country in ("", "US"):
        result = _zippopotam(raw)
        if result.ok:
            return result

    return _nominatim(raw, country)


def _postcodes_io(outcode: str) -> GeoResult:
    url = f"https://api.postcodes.io/outcodes/{quote(outcode)}"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return GeoResult(ok=False, error=f"Couldn't reach postcodes.io: {exc}")
    if response.status_code == 404:
        return GeoResult(ok=False, error=f"postcodes.io doesn't know “{outcode}”.")
    if response.status_code >= 400:
        return GeoResult(ok=False, error=f"postcodes.io returned HTTP {response.status_code}.")
    try:
        data = response.json().get("result") or {}
        return GeoResult(
            ok=True,
            lat=float(data["latitude"]),
            lon=float(data["longitude"]),
            label=data.get("outcode", outcode),
            source="outcode",
        )
    except (KeyError, TypeError, ValueError) as exc:
        return GeoResult(ok=False, error=f"postcodes.io sent something unexpected: {exc}")


def _zippopotam(zip_code: str) -> GeoResult:
    cleaned = re.sub(r"[^0-9]", "", zip_code)[:5]
    if len(cleaned) < 5:
        return GeoResult(ok=False, error="That doesn't look like a US ZIP code.")
    url = f"https://api.zippopotam.us/us/{cleaned}"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return GeoResult(ok=False, error=f"Couldn't reach the ZIP lookup: {exc}")
    if response.status_code == 404:
        return GeoResult(ok=False, error=f"No US ZIP code “{cleaned}”.")
    if response.status_code >= 400:
        return GeoResult(ok=False, error=f"The ZIP lookup returned HTTP {response.status_code}.")
    try:
        places = response.json().get("places") or []
        first = places[0]
        return GeoResult(
            ok=True,
            lat=float(first["latitude"]),
            lon=float(first["longitude"]),
            label=cleaned,
            source="zip",
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return GeoResult(ok=False, error=f"The ZIP lookup sent something unexpected: {exc}")


def _nominatim(text: str, country: str) -> GeoResult:
    query = f"{text}, {country}" if country else text
    url = f"https://nominatim.openstreetmap.org/search?q={quote(query)}&format=json&limit=1"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return GeoResult(ok=False, error=f"Couldn't reach OpenStreetMap: {exc}")
    if response.status_code >= 400:
        return GeoResult(ok=False, error=f"OpenStreetMap returned HTTP {response.status_code}.")
    try:
        results = response.json()
        if not results:
            return GeoResult(ok=False, error=f"Couldn't find “{text}”.")
        first = results[0]
        return GeoResult(
            ok=True,
            lat=float(first["lat"]),
            lon=float(first["lon"]),
            label=(first.get("display_name") or text).split(",")[0],
            source="nominatim",
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return GeoResult(ok=False, error=f"OpenStreetMap sent something unexpected: {exc}")
