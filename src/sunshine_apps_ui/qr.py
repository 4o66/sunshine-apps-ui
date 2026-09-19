# SPDX-License-Identifier: GPL-3.0-or-later
"""A QR code, from the standard library and nothing else.

There is one URL to encode -- where to report a bug -- and it has to be
readable from a sofa, with a phone, off a television. A link is useless there:
there is no keyboard, no address bar and no way to copy anything out of a
stream.

**Why this is written out rather than depended on.** Adding `qrcode` or `segno`
would mean a third-party import for one static picture, on a program whose only
dependency is Pillow and only for artwork. It would also have to be installed
on Windows, where the bundled interpreter ships exactly two things.

**Why it is not a picture checked into the repository instead.** Then the URL
and the code would be two facts that have to agree, and one day they would not.
Here the code is derived from the URL, so it cannot be stale.

Byte mode, error correction level M, versions 1 to 10 -- which covers any URL
up to 213 characters, and the one here is 46. The output is SVG: no Pillow, no
raster, and it stays sharp on a television.

**How it was checked.** Against two independent implementations, in a scratch
environment, not in this package's dependencies. `python-qrcode` produces
*exactly* this matrix -- mask selection included -- for the issues URL and for
other byte-mode strings. `segno` agrees everywhere except that it writes one
extra `0x00` codeword between the terminated data and the pad codewords, which
decoders never see: they stop at the character count. The spec's own wording
(ISO/IEC 18004 s8.4.9: terminator of at most four 0 bits, then zeros to the
next byte boundary, then the pad codewords) is what is implemented here.

`tests/test_qr.py` carries the resulting matrix as a fixture, so the suite
needs nothing installed to keep this honest.
"""

from typing import List, Optional, Tuple

# --- Galois field arithmetic, for the Reed-Solomon error correction ----------

_EXP = [0] * 512
_LOG = [0] * 256


def _build_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D               # the QR generator polynomial
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_build_tables()


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator(degree: int) -> List[int]:
    poly = [1]
    for i in range(degree):
        poly = _poly_mul(poly, [1, _EXP[i]])
    return poly


def _poly_mul(a: List[int], b: List[int]) -> List[int]:
    out = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] ^= _mul(x, y)
    return out


def _remainder(data: List[int], degree: int) -> List[int]:
    """The error correction codewords for one block."""
    poly = _generator(degree)
    out = list(data) + [0] * degree
    for i in range(len(data)):
        factor = out[i]
        if factor:
            for j, coefficient in enumerate(poly):
                out[i + j] ^= _mul(coefficient, factor)
    return out[len(data):]


# --- what each version holds, at error correction level M --------------------
#
# (total codewords, ec codewords per block, blocks in group 1, blocks in group 2)
# From the specification's table; only level M, only what versions 1-10 need.
_VERSIONS = {
    1:  (26, 10, 1, 0),
    2:  (44, 16, 1, 0),
    3:  (70, 26, 1, 0),
    4:  (100, 18, 2, 0),
    5:  (134, 24, 2, 0),
    6:  (172, 16, 4, 0),
    7:  (196, 18, 4, 0),
    8:  (242, 22, 2, 2),
    9:  (292, 22, 3, 2),
    10: (346, 26, 4, 1),
}

_ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

# Version information is only in the code from version 7; below that there is
# none. Level M's format bits, indexed by mask pattern.
_FORMAT_M = [0x5412, 0x5125, 0x5E7C, 0x5B4B, 0x45F9, 0x40CE, 0x4F97, 0x4AA0]

_VERSION_BITS = {
    7: 0x07C94, 8: 0x085BC, 9: 0x09A99, 10: 0x0A4D3,
}


def _capacity(version: int) -> int:
    total, ec, g1, g2 = _VERSIONS[version]
    return total - ec * (g1 + g2)


def _pick_version(length: int) -> int:
    for version in sorted(_VERSIONS):
        count_bits = 8 if version < 10 else 16
        needed = 4 + count_bits + length * 8
        if _capacity(version) * 8 >= needed:
            return version
    raise ValueError("too long for this encoder (%d bytes)" % length)


def _encode_data(text: str, version: int) -> List[int]:
    data = text.encode("utf-8")
    count_bits = 8 if version < 10 else 16
    bits: List[int] = []

    def put(value: int, width: int) -> None:
        for i in range(width - 1, -1, -1):
            bits.append((value >> i) & 1)

    put(0b0100, 4)                       # byte mode
    put(len(data), count_bits)
    for byte in data:
        put(byte, 8)

    capacity = _capacity(version) * 8
    put(0, min(4, capacity - len(bits)))          # terminator
    while len(bits) % 8:
        bits.append(0)
    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8)]
    # The specification's padding: 0xEC and 0x11 alternating, starting with
    # 0xEC, until the version's data capacity is full.
    pad = (0xEC, 0x11)
    index = 0
    while len(codewords) < _capacity(version):
        codewords.append(pad[index % 2])
        index += 1
    return codewords


def _interleave(codewords: List[int], version: int) -> List[int]:
    total, ec_len, g1, g2 = _VERSIONS[version]
    blocks_total = g1 + g2
    data_len = _capacity(version)
    short = data_len // blocks_total
    blocks: List[List[int]] = []
    at = 0
    for index in range(blocks_total):
        size = short + (1 if index >= g1 else 0)
        blocks.append(codewords[at:at + size])
        at += size

    ec_blocks = [_remainder(block, ec_len) for block in blocks]

    out: List[int] = []
    for i in range(max(len(b) for b in blocks)):
        for block in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec_len):
        for block in ec_blocks:
            out.append(block[i])
    return out


# --- placing it in the grid --------------------------------------------------

def _new_matrix(size: int) -> List[List[Optional[int]]]:
    return [[None] * size for _ in range(size)]


def _place_finder(m: List[List[Optional[int]]], row: int, col: int) -> None:
    for r in range(-1, 8):
        for c in range(-1, 8):
            if not (0 <= row + r < len(m) and 0 <= col + c < len(m)):
                continue
            inside = (0 <= r < 7 and 0 <= c < 7)
            dark = inside and (r in (0, 6) or c in (0, 6)
                               or (2 <= r <= 4 and 2 <= c <= 4))
            m[row + r][col + c] = 1 if dark else 0


def _place_function_patterns(m: List[List[Optional[int]]], version: int) -> None:
    size = len(m)
    _place_finder(m, 0, 0)
    _place_finder(m, 0, size - 7)
    _place_finder(m, size - 7, 0)

    for i in range(8, size - 8):                 # timing
        bit = 1 if i % 2 == 0 else 0
        m[6][i] = bit
        m[i][6] = bit

    centres = _ALIGNMENT[version]
    for r in centres:
        for c in centres:
            if (r < 8 and c < 8) or (r < 8 and c > size - 9) or \
                    (r > size - 9 and c < 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = 1 if (abs(dr) == 2 or abs(dc) == 2
                                              or (dr == 0 and dc == 0)) else 0

    m[size - 8][8] = 1                           # the always-dark module


def _reserve_format(m: List[List[Optional[int]]], version: int) -> None:
    size = len(m)
    for i in range(9):
        if m[8][i] is None:
            m[8][i] = 0
        if m[i][8] is None:
            m[i][8] = 0
    for i in range(8):
        if m[8][size - 1 - i] is None:
            m[8][size - 1 - i] = 0
        if m[size - 1 - i][8] is None:
            m[size - 1 - i][8] = 0
    if version >= 7:
        for i in range(6):
            for j in range(3):
                m[size - 11 + j][i] = 0
                m[i][size - 11 + j] = 0


def _is_function(m: List[List[Optional[int]]], reserved, row: int, col: int) -> bool:
    return reserved[row][col]


def _place_data(m: List[List[Optional[int]]], reserved, data: List[int]) -> None:
    size = len(m)
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    at = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1                             # the timing column is skipped
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                m[row][c] = bits[at] if at < len(bits) else 0
                at += 1
        upward = not upward
        col -= 2


def _mask_bit(pattern: int, row: int, col: int) -> bool:
    if pattern == 0:
        return (row + col) % 2 == 0
    if pattern == 1:
        return row % 2 == 0
    if pattern == 2:
        return col % 3 == 0
    if pattern == 3:
        return (row + col) % 3 == 0
    if pattern == 4:
        return (row // 2 + col // 3) % 2 == 0
    if pattern == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if pattern == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _penalty(m: List[List[int]]) -> int:
    size = len(m)
    score = 0

    for line in list(m) + [list(col) for col in zip(*m)]:
        run, previous = 1, line[0]
        for value in line[1:]:
            if value == previous:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, previous = 1, value
        if run >= 5:
            score += 3 + (run - 5)

    for r in range(size - 1):
        for c in range(size - 1):
            block = {m[r][c], m[r][c + 1], m[r + 1][c], m[r + 1][c + 1]}
            if len(block) == 1:
                score += 3

    finder = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(size - 10):
            window = line[i:i + 11]
            if window == finder or window == finder[::-1]:
                score += 40

    # Rule 4: how far the proportion of dark modules strays from half.
    dark = sum(sum(row) for row in m)
    percent = dark * 100 / (size * size)
    score += 10 * (int(abs(percent - 50)) // 5)
    return score


def matrix(text: str) -> List[List[int]]:
    """The QR code for *text*, as rows of 0 and 1. 1 is a dark module."""
    version = _pick_version(len(text.encode("utf-8")))
    size = version * 4 + 17
    data = _interleave(_encode_data(text, version), version)

    base = _new_matrix(size)
    _place_function_patterns(base, version)
    _reserve_format(base, version)
    reserved = [[cell is not None for cell in row] for row in base]

    _place_data(base, reserved, data)

    best, best_score = None, None
    for pattern in range(8):
        candidate = [[cell if reserved[r][c] else cell ^ int(_mask_bit(pattern, r, c))
                      for c, cell in enumerate(row)]
                     for r, row in enumerate(base)]
        _write_format(candidate, pattern, version)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best, best_score = candidate, score
    return best


def _write_format(m: List[List[int]], pattern: int, version: int) -> None:
    size = len(m)
    bits = _FORMAT_M[pattern]
    for i in range(15):
        bit = (bits >> i) & 1
        if i < 6:
            m[i][8] = bit
        elif i == 6:
            m[7][8] = bit
        elif i == 7:
            m[8][8] = bit
        elif i == 8:
            m[8][7] = bit
        else:
            m[8][14 - i] = bit
        if i < 8:
            m[8][size - 1 - i] = bit
        else:
            m[size - 15 + i][8] = bit
    m[size - 8][8] = 1

    if version >= 7:
        value = _VERSION_BITS[version]
        for i in range(18):
            bit = (value >> i) & 1
            r, c = i // 3, i % 3
            m[size - 11 + c][r] = bit
            m[r][size - 11 + c] = bit


def svg(text: str, quiet: int = 4, scale: int = 4) -> str:
    """The QR code as an SVG element, ready to drop into a page.

    Inline, so it needs no `img-src` and no second request: the pages here are
    sent with `default-src 'none'`, and one fewer thing to be refused is one
    fewer thing to go silently wrong.
    """
    grid = matrix(text)
    size = len(grid) + quiet * 2
    box = size * scale
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{box}" height="{box}" '
        f'viewBox="0 0 {size} {size}" role="img" '
        f'aria-label="QR code for {_escape(text)}" shape-rendering="crispEdges">',
        f'<rect width="{size}" height="{size}" fill="#ffffff"/>',
    ]
    for r, row in enumerate(grid):
        run_start = None
        for c, cell in enumerate(row + [0]):
            if cell and run_start is None:
                run_start = c
            elif not cell and run_start is not None:
                parts.append(f'<rect x="{run_start + quiet}" y="{r + quiet}" '
                             f'width="{c - run_start}" height="1" fill="#000000"/>')
                run_start = None
    parts.append("</svg>")
    return "".join(parts)


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
