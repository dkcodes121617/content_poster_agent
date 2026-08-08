"""Render social slides from HTML/CSS to PNG via headless Chromium.

    python tools/render.py --demo          # render a sample carousel to output/
    python tools/render.py --sizes         # list the platform canvases

Why a browser and not Pillow or SVG:

The slides have to look like the site — clipped-gradient headlines, the radial
wash, the masked dot grid, the mockup shadow, real Google Sans Flex with proper
kerning. All of that is CSS the site already ships. Re-implementing it in
Pillow draw calls means maintaining a second, worse copy of the design system
that drifts the first time the site changes. Rendering the actual CSS means the
slides inherit the design instead of imitating it.

Chromium costs ~400 MB in the Modal image and a slower cold start. For an agent
that renders a few dozen slides a week, that is the cheapest part of the budget.

Everything is local: fonts load from ../assets as files, so a scheduled post can
never fail because Google Fonts was slow.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = AGENT_ROOT / "templates" / "slide.html"
OUTPUT = AGENT_ROOT / "output"

# Canvas per platform, at true pixel size. Captured at deviceScaleFactor 2, so
# a 1080x1350 slide leaves as 2160x2700 — which is what keeps type crisp when
# the platform re-compresses it.
SIZES: dict[str, tuple[int, int]] = {
    "instagram_portrait": (1080, 1350),   # 4:5  — the carousel default
    "instagram_square":   (1080, 1080),   # 1:1
    "instagram_story":    (1080, 1920),   # 9:16 — stories / reels cover
    "linkedin_carousel":  (1080, 1350),   # 4:5  — outperforms 1:1 in-feed
    "facebook_link":      (1200, 630),    # 1.91:1
    "x_post":             (1600, 900),    # 16:9
    "pinterest":          (1000, 1500),   # 2:3
}


def render(slides: list[dict], size: str, prefix: str) -> list[Path]:
    from playwright.sync_api import sync_playwright

    if size not in SIZES:
        sys.exit(f"unknown size {size!r}; known: {', '.join(SIZES)}")
    w, h = SIZES[size]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    template = TEMPLATE.read_text(encoding="utf-8")
    written: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # deviceScaleFactor 2 is the whole reason type looks sharp rather than
        # soft after the platform's own re-encode.
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
        try:
            for i, data in enumerate(slides, 1):
                payload = {**data, "width": w, "height": h,
                           "index": data.get("index", f"{i}/{len(slides)}")}
                html = template.replace("__PAYLOAD__", json.dumps(payload))
                # A temp file beside the template so the relative ../assets font
                # paths and brand.css resolve exactly as they do in the browser.
                tmp = TEMPLATE.parent / f"._render_{i}.html"
                tmp.write_text(html, encoding="utf-8")
                try:
                    page.goto(tmp.as_uri())
                    # Wait on the font-ready flag, never a fixed sleep: a slow
                    # decode would otherwise be captured as unstyled text.
                    page.wait_for_function("window.__ready === true", timeout=15000)
                    out = OUTPUT / f"{prefix}_{i:02d}.png"
                    page.screenshot(path=str(out))
                    written.append(out)
                    print(f"  {out.name}  {w}x{h} @2x")
                finally:
                    tmp.unlink(missing_ok=True)
        finally:
            browser.close()
    return written


DEMO = [
    {"role": "cover", "theme": "dark", "kicker": "Case study",
     "title": "Nine no-shows\na week, *gone*.",
     "body": "A dental clinic in Leeds was losing appointments to silence."},
    {"role": "statement", "kicker": "The problem",
     "title": "The booking page worked.\n*Nobody used it.*",
     "body": "Six seconds to load on a phone. No reminder. No confirmation."},
    {"role": "metric", "kicker": "Result",
     "value": "<200ms", "label": "median response, CuePilot",
     "body": "Fast enough that the interface stops feeling like software."},
    {"role": "steps", "kicker": "How we work",
     "title": "The *free prototype*",
     "steps": [
         {"title": "You describe the problem", "detail": "One call, twenty minutes."},
         {"title": "We build something real", "detail": "Working, not a mockup."},
         {"title": "You decide", "detail": "Keep going, or walk away owing nothing."},
     ]},
    {"role": "cta", "theme": "dark",
     "title": "See it before\nyou *pay for it*.",
     "body": "We build a working prototype first. No retainer, no discovery fee.",
     "pill": "wizcodes.site/get-started"},
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--sizes", action="store_true")
    ap.add_argument("--size", default="instagram_portrait")
    args = ap.parse_args()

    if args.sizes:
        for k, (w, h) in SIZES.items():
            print(f"  {k:<20} {w}x{h}  -> {w*2}x{h*2} @2x")
        return 0

    if args.demo:
        print(f"rendering {len(DEMO)} slides at {args.size}:")
        render(DEMO, args.size, "demo")
        print(f"\n-> {OUTPUT}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
