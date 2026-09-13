"""Measurement units for stock quantities.

A quantity is a plain number; the unit says what the number counts. Most parts in
a workshop are "each" and always will be, so that is the default and a part only
carries a real unit when it is genuinely sold by length or weight — wire, tubing,
heat-shrink, filament, solder, glue.

**Deliberately not a conversion layer.** The app never converts between units.
Converting would silently rewrite numbers the owner counted by hand, and "I have
5 metres of this" becoming "500 centimetres" is a data-entry decision, not an
arithmetic one that software should make on its own. The unit is a label on the
number and nothing more.

That restraint is also what keeps this additive: existing rows have no unit, mean
"each", and display exactly as they did before.
"""
from __future__ import annotations

DEFAULT_UNIT = "ea"

# code -> (singular, plural, short symbol). The symbol is what gets printed on
# labels and shown next to a number, so it stays short.
UNIT_CHOICES = [
    ("ea", ("each", "each", "")),
    ("m", ("metre", "metres", "m")),
    ("cm", ("centimetre", "centimetres", "cm")),
    ("mm", ("millimetre", "millimetres", "mm")),
    ("ft", ("foot", "feet", "ft")),
    ("in", ("inch", "inches", "in")),
    ("g", ("gram", "grams", "g")),
    ("kg", ("kilogram", "kilograms", "kg")),
    ("oz", ("ounce", "ounces", "oz")),
    ("lb", ("pound", "pounds", "lb")),
    ("ml", ("millilitre", "millilitres", "ml")),
    ("l", ("litre", "litres", "l")),
]

UNITS = {code: names for code, names in UNIT_CHOICES}

METRIC_UNITS = ["ea", "m", "cm", "mm", "g", "kg", "ml", "l"]
IMPERIAL_UNITS = ["ea", "ft", "in", "oz", "lb"]
UNIT_SYSTEMS = [("metric", "Metric (metres, grams)"), ("imperial", "Imperial (feet, ounces)")]

# Django field choices: (code, human label)
STOCK_UNIT_CHOICES = [(code, names[1].capitalize()) for code, names in UNIT_CHOICES]


def is_known(unit: str) -> bool:
    return (unit or "") in UNITS


def symbol(unit: str) -> str:
    """The short form printed next to a number. Empty for 'each'.

    "each" gets no symbol on purpose: "5" reads better than "5 ea" in every list
    the app already shows, so the common case stays exactly as it looks today.
    """
    return UNITS.get(unit or DEFAULT_UNIT, UNITS[DEFAULT_UNIT])[2]


def label(unit: str, qty=None) -> str:
    """Full unit name, pluralised against the quantity when one is given."""
    singular, plural, _ = UNITS.get(unit or DEFAULT_UNIT, UNITS[DEFAULT_UNIT])
    if qty is None:
        return plural
    try:
        return singular if float(qty) == 1 else plural
    except (TypeError, ValueError):
        return plural


def format_quantity(qty, unit: str = DEFAULT_UNIT) -> str:
    """A quantity for display: '5 m', '1 ft', or just '5' for plain counts.

    `None` means "quantity unknown", which this app already distinguishes from zero
    (see StockItem.quantity_raw), so it is not rendered as a number.
    """
    if qty is None or qty == "":
        return "unknown" if unit else "unknown qty"
    sym = symbol(unit)
    return f"{qty} {sym}".strip()


def units_for_system(unit_system: str) -> list[str]:
    """The unit codes to offer first for a metric or imperial install.

    Only affects ordering in pickers — every unit stays selectable either way,
    because a UK workshop stocked from US suppliers genuinely has both.
    """
    preferred = IMPERIAL_UNITS if unit_system == "imperial" else METRIC_UNITS
    other = [u for u in METRIC_UNITS + IMPERIAL_UNITS if u not in preferred]
    return preferred + other
