"""Rendering labels, and getting them to the printer.

Two halves, deliberately split. **Rendering** happens once for every kind of printer:
a Pillow bitmap at the label's physical size multiplied by the printer's dots per
inch, with real font files (so genuine bold and italic), word-wrapping, shrink-to-fit,
and an optional barcode composited in. **Encoding** is printer-specific and lives in
`label_drivers`, one class per printer language. This module owns the pixel maths, the
size table, and the trip to the print bridge on the Pi.

The GK420T this was built around understands only ZPL, and ZPL's own font commands are
limited -- no italics at all, and "bold" is a hack -- which is why a label is rendered
as a complete bitmap rather than as text with font commands.

`DPI` is a module constant rather than a setting lookup for the benefit of the label
size table and the tests; the number actually used to render comes from
`configured_dpi()`, which is the printer's own resolution unless the owner has said
otherwise in Settings.
"""
import io

from PIL import Image, ImageDraw, ImageFont

from .label_drivers import get_driver

DPI = 203  # GK420T native resolution

# The 3 physical label sizes Seth actually owns (see docs/HANDOFF.md item 1).
LABEL_SIZES = {
    "large": {"display": 'General 4"×2"', "width_in": 4.0, "height_in": 2.0},
    "tote": {"display": 'Tote 2"×1"', "width_in": 2.0, "height_in": 1.0},
    "barcode": {"display": 'Barcode 1"×0.5"', "width_in": 1.0, "height_in": 0.5},
}

# Font resolution is a per-platform fallback chain, tried in order, because this
# runs on four kinds of machine: a Debian container, macOS, the Pi kiosk, and
# eventually other people's machines — including Windows. Seth's instance uses
# DejaVu; a Mac or Windows user gets their own system font instead of a crash.
#
# The last resort uses load_default(size=...) rather than bare load_default(),
# which renders at a fixed tiny size and ignores size_px entirely — so a machine
# with none of these fonts would print unreadable labels instead of failing loudly.
# The sized form returns a real scalable font.
_FONT_CANDIDATES = {
    (False, False): [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux (Docker/Pi)
        "/System/Library/Fonts/Supplemental/Arial.ttf",  # macOS
        "C:/Windows/Fonts/arial.ttf",  # Windows
    ],
    (True, False): [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    (False, True): [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
        "C:/Windows/Fonts/ariali.ttf",
    ],
    (True, True): [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
        "C:/Windows/Fonts/arialbi.ttf",
    ],
}


def _load_font(bold, italic, size_px):
    for path in _FONT_CANDIDATES[(bool(bold), bool(italic))]:
        try:
            return ImageFont.truetype(path, size_px)
        except OSError:
            continue
    return ImageFont.load_default(size=size_px)


def _wrap_text(draw, text, font, max_width):
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def configured_dpi() -> int:
    """The resolution to render at: the printer's own, unless the owner overrode it.

    The override exists for a real case rather than completeness. A printer family
    spans resolutions -- a Zebra GK420T is 203dpi and the 300dpi version is otherwise
    the same machine, Brother QLs are 300, Dymo LabelWriters are 203 -- and rendering
    at the wrong one produces a label that is the right shape and the wrong size.
    """
    from . import hardware_config

    return hardware_config.printer_dpi() or get_driver(hardware_config.printer_driver()).default_dpi


def render_label(text, size_key, font_pt=24, bold=False, italic=False, barcode_value="", dpi=None):
    """Returns a 1-bit Pillow Image (white background, black ink) at the label's
    exact pixel dimensions for the given (or configured) DPI."""
    dpi = dpi or configured_dpi()
    size = LABEL_SIZES[size_key]
    width_px = round(size["width_in"] * dpi)
    height_px = round(size["height_in"] * dpi)
    margin = max(4, round(dpi * 0.06))

    image = Image.new("L", (width_px, height_px), color=255)
    draw = ImageDraw.Draw(image)

    text_area_top = margin
    text_area_bottom = height_px - margin

    if barcode_value:
        import barcode
        from barcode.writer import ImageWriter

        writer = ImageWriter()
        writer.dpi = dpi
        bc = barcode.get("code128", barcode_value, writer=writer)
        bc_image = bc.render({"write_text": False, "quiet_zone": 1, "module_height": 8})

        bc_max_width = width_px - 2 * margin
        bc_max_height = round(height_px * 0.45)
        scale = min(bc_max_width / bc_image.width, bc_max_height / bc_image.height)
        bc_image = bc_image.resize((max(1, round(bc_image.width * scale)), max(1, round(bc_image.height * scale))))
        bc_x = (width_px - bc_image.width) // 2
        image.paste(bc_image.convert("L"), (bc_x, margin))
        text_area_top = margin + bc_image.height + margin

    if text.strip():
        font_size_px = round(font_pt * dpi / 72)
        font = _load_font(bold, italic, font_size_px)
        max_text_width = width_px - 2 * margin
        lines = _wrap_text(draw, text.strip(), font, max_text_width)

        line_height = font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + round(font_size_px * 0.25)
        total_text_height = line_height * len(lines)
        available_height = text_area_bottom - text_area_top

        # Shrink to fit rather than overflow the label if the text is too long/large.
        while total_text_height > available_height and font_size_px > 6:
            font_size_px -= 1
            font = _load_font(bold, italic, font_size_px)
            lines = _wrap_text(draw, text.strip(), font, max_text_width)
            line_height = font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + round(font_size_px * 0.25)
            total_text_height = line_height * len(lines)

        y = text_area_top + max(0, (available_height - total_text_height) // 2)
        for line in lines:
            line_width = draw.textlength(line, font=font)
            x = (width_px - line_width) // 2
            draw.text((x, y), line, font=font, fill=0)
            y += line_height

    return image.convert("1"), width_px, height_px


def render_label_png_bytes(text, size_key, font_pt=24, bold=False, italic=False, barcode_value="", dpi=None):
    """For the live preview endpoint -- same render, returned as PNG bytes.

    Rendered at the printer's own resolution on purpose, so the preview shows what
    will actually come out rather than a differently-proportioned likeness.
    """
    image, _, _ = render_label(text, size_key, font_pt, bold, italic, barcode_value, dpi=dpi)
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def too_wide_message(driver, size_key, width_px, dpi) -> str:
    """Why this label cannot go on this printer, in the owner's own terms.

    Worth saying properly rather than truncating: a print head is only as wide as it
    is, and clipping is silent. Inches are what label stock is sold in and what the
    owner picked from, so both units appear.
    """
    display = LABEL_SIZES[size_key]["display"]
    return (
        f"A {display} label is {width_px} dots wide at {dpi}dpi, and {driver.name} prints "
        f"{driver.max_width_dots} dots across — it would be clipped. Use a narrower label "
        "size, or a different printer."
    )


def print_label(text, size_key, font_pt=24, bold=False, italic=False, barcode_value=""):
    """Renders and sends the label to the Pi's print-bridge. Returns (ok, error_message).

    The bytes and their content type come from the configured driver, so the bridge
    stays a relay for everything except CUPS (where it spools the image instead).
    """
    from . import hardware_config

    url = hardware_config.printer_url()
    if not url:
        return False, "No label printer configured yet — set one up under Settings."

    driver = get_driver(hardware_config.printer_driver())
    dpi = configured_dpi()
    image, width_px, height_px = render_label(
        text, size_key, font_pt, bold, italic, barcode_value, dpi=dpi
    )

    # Refuse rather than send something the printer will quietly crop. Checked here
    # rather than in the driver because the message needs the label size, which is a
    # rendering concern, not an encoding one.
    if driver.max_width_dots and width_px > driver.max_width_dots:
        return False, too_wide_message(driver, size_key, width_px, dpi)

    payload = driver.encode(image, width_px, height_px)

    import requests

    key = hardware_config.printer_key()
    headers = {"X-Api-Key": key} if key else {}
    try:
        resp = requests.post(
            f"{url}/print",
            data=payload,
            headers={**headers, "Content-Type": driver.content_type},
            timeout=10,
        )
        resp.raise_for_status()
        return True, None
    except requests.RequestException as exc:
        return False, str(exc)
