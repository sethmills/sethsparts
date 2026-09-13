"""Turning a rendered label into the bytes one particular printer understands.

Rendering happens once, in `label_printing`: a Pillow bitmap at the pixel size the
label and the printer's dot density call for. What differs between printers is only
what you do with that bitmap, and that is all this module is.

**What has actually been tested, since it is the whole point of having this file.**
Only the ZPL path has been near real hardware. It prints every label Seth's workshop
has ever produced, from a GK420T. The other three are written from the manufacturers'
own documentation, cited per driver, and have **never been tried on the hardware they
target** -- see each driver's `note`, which is what the settings page and the help
pages show the owner. They are not guesses, but they are unverified, and the
difference between those two things is exactly what a project like this tends to lose.

A second thing worth knowing before editing: label *sizes* are physical inches
(`LABEL_SIZES`), and each printer has a fixed-width print head. A 4"-wide label is 1200
dots at 300dpi and simply does not fit a Brother QL (720 dots) or a Dymo (448) -- so
every driver declares `max_width_dots` and `print_label` refuses rather than quietly
sending something the printer will clip.
"""
from __future__ import annotations

import io
from dataclasses import dataclass


def _rows_as_bits(image, width_px: int, height_px: int, stride_bytes: int) -> list[bytes]:
    """The bitmap as one fixed-width row of bytes per line, MSB first, 1 = ink.

    Two conventions have to be flipped from what Pillow gives us, and getting either
    wrong prints something that looks like a font or layout bug rather than an
    encoding bug:

    * Pillow's "1" mode stores 255 for white. Every printer format here wants a set
      bit to mean "put ink here".
    * Every one of these formats is most-significant-bit-first, so the leftmost dot in
      a byte is bit 7. Dymo's manual states this directly; ZPL's ^GFA is the same.

    `stride_bytes` is the printer's own line width, not the image's: a printer with a
    fixed print head expects whole lines of its full width, so the unused right-hand
    side is zero-padded rather than omitted.
    """
    pixels = image.load()
    rows = []
    for y in range(height_px):
        row = bytearray(stride_bytes)
        for x in range(width_px):
            if pixels[x, y] == 0:
                row[x // 8] |= 0x80 >> (x % 8)
        rows.append(bytes(row))
    return rows


@dataclass(frozen=True)
class LabelDriver:
    """One printer language.

    `tested` is a claim about hardware, not about code quality, and it is deliberately
    a field rather than a comment so the UI can tell the owner the truth without
    anyone having to remember to update prose.
    """

    key: str
    name: str
    default_dpi: int
    tested: bool
    content_type: str
    max_width_dots: int | None
    reference: str
    note: str

    def encode(self, image, width_px: int, height_px: int) -> bytes:  # pragma: no cover
        raise NotImplementedError


class ZebraZplDriver(LabelDriver):
    """Zebra's ZPL, as a bitmap graphic field."""

    def encode(self, image, width_px, height_px) -> bytes:
        return zpl_graphic_field(image, width_px, height_px).encode("utf-8")


class BrotherQlDriver(LabelDriver):
    """Brother's QL raster commands, uncompressed.

    The manual describes an optional TIFF compression mode for the raster data; this
    sends plain lines instead. Compression would cut the transfer size, but it is
    another encoding to get exactly right on a printer nobody here can test against,
    and a label is a few kilobytes either way.
    """

    def encode(self, image, width_px, height_px) -> bytes:
        return brother_ql_raster(image, width_px, height_px)


class DymoLabelWriterDriver(LabelDriver):
    """Dymo LabelWriter "raster mode" graphics (SYN lines)."""

    def encode(self, image, width_px, height_px) -> bytes:
        return dymo_raster(image, width_px, height_px)


class CupsDriver(LabelDriver):
    """Hand the printer's own driver the picture and let it do the work.

    Not a printer language at all: the PNG goes to the print bridge, which spools it
    with `lp`, and whatever driver that queue has installed does the rendering. This is
    the route for a printer nobody has written an encoder for -- including one whose
    own manufacturer's driver already handles it properly.
    """

    def encode(self, image, width_px, height_px) -> bytes:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        return buffer.getvalue()


# ---------------------------------------------------------------------------
# ZPL
# ---------------------------------------------------------------------------

def zpl_graphic_field(image, width_px: int, height_px: int) -> str:
    """Packs a 1-bit image into a ZPL ^GFA (ASCII hex) graphic field.

    The whole label is one graphic: ZPL's own fonts cannot do italics and its "bold"
    is a hack, so the bitmap carries the typography and ZPL only has to place it.
    """
    bytes_per_row = (width_px + 7) // 8
    total_bytes = bytes_per_row * height_px

    packed = bytearray()
    for row in _rows_as_bits(image, width_px, height_px, bytes_per_row):
        packed += row

    hex_data = packed.hex().upper()
    return (
        "^XA\n"
        f"^PW{width_px}\n"
        f"^LL{height_px}\n"
        f"^FO0,0^GFA,{total_bytes},{total_bytes},{bytes_per_row},{hex_data}^FS\n"
        "^XZ\n"
    )


# ---------------------------------------------------------------------------
# Brother QL
# ---------------------------------------------------------------------------

# The QL print head is 720 dots wide and every raster line is 90 bytes regardless of
# which tape is loaded; the tape's position on the head is what varies. These come
# from the raster-line table in the manual for 62mm continuous tape, which is the
# widest and the default assumption here: 12 pins of left margin, 696 pins of print
# area, 12 pins of right margin.
#
# A narrower tape sits further from the left edge (29mm tape starts at pin 408), so
# this constant is the single most likely thing to need changing to match the tape in
# the printer. That is exactly the kind of detail that only a real printer can settle.
_BROTHER_HEAD_BYTES = 90
_BROTHER_PRINT_AREA_DOTS = 696
_BROTHER_LEFT_MARGIN_DOTS = 12
_BROTHER_INVALIDATE_BYTES = 400  # "sends a 400-byte invalidate command"

#: The tape width this Brother driver declares to the printer, in mm. 62mm is the
#: widest QL tape, and the media width has to match what is loaded or the printer
#: reports an error rather than printing.
_BROTHER_TAPE_WIDTH_MM = 62


def brother_ql_raster(image, width_px: int, height_px: int) -> bytes:
    """A complete Brother QL print job for one label.

    Job structure, in the order the manual gives it: a 400-byte invalidate, an
    initialize, the per-page control codes, the raster lines, then Control-Z to print
    the last page and feed it.
    """
    out = bytearray()

    # (1) Initialization -- once per job.
    out += b"\x00" * _BROTHER_INVALIDATE_BYTES
    out += b"\x1b\x40"  # ESC @ initialize

    # (2) Control codes -- once per page.
    out += b"\x1b\x69\x61\x01"  # ESC i a 01: switch to raster mode
    out += b"\x1b\x69\x21\x00"  # ESC i ! 00: no automatic status notification

    # ESC i z: print information. The valid flag says which of the values that follow
    # the printer should believe: 0x02 media type, 0x04 media width, 0x80 recovery
    # always on. Media type 0x0A is continuous tape; a die-cut label would be 0x0B and
    # would have to match the media actually loaded, or the printer reports an error.
    raster_count = height_px
    out += bytes([
        0x1B, 0x69, 0x7A,           # ESC i z
        0x86,                       # valid: media type + width + recovery
        0x0A,                       # continuous length tape
        _BROTHER_TAPE_WIDTH_MM,     # media width, mm
        0x00,                       # media length, mm (0 for continuous)
        raster_count & 0xFF,        # raster number, little-endian...
        (raster_count >> 8) & 0xFF,
        (raster_count >> 16) & 0xFF,
        (raster_count >> 24) & 0xFF,
        0x00,                       # ...then the two trailing zeros the manual lists
        0x00,
    ])
    out += b"\x1b\x69\x4d\x40"  # ESC i M 40: auto cut
    out += b"\x1b\x69\x41\x01"  # ESC i A 01: cut after each label
    out += b"\x1b\x69\x4b\x08"  # ESC i K 08: cut at end
    out += bytes([0x1B, 0x69, 0x64, 0x23, 0x00])  # ESC i d: 3mm margin (35 dots at 300dpi)

    # (3) Raster data. Both margins and any unused head width are zeroed by
    # _rows_as_bits, so only the left-margin offset has to be applied here.
    for row in _rows_as_bits(image, width_px, height_px, _BROTHER_HEAD_BYTES):
        shifted = _shift_right(row, _BROTHER_LEFT_MARGIN_DOTS)
        out += bytes([0x67, 0x00, _BROTHER_HEAD_BYTES])  # g 00 5A (90)
        out += shifted

    # (4) Print. Control-Z prints the last page and feeds it; FF (0x0C) would be used
    # for pages that are not the last.
    out += b"\x1a"
    return bytes(out)


def _shift_right(row: bytes, dots: int) -> bytes:
    """Moves a whole line `dots` bits towards the right-hand margin.

    The QL's raster data starts at the print area rather than at the head's left edge,
    so a line drawn at bit 0 would land 12 dots (1mm) left of where the label expects
    it. Implemented with a single integer so the carry between bytes is not something
    to get wrong by hand.
    """
    if not dots:
        return row
    value = int.from_bytes(row, "big") >> dots
    return value.to_bytes(len(row), "big")


# ---------------------------------------------------------------------------
# Dymo LabelWriter
# ---------------------------------------------------------------------------

# From Dymo's LabelWriter technical reference: the print head has 448 elements
# (0.125mm square, eight dots per millimetre) and the host must send the whole line
# every time, because "there is no command for clearing the shift register". So the
# line width is fixed at 56 bytes and a narrow label is padded, not shortened.
_DYMO_HEAD_BYTES = 56
_DYMO_HEAD_DOTS = 448


def dymo_raster(image, width_px: int, height_px: int) -> bytes:
    """A complete Dymo LabelWriter print job for one label.

    Each line is a SYN (0x16) followed by the bytes-per-line, which is what ESC D
    declares; ESC B says where the line starts (0 = the left edge of the label); ESC E
    is the form feed that prints the buffer and advances the media.
    """
    out = bytearray()
    out += b"\x1b\x40"  # ESC @ -- reset to the power-up condition
    out += bytes([0x1B, 0x42, 0x00])  # ESC B 0: start at the left margin
    out += bytes([0x1B, 0x44, _DYMO_HEAD_BYTES])  # ESC D: bytes per line

    for row in _rows_as_bits(image, width_px, height_px, _DYMO_HEAD_BYTES):
        out += bytes([0x16])  # SYN
        out += row

    out += b"\x1b\x45"  # ESC E: form feed
    return bytes(out)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

DRIVERS: dict[str, LabelDriver] = {
    "zpl": ZebraZplDriver(
        key="zpl",
        name="Zebra / ZPL",
        default_dpi=203,
        tested=True,
        content_type="application/x-zpl",
        # A GK420T prints 4.09" across, so a full-width 4" label fits with room to spare.
        max_width_dots=832,
        reference="ZPL II programming guide; ^GFA graphic field",
        note="Tested against a real Zebra GK420T — every label this app prints today goes through it.",
    ),
    "brother_ql": BrotherQlDriver(
        key="brother_ql",
        name="Brother QL",
        default_dpi=300,
        tested=False,
        content_type="application/vnd.brother-ql",
        max_width_dots=_BROTHER_PRINT_AREA_DOTS,
        reference="Brother Software Developer's Manual — Raster Command Reference, QL-800 series, v1.01",
        note=(
            "Written to Brother's documented raster commands. Never tried on a real Brother "
            "printer, and it assumes the widest (62mm) tape is loaded — check that matches the "
            "tape you have."
        ),
    ),
    "dymo": DymoLabelWriterDriver(
        key="dymo",
        name="Dymo LabelWriter",
        default_dpi=203,
        tested=False,
        content_type="application/vnd.dymo-labelwriter",
        max_width_dots=_DYMO_HEAD_DOTS,
        reference="Dymo LabelWriter technical reference (SE450 command set)",
        note=(
            "Written to Dymo's documented raster commands. Never tried on a real Dymo printer. "
            "Its head is 448 dots, so only the narrower label sizes fit."
        ),
    ),
    "cups": CupsDriver(
        key="cups",
        name="Any printer, via CUPS",
        default_dpi=300,
        tested=False,
        content_type="image/png",
        max_width_dots=None,
        reference="CUPS on the print-bridge host; the queue's own driver does the rendering",
        note=(
            "Sends the label as an image to a CUPS queue on the print bridge, so the printer's "
            "own driver decides how to print it. Untested here too, but it has nothing to get "
            "wrong in the printer's language, which makes it the most likely to work first."
        ),
    ),
}


def get_driver(key: str) -> LabelDriver:
    """The driver for a stored key, falling back to ZPL.

    An unknown key can only come from a hand-edited database or an older install
    carrying a value this version has dropped, and neither should take the label page
    down -- ZPL is the one that has been tested, so that is the safe direction to fail.
    """
    return DRIVERS.get(key or "", DRIVERS["zpl"])


def driver_keys() -> list[str]:
    """The registry's keys, in the order the settings page offers them."""
    return list(DRIVERS)
