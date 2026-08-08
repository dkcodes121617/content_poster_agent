"""Fetch the site's real typefaces so social posts match the website.

The brand mark on every generated image is drawn by Pillow in the SAME face the
site sets in `wizcodes_next/src/app/layout.tsx` — Google Sans Flex for text,
Google Sans Code for the mono accent. A post rendered in a different family is
the exact failure the site's own font swap was made to fix: Poppins was called
out there as "the site's biggest brand liability", and re-introducing it on
every social image would undo that on the most-seen surface WizCodes has.

Google Fonts does not publish a plain `.ttf` link for these. It serves a "kit"
URL whose payload format is picked from the User-Agent, and Pillow's FreeType
can open exactly one of the three on offer:

    modern browser UA  -> woff2   (FreeType cannot read it)
    MSIE 6 UA          -> eot     (a TTF behind a 264-byte header)
    Android 4 UA       -> ttf     <- what we want

So the UA below is an old Android, verified to return `Content-Type: font/ttf`.
This is not a trick; UA-based format negotiation is how that endpoint is
designed to work. The magic-number check after download is what makes a future
change in their sniffing a loud failure here rather than a silent one inside a
scheduled run six weeks later.

    python tools/fetch_brand_fonts.py

Re-run only when the site changes typeface. The files are committed as build
assets so a scheduled run can never fail because Google Fonts was slow.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# Verified to return Content-Type: font/ttf from fonts.gstatic.com.
LEGACY_UA = (
    "Mozilla/5.0 (Linux; U; Android 4.0.3; en-us) "
    "AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30"
)

# The endpoint returns a STATIC instance per request, not the variable file —
# verified: Pillow's set_variation_by_name() raises on what comes back. So ask
# for each weight explicitly rather than expecting one file to cover the axis.
# SemiBold is the brand mark's weight (what Poppins-SemiBold was doing before);
# Regular covers any body text drawn onto an image later.
FAMILIES = {
    # family query                      -> output filename
    "Google+Sans+Flex:wght@600": "GoogleSansFlex-SemiBold.ttf",
    "Google+Sans+Flex:wght@400": "GoogleSansFlex-Regular.ttf",
    "Google+Sans+Code:wght@400": "GoogleSansCode-Regular.ttf",
}

# Magic numbers Pillow/FreeType can actually open.
TTF_MAGICS = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")


def fetch_css(family: str) -> str:
    url = f"https://fonts.googleapis.com/css2?family={family}"
    req = urllib.request.Request(url, headers={"User-Agent": LEGACY_UA})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def font_url(css: str) -> str | None:
    start = css.find("src: url(")
    if start == -1:
        return None
    start += len("src: url(")
    end = css.find(")", start)
    return css[start:end] if end != -1 else None


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    failures = 0

    for family, filename in FAMILIES.items():
        try:
            url = font_url(fetch_css(family))
            if not url:
                print(f"  FAIL {family}: no font URL in CSS")
                failures += 1
                continue

            req = urllib.request.Request(url, headers={"User-Agent": LEGACY_UA})
            data = urllib.request.urlopen(req, timeout=60).read()

            # Verify BEFORE writing. A woff2 saved as .ttf fails at render time,
            # inside a scheduled run, with a FreeType error nobody connects back
            # to this script.
            if not data.startswith(TTF_MAGICS):
                print(f"  FAIL {family}: got {data[:4]!r}, not TrueType "
                      f"(Google Fonts changed its UA sniffing?)")
                failures += 1
                continue

            out = ASSETS / filename
            out.write_bytes(data)
            print(f"  ok   {filename}  ({len(data):,} bytes)")
        except Exception as e:
            print(f"  FAIL {family}: {type(e).__name__}: {str(e)[:120]}")
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
