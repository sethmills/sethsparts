"""Lightweight "search by function/class, not just name" support.

No runtime AI call — just a hand-maintained synonym map so a query like "display" or
"motor driver" surfaces parts whose name doesn't literally contain that word but whose
category/description does (e.g. "1.8 inch spi tft module" for "display").
"""

import re

from django.db.models import Q

KEYWORD_SYNONYMS = {
    "display": ["display", "oled", "tft", "lcd", "screen", "e-ink", "eink", "epaper"],
    "screen": ["display", "oled", "tft", "lcd", "screen"],
    "relay": ["relay", "switch"],
    "motor": ["motor", "servo", "stepper"],
    "motor driver": ["motor driver", "h-bridge", "hbridge", "l298", "l293", "bts7960", "stepper driver", "driver"],
    "driver": ["driver", "h-bridge", "controller"],
    "wifi": ["wifi", "esp32", "esp8266", "wireless", "nodemcu", "wemos"],
    "bluetooth": ["bluetooth", "ble", "bluefruit", "nrf51", "nrf52"],
    "gps": ["gps", "gnss"],
    "camera": ["camera", "cam", "lens"],
    "sensor": [
        "sensor", "accelerometer", "gyroscope", "temperature", "humidity", "pressure",
        "proximity", "touch", "imu", "magnetometer", "compass",
    ],
    "audio": ["audio", "speaker", "microphone", "mic", "amp", "amplifier", "sound", "voice", "bonnet"],
    "power": ["power", "battery", "charger", "regulator", "boost", "buck", "psu", "power supply"],
    "battery": ["battery", "liion", "li-ion", "lipo", "li-po", "cell"],
    "case": ["case", "enclosure", "housing"],
    "enclosure": ["case", "enclosure", "housing"],
    "cable": ["cable", "wire", "cord", "lead"],
    "connector": ["connector", "header", "terminal", "plug", "jack"],
    "led": ["led", "neopixel", "light", "lighting"],
    "microcontroller": ["microcontroller", "board", "mcu", "dev board", "development board"],
    "raspberry pi": ["raspberry pi", "raspi", "pi zero", "pi 4", "pi 400"],
    "pi": ["raspberry pi", "raspi", "pi zero"],
    "arduino": ["arduino"],
    "3d printing": ["3d print", "filament", "nozzle", "extruder", "print bed"],
    "filament": ["filament", "3d print"],
    "tool": ["tool", "screwdriver", "wrench", "drill", "pliers", "hammer"],
    "rfid": ["rfid", "nfc"],
    "keyboard": ["keyboard", "keypad", "macropad"],
}


def expand_terms(query):
    """Given a free-text query, return the extra keywords implied by any matching
    function/class term (e.g. "display" -> also search oled/tft/lcd/screen)."""
    q_lower = query.strip().lower()
    if not q_lower:
        return []
    extra = set()
    for key, synonyms in KEYWORD_SYNONYMS.items():
        if key in q_lower or q_lower in key:
            extra.update(synonyms)
    extra.discard(q_lower)
    return sorted(extra)


def build_search_query(query):
    """Q object OR-ing the raw query (plain substring match — forgiving of partial/typo'd
    input) with any synonym expansions (whole-word regex match — short abbreviations like
    "ble" must not match as a substring inside unrelated words like "cable"/"table")."""
    query = query.strip()
    q_obj = Q()
    if query:
        q_obj |= (
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(manufacturer__icontains=query)
            | Q(category__name__icontains=query)
        )
    for term in expand_terms(query):
        pattern = rf"\b{re.escape(term)}\b"
        q_obj |= (
            Q(name__iregex=pattern)
            | Q(description__iregex=pattern)
            | Q(manufacturer__iregex=pattern)
            | Q(category__name__iregex=pattern)
        )
    return q_obj
