"""The design lab: render matrices that prove every format x layout x look works.

    modal run modal_app.py::lab_cli --round formats     (rendering happens on Modal)

Rounds:
  formats   every format and layout, in one dark and one light look
  looks     every look across a representative spread of formats
  hostile   every format with every field at its budget limit
  canvas    square, story, landscape and pin canvases
  all       everything above

Contact sheets put a red border on any slide whose audit found an error and an
amber one on warnings, so a few hundred renders can be reviewed by eye in
minutes - which is the review that caught every defect v1's tests missed.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from design.fixtures import GOOD, hostile
from design.registry import ACCENTS, FORMATS, LOOKS, Choice, allowed_places
from design.render import build_payload

AGENT_ROOT = Path(__file__).resolve().parent.parent
GRAPHICS = AGENT_ROOT.parent / "wizcodes_next" / "public" / "graphics"
CAROUSEL_ONLY = {f.id for f in FORMATS.values() if f.family == "slide"}
ART_PLACES = ("bg", "corner", "band")


def _svg_for(fmt: str, layout: str) -> str | None:
    if fmt != "mockup":
        return None
    name = "noorly-mobile-app.svg" if layout == "phone" else "ai-whatsapp-automation-ai-automation.svg"
    path = GRAPHICS / name
    return path.read_text(encoding="utf-8") if path.exists() else None


def _choice(fmt: str, layout: str, look: str, n: int) -> Choice:
    lk = LOOKS[look]
    art = lk.art[n % len(lk.art)] if lk.art else "none"
    places = allowed_places(look, fmt, art)
    place = places[n % len(places)]
    if fmt == "hook" and layout == "split":
        place = "slot"
    return Choice(format=fmt, layout=layout, look=look, accent=ACCENTS[n % len(ACCENTS)], art=art, place=place, seed=1000 + n * 37)


def _payload(fmt: str, layout: str, look: str, n: int, content: dict | None = None, canvas="portrait") -> tuple[str, dict]:
    choice = _choice(fmt, layout, look, n)
    slide = {"index": 1 if fmt == "hook" else (7 if fmt in ("cta", "recap") else 3), "count": 7} if fmt in CAROUSEL_ONLY else None
    payload = build_payload(choice, content if content is not None else GOOD[fmt], canvas=canvas, slide=slide,
                            svg=_svg_for(fmt, layout))
    label = f"{fmt}/{layout}/{look}/{choice.accent}/{choice.art}" + (f"/{canvas}" if canvas != "portrait" else "")
    return label, payload


def round_formats() -> list[tuple[str, dict]]:
    out, n = [], 0
    for fid, fmt in FORMATS.items():
        for layout in fmt.layouts:
            for look in ("midnight", "paper"):
                out.append(_payload(fid, layout, look, n))
                n += 1
    return out


def round_looks() -> list[tuple[str, dict]]:
    spread = [("hook", "stack"), ("cheat_sheet", "grid"), ("stat", "hero"), ("flags", "columns"),
              ("decision_tree", "td"), ("chart", "bar"), ("post_card", "card"), ("vs", "columns")]
    out, n = [], 0
    for look in LOOKS:
        for fid, layout in spread:
            out.append(_payload(fid, layout, look, n))
            n += 1
    return out


def round_hostile() -> list[tuple[str, dict]]:
    out, n = [], 0
    for fid, fmt in FORMATS.items():
        for look in ("paper", "midnight"):
            label, payload = _payload(fid, fmt.layouts[0], look, n, content=hostile(fid))
            out.append(("HOSTILE " + label, payload))
            n += 1
    return out


def round_canvas() -> list[tuple[str, dict]]:
    picks = [("hook", "stack"), ("stat", "hero"), ("checklist", "list"), ("hot_take", "big"), ("quote", "card"), ("chart", "bar"),
             ("mockup", "phone"), ("flags", "columns"), ("decision_tree", "td"), ("cheat_sheet", "grid")]
    out, n = [], 0
    for canvas in ("square", "story", "landscape", "pin"):
        for fid, layout in picks:
            if canvas == "landscape" and not FORMATS[fid].landscape_ok:
                continue
            out.append(_payload(fid, layout, ("midnight", "paper", "glass", "ink", "aurora", "grain", "noir", "swiss")[n % 8], n, canvas=canvas))
            n += 1
    return out


ROUNDS = {"formats": round_formats, "looks": round_looks, "hostile": round_hostile, "canvas": round_canvas}


def build_round(name: str) -> list[tuple[str, dict]]:
    if name == "all":
        return [item for fn in ROUNDS.values() for item in fn()]
    return ROUNDS[name]()


# ── run + sheets (executed on Modal) ──────────────────────────────────────────
def run_round(items: list[tuple[str, dict]], work: Path) -> bytes:
    """Render, build contact sheets and thumbnails, return a zip."""
    import zipfile

    from design.render import render

    labels = [lbl for lbl, _ in items]
    pngs, audits = render([p for _, p in items], work / "png", "lab", strict=False)
    for a, lbl in zip(audits, labels, strict=False):
        a["label"] = lbl
        a.pop("boxes", None)
    sheets = contact_sheets(list(zip(labels, pngs, audits, strict=False)), work / "sheets")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("audits.json", json.dumps(audits, indent=1, default=str))
        for s in sheets:
            z.write(s, f"sheets/{s.name}")
        for (_lbl, png, audit) in zip(labels, pngs, audits, strict=False):
            z.writestr(f"thumbs/{audit['index']:03d}.jpg", _thumb(png, 720))
    return buf.getvalue()


def _thumb(png: Path, width: int) -> bytes:
    from PIL import Image

    im = Image.open(png).convert("RGB")
    h = int(im.height * width / im.width)
    im = im.resize((width, h))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=86)
    return out.getvalue()


def contact_sheets(items, out_dir: Path, cols: int = 4, thumb_w: int = 400, per_sheet: int = 12) -> list[Path]:
    from PIL import Image, ImageDraw, ImageFont

    out_dir.mkdir(parents=True, exist_ok=True)
    font_path = AGENT_ROOT / "assets" / "GoogleSansCode-Regular.ttf"
    try:
        font = ImageFont.truetype(str(font_path), 15)
    except Exception:
        font = ImageFont.load_default()
    sheets = []
    for s in range(0, len(items), per_sheet):
        chunk = items[s:s + per_sheet]
        thumbs = []
        for lbl, png, audit in chunk:
            im = Image.open(png).convert("RGB")
            th = int(im.height * thumb_w / im.width)
            thumbs.append((lbl, im.resize((thumb_w, th)), audit))
        row_h = max(t[1].height for t in thumbs) + 64
        rows = (len(thumbs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (thumb_w + 24) + 24, rows * row_h + 24), (24, 26, 30))
        d = ImageDraw.Draw(sheet)
        for i, (lbl, th, audit) in enumerate(thumbs):
            x = 24 + (i % cols) * (thumb_w + 24)
            y = 24 + (i // cols) * row_h
            errs, warns = audit.get("errors") or [], audit.get("warnings") or []
            border = (230, 60, 60) if errs else ((235, 170, 40) if warns else (60, 190, 110))
            d.rectangle([x - 5, y - 5, x + thumb_w + 4, y + th.height + 4], fill=border)
            sheet.paste(th, (x, y))
            d.text((x, y + th.height + 8), f"#{audit.get('index', '?')} {lbl}"[:52], fill=(230, 230, 230), font=font)
            note = (errs[0] if errs else (warns[0] if warns else f"fit {audit.get('fit')} fill {audit.get('fill')}"))
            d.text((x, y + th.height + 28), str(note)[:52], fill=border, font=font)
        path = out_dir / f"sheet_{s // per_sheet + 1:02d}.jpg"
        sheet.save(path, "JPEG", quality=88)
        sheets.append(path)
    return sheets
