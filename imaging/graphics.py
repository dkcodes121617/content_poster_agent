"""Brand artwork, resolved out of the site repo.

CONTENT_SYSTEM.md §2: `wizcodes_next/public/graphics/` holds 95 brand-designed
SVGs that are already live on the site and already in the studio's visual
language. Two families — per-project artwork and blog diagrams. So the mockup
and explainer archetypes need no new design work and no screenshots. Embedding
one is a fetch, not a design project.

## The manifest removes the guesswork

The §2 caveat was that `projects.ts` carries no image field, so project → graphic
would have to be matched by slug convention and that mapping needed checking.
It turned out not to need a convention at all: `src/lib/graphics/manifest.json`
*is* the mapping, maintained by the site. Verified against the live repo:

    26 projects in projects.ts
    19 with a graphic in the manifest
     7 with none  ->  cover_mockup degrades to cover_bold, mockup_* to statement

Seven of twenty-six is ordinary, not exceptional, which is why the fallback is
part of the archetype registry rather than an error path.

## Why the SVG is inlined rather than linked

`<img src="https://wizcodes.site/graphics/x.svg">` would put a network fetch in
the middle of a render, on a schedule nobody watches, for no benefit. The
markup is read through the same `SiteReader` the facts snapshot already uses —
same token, same per-run cache — and pasted into the page. Nothing to be slow,
nothing to 404 at 3am.

The captions are the quiet win: a diagram's caption and alt text are written in
the repo, by us, about a real post. A `graphic_embed` slide is therefore grounded
by construction — the words on it came out of the corpus the gate checks against.
"""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass

from wizcore.facts.site import SiteReader

log = logging.getLogger("content_poster.imaging.graphics")

MANIFEST = "src/lib/graphics/manifest.json"
GRAPHICS_DIR = "public/graphics"

# Diagram types worth putting on a social slide. `StatGrid` and `Timeline` are
# excluded on purpose: both carry small type that survives a blog column and
# disappears at feed size, which is the whole reason a diagram gets reused
# rather than a screenshot.
SOCIAL_DIAGRAM_TYPES = frozenset(
    {"FlowDiagram", "CompareDiagram", "DecisionTree", "ConceptDiagram",
     "ArchitectureDiagram", "QuadrantMap", "BarChart"}
)

_MAX_SVG_BYTES = 400_000


@dataclass(frozen=True)
class Artwork:
    file: str
    svg: str
    alt: str = ""
    caption: str = ""
    kind: str = ""          # mockup | cover | diagram
    source_slug: str = ""   # the project or post it belongs to


class GraphicsLibrary:
    """Per-run artwork lookup. Shares the reader, so it shares the cache."""

    def __init__(self, reader: SiteReader):
        self._reader = reader
        self._manifest: dict | None = None

    # ── the index ────────────────────────────────────────────────────────────
    def manifest(self) -> dict:
        if self._manifest is None:
            raw = self._reader.read(MANIFEST)
            try:
                self._manifest = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                # A malformed manifest must not take down a publishing run. The
                # imaged archetypes degrade to text, which they are already
                # built to do for the seven projects that have no artwork.
                log.warning("graphics manifest is not valid JSON; artwork disabled")
                self._manifest = {}
        return self._manifest

    def has_project_art(self, slug: str) -> bool:
        return bool((self.manifest().get("projects") or {}).get(slug))

    def projects_with_art(self) -> list[str]:
        return sorted((self.manifest().get("projects") or {}).keys())

    # ── lookups ──────────────────────────────────────────────────────────────
    def for_project(self, slug: str) -> Artwork | None:
        """Per-project artwork, or None when that project has none."""
        file = (self.manifest().get("projects") or {}).get(slug)
        if not file:
            return None
        svg = self._svg(file)
        return Artwork(file=file, svg=svg, kind="project", source_slug=slug) if svg else None

    def for_post(self, slug: str) -> Artwork | None:
        """A blog post's cover illustration."""
        entry = (self.manifest().get("covers") or {}).get(slug)
        if not entry:
            return None
        file = entry.get("file") if isinstance(entry, dict) else entry
        svg = self._svg(file) if file else ""
        if not svg:
            return None
        alt = entry.get("alt", "") if isinstance(entry, dict) else ""
        return Artwork(file=file, svg=svg, alt=alt, kind="cover", source_slug=slug)

    def diagram(self, post_slug: str = "", rng: random.Random | None = None) -> Artwork | None:
        """A diagram drawn for the blog, whole, with the caption written for it.

        With no `post_slug`, picks any diagram of a social-friendly type. The
        picker is seeded by the caller so that "which diagram today" is stable
        within a run and varies across runs — the same discipline the calendar
        jitter uses, for the same reason.
        """
        charts = self.manifest().get("charts") or {}
        pool = [
            (file, meta) for file, meta in charts.items()
            if meta.get("type") in SOCIAL_DIAGRAM_TYPES
            and (not post_slug or meta.get("post") == post_slug)
        ]
        if not pool:
            return None
        picker = rng or random
        for file, meta in picker.sample(pool, k=len(pool)):
            svg = self._svg(file)
            if svg:
                return Artwork(
                    file=file, svg=svg,
                    alt=meta.get("alt", ""), caption=meta.get("caption", ""),
                    kind="diagram", source_slug=meta.get("post", ""),
                )
        return None

    # ── reading ──────────────────────────────────────────────────────────────
    def _svg(self, file: str) -> str:
        if not file or not file.endswith(".svg") or "/" in file or ".." in file:
            log.warning("refusing to read suspicious graphics path %r", file)
            return ""
        markup = self._reader.read(f"{GRAPHICS_DIR}/{file}")
        if not markup:
            log.warning("graphic listed in the manifest but missing from the repo: %s", file)
            return ""
        if len(markup) > _MAX_SVG_BYTES:
            # Chromium will render it; the page just takes a long time and the
            # payload has to be JSON-encoded into the HTML first. Nothing in the
            # library is close to this, so hitting it means something changed.
            log.warning("graphic %s is %d bytes - skipping", file, len(markup))
            return ""
        return _fit_svg(markup)


_SIZE_ATTR = re.compile(r'\s(?:width|height)\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', re.I)


def _fit_svg(markup: str) -> str:
    """Strip fixed width/height from the root so CSS can size it.

    An SVG authored for a blog column carries `width="720"`, and inside a slide
    that renders at 720 canvas pixels regardless of the box it was put in — the
    artwork either overflows the frame or floats in the middle of it. Removing
    the attributes hands sizing to the stylesheet, where the rest of the layout
    already lives. The `viewBox` is what actually preserves the aspect ratio and
    is deliberately untouched.
    """
    match = re.search(r"<svg\b[^>]*>", markup, re.I)
    if not match:
        return markup
    tag = match.group(0)
    if "viewbox" not in tag.lower():
        # With no viewBox, stripping the dimensions would collapse it to nothing.
        return markup
    return markup[: match.start()] + _SIZE_ATTR.sub("", tag) + markup[match.end():]


# A stand-in used only by the render tests and `tools/render.py --all`, so the
# imaged archetypes can be exercised without the site repo. Never published:
# the publishing path resolves real artwork or falls back to a text archetype.
PLACEHOLDER_SVG = (
    '<svg viewBox="0 0 640 400" xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="pg" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0%" stop-color="#8ECAE6"/><stop offset="100%" stop-color="#219EBC"/>'
    "</linearGradient></defs>"
    '<rect width="640" height="400" fill="#EEF3F7"/>'
    '<rect x="40" y="40" width="360" height="26" rx="13" fill="url(#pg)"/>'
    '<rect x="40" y="92" width="560" height="14" rx="7" fill="#CBD9E4"/>'
    '<rect x="40" y="120" width="470" height="14" rx="7" fill="#CBD9E4"/>'
    '<rect x="40" y="176" width="250" height="180" rx="16" fill="#FFFFFF"/>'
    '<rect x="310" y="176" width="290" height="180" rx="16" fill="#FFFFFF"/>'
    '<circle cx="120" cy="250" r="42" fill="url(#pg)" opacity="0.35"/>'
    '<rect x="340" y="212" width="200" height="12" rx="6" fill="#DCE6EE"/>'
    '<rect x="340" y="240" width="160" height="12" rx="6" fill="#DCE6EE"/>'
    '<rect x="340" y="268" width="180" height="12" rx="6" fill="#DCE6EE"/>'
    "</svg>"
)
