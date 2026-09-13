"""Custom label rendering + printing for the Zebra GK420T.

The GK420T only understands ZPL. Rather than hand-rolling ZPL's limited (and
italic-less) built-in font commands, labels are rendered as a full-bitmap image
with Pillow (real font files -> real bold/italic/size control, plus an optional
barcode composited in) and shipped to the printer as one ZPL ^GFA graphic field.
The Pi's print-bridge (label-printer/pi/server.py) just relays those raw bytes
to the printer over USB -- all the actual layout/rendering happens here.
"""
import io

from PIL import Image, ImageDraw, ImageFont

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


def render_label(text, size_key, font_pt=24, bold=False, italic=False, barcode_value=""):
    """Returns a 1-bit Pillow Image (white background, black ink) at the label's
    exact pixel dimensions for this printer's DPI."""
    size = LABEL_SIZES[size_key]
    width_px = round(size["width_in"] * DPI)
    height_px = round(size["height_in"] * DPI)
    margin = max(4, round(DPI * 0.06))

    image = Image.new("L", (width_px, height_px), color=255)
    draw = ImageDraw.Draw(image)

    text_area_top = margin
    text_area_bottom = height_px - margin

    if barcode_value:
        import barcode
        from barcode.writer import ImageWriter

        writer = ImageWriter()
        writer.dpi = DPI
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
        font_size_px = round(font_pt * DPI / 72)
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


def image_to_zpl(image, width_px, height_px):
    """Packs a 1-bit Pillow image into a ZPL ^GFA (ASCII hex) graphic field."""
    bytes_per_row = (width_px + 7) // 8
    total_bytes = bytes_per_row * height_px

    # Pillow's '1' mode: 255 = white, 0 = black. ZPL ^GFA: bit 1 = print (black).
    packed = bytearray(total_bytes)
    pixels = image.load()
    for y in range(height_px):
        row_offset = y * bytes_per_row
        for x in range(width_px):
            if pixels[x, y] == 0:
                packed[row_offset + (x // 8)] |= 0x80 >> (x % 8)

    hex_data = packed.hex().upper()
    width_dots = width_px
    height_dots = height_px
    zpl = (
        "^XA\n"
        f"^PW{width_dots}\n"
        f"^LL{height_dots}\n"
        f"^FO0,0^GFA,{total_bytes},{total_bytes},{bytes_per_row},{hex_data}^FS\n"
        "^XZ\n"
    )
    return zpl


def render_label_png_bytes(text, size_key, font_pt=24, bold=False, italic=False, barcode_value=""):
    """For the live preview endpoint -- same render, returned as PNG bytes."""
    image, _, _ = render_label(text, size_key, font_pt, bold, italic, barcode_value)
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def print_label(text, size_key, font_pt=24, bold=False, italic=False, barcode_value=""):
    """Renders and sends the label to the Pi's print-bridge. Returns (ok, error_message)."""
    from .hardware_config import printer_key, printer_url

    url = printer_url()
    if not url:
        return False, "No label printer configured yet — set one up under Settings."

    image, width_px, height_px = render_label(text, size_key, font_pt, bold, italic, barcode_value)
    zpl = image_to_zpl(image, width_px, height_px)

    import requests

    key = printer_key()
    headers = {"X-Api-Key": key} if key else {}
    try:
        resp = requests.post(
            f"{url}/print",
            data=zpl.encode("utf-8"),
            headers={**headers, "Content-Type": "application/x-zpl"},
            timeout=10,
        )
        resp.raise_for_status()
        return True, None
    except requests.RequestException as exc:
        return False, str(exc)
