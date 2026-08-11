"""Render social slides from HTML/CSS to PNG via headless Chromium.

    python tools/render.py --demo          # a sample carousel to output/
    python tools/render.py --all           # every archetype, for eyeballing
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

## The audit

Every slide reports `window.__audit` before it is captured — what the type scale
had to shrink to, whether anything still overflows, whether the archetype drew
anything at all. Measuring in the DOM is exact where a pixel diff would be a
guess, and it costs nothing because the page is already open.

`strict=True` (the default for the agent) refuses to write a PNG the audit
called broken. That is the whole point: the three defects in CONTENT_SYSTEM.md
§1 all rendered *successfully*, and a human found them by looking.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

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


class RenderError(RuntimeError):
    """A slide rendered, and the audit says it is not publishable."""


def _payload(data: dict, index: str, w: int, h: int) -> dict:
    """Fill in what the template needs but the writer never supplies.

    `layout` and `family` come from the archetype registry rather than from the
    model. Letting the writer choose a layout would mean a JSON field that can
    be wrong in a way no validator upstream of the renderer would catch — and
    the registry already knows which layouts each archetype composes in.
    """
    from campaign import visual

    archetype = visual.resolve(data.get("role", ""))
    layout = data.get("layout")
    if archetype and layout not in archetype.layouts:
        layout = archetype.layouts[0]
    return {
        **data,
        "layout": layout or "centred",
        "family": archetype.family if archetype else "",
        "width": w,
        "height": h,
        "index": data.get("index", index),
    }


def render(
    slides: list[dict],
    size: str,
    prefix: str,
    *,
    strict: bool = True,
    audits: list[dict] | None = None,
) -> list[Path]:
    """Render slides to PNG. `audits`, if given, is filled with the DOM reports."""
    from playwright.sync_api import sync_playwright

    if size not in SIZES:
        sys.exit(f"unknown size {size!r}; known: {', '.join(SIZES)}")
    w, h = SIZES[size]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    template = TEMPLATE.read_text(encoding="utf-8")
    written: list[Path] = []
    problems: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # deviceScaleFactor 2 is the whole reason type looks sharp rather than
        # soft after the platform's own re-encode.
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
        try:
            for i, data in enumerate(slides, 1):
                payload = _payload(data, f"{i}/{len(slides)}", w, h)
                html = template.replace("__PAYLOAD__", json.dumps(payload))
                # A temp file beside the template so the relative ../assets font
                # paths and brand.css resolve exactly as they do in the browser.
                tmp = TEMPLATE.parent / f"._render_{i}.html"
                tmp.write_text(html, encoding="utf-8")
                try:
                    page.goto(tmp.as_uri())
                    # Wait on the ready flag, never a fixed sleep: the flag is
                    # set after fonts decode AND after fitting, so a screenshot
                    # can never catch unstyled or unfitted text.
                    page.wait_for_function("window.__ready === true", timeout=15000)
                    audit = page.evaluate("window.__audit") or {}
                    audit["slide"] = i
                    if audits is not None:
                        audits.append(audit)
                    for err in audit.get("errors") or []:
                        problems.append(f"slide {i} ({audit.get('role')}): {err}")

                    out = OUTPUT / f"{prefix}_{i:02d}.png"
                    page.screenshot(path=str(out))
                    written.append(out)
                    flag = "  ".join(
                        ["!" if audit.get("errors") else "", *(audit.get("warnings") or [])]
                    ).strip()
                    print(f"  {out.name}  {w}x{h} @2x  {flag}")
                finally:
                    tmp.unlink(missing_ok=True)
        finally:
            browser.close()

    if problems and strict:
        # The PNGs stay on disk deliberately. Being able to look at what the
        # audit objected to is the difference between fixing it in one pass and
        # guessing at a message.
        raise RenderError("; ".join(problems))
    for problem in problems:
        print(f"  WARN {problem}")
    return written


DEMO = [
    {"role": "cover_bold", "theme": "dark", "kicker": "Case study",
     "title": "Nine no-shows\na week, *gone*.",
     "body": "A dental clinic in Leeds was losing appointments to silence."},
    {"role": "statement", "layout": "top_anchored", "kicker": "The problem",
     "title": "The booking page worked.\n*Nobody used it.*",
     "body": "Six seconds to load on a phone. No reminder. No confirmation."},
    {"role": "metric_hero", "theme": "tinted", "kicker": "Result",
     "value": "<200ms", "label": "median response, CuePilot",
     "body": "Fast enough that the interface stops feeling like software."},
    {"role": "steps", "kicker": "How we work",
     "title": "The *free prototype*",
     "steps": [
         {"title": "You describe the problem", "detail": "One call, twenty minutes."},
         {"title": "We build something real", "detail": "Working, not a mockup."},
         {"title": "You decide", "detail": "Keep going, or walk away owing nothing."},
     ]},
    {"role": "cta_pill", "theme": "dark",
     "title": "See it before\nyou *pay for it*.",
     "body": "We build a working prototype first. No retainer, no discovery fee.",
     "pill": "wizcodes.site/get-started"},
]

# One slide per archetype, in registry order. This is what `--all` renders and
# what tests/test_render.py asserts against, so an archetype added to the
# registry with no sample here fails a test rather than shipping undrawn.
SAMPLES: dict[str, dict] = {
    "cover_bold": {"theme": "dark", "kicker": "Case study",
                   "title": "Nine no-shows\na week, *gone*."},
    "cover_question": {"theme": "dark", "kicker": "Buying software",
                       "title": "What does a\nwebsite *actually* cost?"},
    "cover_stat": {"theme": "dark", "kicker": "Reach", "value": "11",
                   "label": "countries with a live WizCodes build"},
    "cover_mockup": {"layout": "split_5050", "theme": "tinted", "kicker": "Work",
                     "title": "Shift planning\nfor *three clinics*.",
                     "svg": "__PLACEHOLDER__"},
    "metric_hero": {"theme": "tinted", "kicker": "Result", "value": "<200ms",
                    "label": "median response, CuePilot",
                    "body": "Fast enough that the interface stops feeling like software."},
    "stat_row": {"kicker": "So far", "title": "Where the work has *landed*",
                 "stats": [{"value": "26", "label": "projects shipped"},
                           {"value": "11", "label": "countries served"},
                           {"value": "5", "label": "open-source tools"}]},
    "bar_chart": {"kicker": "Load time", "title": "Where the *seconds* went",
                  "chart": {"unit": "s", "source": "Measured on a mid-range Android",
                            "series": [{"label": "Images", "value": 3.1},
                                       {"label": "Scripts", "value": 1.8},
                                       {"label": "Fonts", "value": 0.7}]}},
    "comparison_bar": {"kicker": "Discovery", "title": "Two ways to *start*",
                       "note": "Industry figures are typical agency practice, not ours.",
                       "chart": {"unit": " weeks",
                                 "series": [{"label": "Working prototype", "value": 1},
                                            {"label": "Paid discovery deck", "value": 4}]}},
    "donut": {"kicker": "Mobile", "title": "Most of your traffic is *already* on a phone",
              "chart": {"value": 78, "label": "of sessions on mobile"}},
    "statement": {"layout": "top_anchored", "kicker": "The problem",
                  "title": "The booking page worked.\n*Nobody used it.*",
                  "body": "Six seconds to load on a phone. No reminder. No confirmation."},
    "steps": {"kicker": "How we work", "title": "The *free prototype*",
              "steps": [{"title": "You describe the problem", "detail": "One call, twenty minutes."},
                        {"title": "We build something real", "detail": "Working, not a mockup."},
                        {"title": "You decide", "detail": "Keep going, or walk away owing nothing."}]},
    "checklist": {"kicker": "Before you sign", "title": "Four things to *ask for*",
                  "items": ["Who owns the code afterwards",
                            "What happens if the developer disappears",
                            "Whether the quote covers hosting",
                            "How changes are priced once it is live"]},
    "flow_diagram": {"kicker": "The route", "title": "How a brief becomes *software*",
                     "nodes": ["Brief", "Prototype", "Your call", "Build", "Handover"]},
    "before_after": {"kicker": "Rebuild",
                     "title": "Same content. *Different* result.",
                     "before": {"label": "Before", "text": "Six seconds to first paint on a phone."},
                     "after": {"label": "After", "text": "Under 200ms, on the same connection."}},
    "myth_fact": {"kicker": "Buying software",
                  "myth": "You need the full spec before anyone writes code.",
                  "fact": "You need *one working screen* you can argue with."},
    "mockup_browser": {"kicker": "Work", "title": "A booking desk that *answers*.",
                       "url": "wizcodes.site/work/cuepilot",
                       "svg": "__PLACEHOLDER__"},
    "mockup_phone": {"layout": "split_5050", "kicker": "Work",
                     "title": "Rotas in\n*a thumb tap*.",
                     "svg": "__PHONE__"},
    "graphic_embed": {"kicker": "From the blog", "title": "The four *guardrails*",
                      "caption": "The four guardrails we build before adding any clever behaviour",
                      "svg": "__PLACEHOLDER__"},
    "quote": {"kicker": "Client", "quote": "They shipped the thing they said they would.",
              "attribution": "Priya Raman, Northgate Dental"},
    "cta_pill": {"theme": "dark", "title": "See it before\nyou *pay for it*.",
                 "body": "We build a working prototype first. No retainer, no discovery fee.",
                 "pill": "wizcodes.site/get-started"},
    "cta_split": {"theme": "dark", "layout": "split_5050",
                  "title": "See it before\nyou *pay for it*.",
                  "pill": "wizcodes.site/get-started",
                  "note": "No retainer. No discovery fee."},
}


def sample_slides() -> list[dict]:
    """Every archetype as a renderable slide, in registry order.

    Imaged archetypes get the placeholder rather than real artwork: this list
    has to render identically on a machine with no site-repo token, because it
    is what the render tests assert against.
    """
    from campaign import visual
    from imaging import mockups

    out = []
    for a in visual.ARCHETYPES:
        if a.name not in SAMPLES:
            continue
        slide = {"role": a.name, **SAMPLES[a.name]}
        if slide.get("svg") == "__PLACEHOLDER__":
            slide["svg"] = mockups.by_kind("dashboard").svg
        elif slide.get("svg") == "__PHONE__":
            slide["svg"] = mockups.by_kind("mobile_list").svg
        out.append(slide)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--all", action="store_true", help="one slide per archetype")
    ap.add_argument("--sizes", action="store_true")
    ap.add_argument("--size", default="instagram_portrait")
    ap.add_argument("--lax", action="store_true", help="warn on audit errors instead of failing")
    args = ap.parse_args()

    if args.sizes:
        for k, (w, h) in SIZES.items():
            print(f"  {k:<20} {w}x{h}  -> {w*2}x{h*2} @2x")
        return 0

    slides, prefix = (
        (sample_slides(), "archetype") if args.all
        else (DEMO, "demo") if args.demo
        else ([], "")
    )
    if not slides:
        ap.print_help()
        return 0

    print(f"rendering {len(slides)} slide(s) at {args.size}:")
    audits: list[dict] = []
    try:
        render(slides, args.size, prefix, strict=not args.lax, audits=audits)
    except RenderError as e:
        print(f"\nAUDIT FAILED: {e}", file=sys.stderr)
        return 1
    bad = sum(1 for a in audits if a.get("errors"))
    shrunk = sum(1 for a in audits if (a.get("fit") or 1) < 1)
    print(f"\n-> {OUTPUT}\n   {len(audits)} slides, {bad} with errors, {shrunk} shrunk to fit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
