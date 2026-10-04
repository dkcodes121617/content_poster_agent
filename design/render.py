"""Render design-engine slides to PNG through headless Chromium.

Same discipline as tools/render.py (v1), which this sits beside rather than
replaces: one browser, the page reports `window.__audit` before capture, and
`strict` refuses to call a slide publishable when the audit found a defect.

What v2 adds:
  * only the engines a slide needs are loaded (Mermaid is 5 MB)
  * icons travel in the payload, resolved from the bundled Lucide sprite
  * a PIXEL contrast check after capture - text colour against the colour
    actually rendered behind it (art, gradients, glass), not the declared
    token, because the declared token is exactly what lies when art sits
    under the type
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from design.registry import BASE_ICONS, CANVAS, ENGINE_SCRIPTS, Choice, engines_for

AGENT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = AGENT_ROOT / "templates" / "v2"
SPRITE = TEMPLATE_DIR / "icons" / "lucide-sprite.svg"


class RenderError(RuntimeError):
    """A slide rendered and the audit says it is not publishable."""


# ── icons ─────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _sprite() -> dict[str, str]:
    text = SPRITE.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r'<symbol id="([^"]+)" viewBox="([^"]+)">(.*?)</symbol>', text, re.S):
        out[m.group(1)] = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{m.group(2)}" fill="none" stroke="currentColor" '
            f'stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">{m.group(3).strip()}</svg>'
        )
    return out


def icon_names() -> list[str]:
    return sorted(_sprite())


def _icons_for(content) -> dict[str, str]:
    wanted = set(BASE_ICONS)

    def walk(v):
        if isinstance(v, dict):
            for k, val in v.items():
                if k == "icon" and isinstance(val, str):
                    wanted.add(val)
                else:
                    walk(val)
        elif isinstance(v, list):
            for i in v:
                walk(i)

    walk(content)
    sprite = _sprite()
    return {n: sprite[n] for n in wanted if n in sprite}


# ── payload ───────────────────────────────────────────────────────────────────
def build_payload(choice: Choice, content: dict, *, canvas="portrait", slide: dict | None = None,
                  series: str | None = None, svg: str | None = None, brand: dict | None = None) -> dict:
    w, h = CANVAS[canvas] if isinstance(canvas, str) else canvas
    return {
        "canvas": {"w": w, "h": h},
        "format": choice.format, "layout": choice.layout, "look": choice.look, "accent": choice.accent,
        "art": {"kind": choice.art, "seed": choice.seed, "place": choice.place},
        "slide": slide, "series": {"label": series} if series else None,
        "brand": brand or {"handle": "@wiz_codes", "site": "wizcodes.site"},
        "content": content, "icons": _icons_for(content), "svg": svg,
    }


def _html(payload: dict) -> str:
    template = (TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    scripts = "\n  ".join(f'<script src="{src}"></script>'
                          for eng in engines_for(payload["format"], payload["look"]) for src in ENGINE_SCRIPTS[eng])
    # "</" inside a JSON string would close the <script> it is embedded in.
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("__ENGINES__", scripts).replace("__PAYLOAD__", data)


# ── render ────────────────────────────────────────────────────────────────────
def render(payloads: list[dict], out_dir: Path, prefix: str, *, strict: bool = True, dsf: int = 2,
           timeout_ms: int = 60000, contrast: bool = True) -> tuple[list[Path], list[dict]]:
    """Render every payload. Returns (png paths, audits) in input order."""
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    audits: list[dict] = []
    problems: list[str] = []
    tag = f"{os.getpid()}_{abs(hash(prefix)) % 10**6}"

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--font-render-hinting=none", "--disable-lcd-text"])
        try:
            page = None
            current = None
            for i, payload in enumerate(payloads, 1):
                size = (payload["canvas"]["w"], payload["canvas"]["h"])
                if page is None or size != current:
                    if page is not None:
                        page.close()
                    page = browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=dsf)
                    current = size
                tmp = TEMPLATE_DIR / f"._r_{tag}_{i}.html"
                tmp.write_text(_html(payload), encoding="utf-8")
                out = out_dir / f"{prefix}_{i:02d}.png"
                try:
                    page.goto(tmp.as_uri())
                    page.wait_for_function("window.__ready === true", timeout=timeout_ms)
                    audit = page.evaluate("window.__audit") or {}
                    page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": size[0], "height": size[1]})
                except Exception as e:  # a timeout or a crashed page is a failed slide, not a crashed run
                    audit = {"errors": [f"render failed: {str(e)[:200]}"], "warnings": [], "boxes": []}
                    if not out.exists():
                        page.screenshot(path=str(out))
                finally:
                    tmp.unlink(missing_ok=True)
                if contrast and out.exists():
                    audit.setdefault("errors", []).extend(contrast_problems(out, audit.get("boxes") or [], dsf))
                audit["index"] = i
                audit["png"] = str(out)
                audits.append(audit)
                written.append(out)
                for err in audit.get("errors") or []:
                    problems.append(f"{prefix} #{i} ({payload['format']}/{payload['layout']}/{payload['look']}): {err}")
        finally:
            browser.close()

    if problems and strict:
        raise RenderError("; ".join(problems[:20]))
    return written, audits


# ── documents ─────────────────────────────────────────────────────────────────
def to_pdf(pngs: list[Path], out: Path, size: tuple[int, int] = (1080, 1350)) -> Path:
    """One page per rendered slide - the form LinkedIn takes a carousel in.

    Built from the finished PNGs rather than by printing the slides' HTML:
    print mode rasterises backdrop blur, masks and filters its own way, and a
    document that differs from the images it was checked as is a document
    nobody checked. Chromium embeds the PNGs losslessly.
    """
    from playwright.sync_api import sync_playwright

    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    pages = "".join(f'<img src="{Path(p).resolve().as_uri()}">' for p in pngs)
    doc = (f"<!doctype html><html><head><meta charset='utf-8'><style>@page {{ size: {w}px {h}px; margin: 0 }}"
           f"html, body {{ margin: 0; padding: 0; background: #000 }}"
           f"img {{ display: block; width: {w}px; height: {h}px; page-break-after: always; break-after: page }}"
           f"img:last-child {{ page-break-after: auto; break-after: auto }}</style></head><body>{pages}</body></html>")
    tmp = out.parent / f"._doc_{os.getpid()}.html"
    tmp.write_text(doc, encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": w, "height": h})
                page.goto(tmp.as_uri())
                page.wait_for_function("[...document.images].every((i) => i.complete && i.naturalWidth > 0)", timeout=30000)
                page.pdf(path=str(out), width=f"{w}px", height=f"{h}px", print_background=True,
                         margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
            finally:
                browser.close()
    finally:
        tmp.unlink(missing_ok=True)
    return out


# ── contrast, measured on pixels ──────────────────────────────────────────────
_RGB = re.compile(r"rgba?\(([^)]+)\)")


def _parse(color: str):
    m = _RGB.search(color or "")
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).replace("/", ",").split(",")]
    try:
        r, g, b = (float(parts[0]), float(parts[1]), float(parts[2]))
        a = float(parts[3]) if len(parts) > 3 else 1.0
    except (ValueError, IndexError):
        return None
    return (r, g, b, a)


def _lum(rgb) -> float:
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def ratio(a, b) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def contrast_problems(png: Path, boxes: list[dict], dsf: int = 2) -> list[str]:
    """Text whose rendered background leaves it below WCAG contrast.

    The background is the most common colour in the text's box once colours
    near the text colour are excluded - glyph pixels are the minority of any
    text box, so the mode is what the text actually sits on.
    """
    from PIL import Image

    try:
        img = Image.open(png).convert("RGB")
    except Exception:
        return []
    out = []
    W, H = img.size
    for b in boxes:
        if b.get("clip") or b.get("h", 0) < 8 or b.get("w", 0) < 8:
            continue
        col = _parse(b.get("color", ""))
        if not col or col[3] < 0.35:
            continue
        x0, y0 = max(0, int(b["x"] * dsf)), max(0, int(b["y"] * dsf))
        x1, y1 = min(W, int((b["x"] + b["w"]) * dsf)), min(H, int((b["y"] + b["h"]) * dsf))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        region = img.crop((x0, y0, x1, y1)).resize((max(1, (x1 - x0) // 3), max(1, (y1 - y0) // 3)))
        counts = Counter()
        for px in region.getdata():
            if abs(px[0] - col[0]) + abs(px[1] - col[1]) + abs(px[2] - col[2]) < 90:
                continue
            counts[(px[0] // 8 * 8, px[1] // 8 * 8, px[2] // 8 * 8)] += 1
        if not counts:
            continue
        bg = counts.most_common(1)[0][0]
        text_rgb = col[:3]
        if col[3] < 1:
            text_rgb = tuple(col[i] * col[3] + bg[i] * (1 - col[3]) for i in range(3))
        r = ratio(text_rgb, bg)
        size, weight = float(b.get("size", 16)), int(b.get("weight", 400))
        large = size >= 34 or (size >= 26 and weight >= 600)
        need = 3.0 if large else 4.5
        if r < need - 0.05:
            out.append(f'low contrast {r:.1f}:1 (needs {need:.1f}) on "{b.get("text", "")[:30]}"')
    return out[:6]
