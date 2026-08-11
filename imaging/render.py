"""Slide rendering — a thin wrapper over the renderer that already exists.

`tools/render.py` was written and verified before this agent had any code, and
it already produces a real carousel (`python tools/render.py --demo`). This
module imports it rather than reimplementing it: two renderers would mean two
sets of canvas sizes and two ideas of what a slide looks like, and they would
diverge the first time one was touched.

Why a browser at all, rather than Pillow: the premium look of the site's hero
and CTA sections comes from specific CSS — the clipped-gradient headline, the
radial wash, the dot grid masked to fade, the mockup shadow, and real Google
Sans Flex kerning. `templates/brand.css` copies those tokens verbatim, so the
slides **inherit** the design system instead of imitating it. Redrawing that in
Pillow would mean maintaining a second, worse copy that drifts the moment the
site changes.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

log = logging.getLogger("content_poster.imaging")

AGENT_ROOT = Path(__file__).resolve().parent.parent
_RENDER_PY = AGENT_ROOT / "tools" / "render.py"

# Canvas per platform. Each gets its true aspect ratio rather than one square
# image cropped five ways.
PLATFORM_SIZE = {
    "instagram": "instagram_portrait",   # 4:5 outperforms 1:1 in feed
    "linkedin": "linkedin_carousel",
    "facebook": "facebook_link",
    "pinterest": "pinterest",
    "threads": "instagram_square",
    "devto": "facebook_link",
}


def _renderer():
    """Load tools/render.py as a module. `tools/` is a scripts dir, not a package."""
    spec = importlib.util.spec_from_file_location("cp_render", _RENDER_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load renderer from {_RENDER_PY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("cp_render", module)
    spec.loader.exec_module(module)
    return module


def render_slides(
    slides: list[dict],
    platform: str,
    prefix: str,
    *,
    strict: bool = True,
    audits: list[dict] | None = None,
) -> list[Path]:
    """Render slides for one platform. Returns the written PNG paths.

    Raises rather than returning an empty list: a publish step that silently
    posted a carousel with no images would be worse than a failed run, and the
    caller treats a raised error as "skip this platform, report it".

    `strict` defaults to True, which is the publishing behaviour: the DOM audit
    refusing a slide is a raised error, not a warning printed into a log nobody
    reads. `tools/showcase.py` passes False, because a review harness that
    refuses to write the picture of the problem cannot show you the problem.
    """
    if not slides:
        return []
    module = _renderer()
    size = PLATFORM_SIZE.get(platform, "instagram_portrait")
    paths = module.render(slides, size, prefix, strict=strict, audits=audits)
    if not paths:
        raise RuntimeError(f"renderer produced no images for {platform}")
    log.info("rendered %d slide(s) at %s for %s", len(paths), size, platform)
    return paths


def single_image(slide: dict, platform: str, prefix: str) -> Path:
    """One image — Facebook, Pinterest, a Threads attachment."""
    paths = render_slides([slide], platform, prefix)
    return paths[0]


def sizes() -> dict:
    return dict(_renderer().SIZES)
