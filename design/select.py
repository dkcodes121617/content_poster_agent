"""The v2 deck planner: what a post will look like, decided before it is written.

    plan = select.plan(platform="linkedin", pillar="teach", slides=8, history=rows)

The writer is told the shape - which format each slide is, in order - and only
fills in the words. Asking a model to choose the shape is what produced one
deck shape a day for a month under v1; choosing it here, against a ledger of
what this platform has already shown, is what makes variety a property of a
query instead of a hope.

## The axes, and why each one rotates separately

  recipe    the deck's argument: cheat code, myth buster, decision guide ...
  formats   each slide's structure, with alternatives inside a recipe
  layout    each format's composition
  look      the whole deck's visual identity (12)
  accent    colour family (5), pinned to a service line when there is one
  art       generative background (12 kinds x a seed), and where it sits

A feed where every post shares a look reads as a brand; one where every post
shares a look AND a structure reads as a template. So the look is held for a
whole deck (consistency inside a post) but changes between posts, while
formats and layouts change slide by slide.

## Rules, as filters that may all fail

  * never the same recipe twice in 14 days on one platform
  * never the same look twice in a row, and rarely within the last three
  * never the same opener layout twice in a row
  * no art kind repeated within the last two posts

Each rule narrows the pool and an empty pool falls back to the wider one:
refusing to post because every option was used recently would trade a real
post for a bookkeeping preference.

## Deterministic

Seeded by day, platform, pillar and slot. A retried run rebuilds the same deck,
which matters because the idempotency key says the post already happened.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import asdict, dataclass, field
from datetime import date

from campaign.calendar import today_ist
from design.registry import (
    FORMATS,
    LOOKS,
    PLATFORM_CANVAS,
    SERVICE_ACCENT,
    Choice,
    allowed_places,
)

log = logging.getLogger("content_poster.design.select")

ROTATION_DAYS = 14
MIN_SLIDES, MAX_SLIDES = 3, 10

# Platforms that carry no image at all (text-first), mirroring the write node.
TEXT_ONLY = frozenset({"threads", "x", "youtube", "devto"})


# ── recipes ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Recipe:
    name: str
    # The body, between the hook and the closer. Each entry is a tuple of
    # alternative formats; the first eligible one that is not over-used wins.
    body: tuple[tuple[str, ...], ...]
    pillars: tuple[str, ...]
    goal: str                       # saves | shares | comments | follows | clicks
    feels_like: str                 # one line the writer reads
    closer: tuple[str, ...] = ("cta",)
    cta: str = "save"               # cta layout: save | follow | comment
    # Formats added (in order) when more slides are asked for than the body has.
    stretch: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()     # stats | project


RECIPES: tuple[Recipe, ...] = (
    Recipe("cheat_code", (("cheat_sheet",), ("checklist", "flags"), ("steps", "framework")),
           ("teach",), "saves", "a reference worth saving: dense, specific, screenshot-able",
           closer=("recap", "cta"), cta="save", stretch=("myth_fact", "vs", "notes")),
    Recipe("myth_buster", (("myth_fact",), ("myth_fact",), ("hot_take", "post_card")),
           ("pov", "teach", "timely"), "comments", "three beliefs buyers hold, each corrected with evidence",
           cta="comment", stretch=("myth_fact", "checklist")),
    Recipe("decision_guide", (("decision_tree",), ("vs",), ("checklist",)),
           ("teach",), "saves", "helps a buyer make one decision with a clear rule",
           cta="save", stretch=("flags", "quadrant")),
    Recipe("framework_drop", (("framework",), ("steps",), ("checklist", "cheat_sheet")),
           ("teach", "pov"), "follows", "a named model the reader can reuse on their own project",
           closer=("recap", "cta"), cta="follow", stretch=("myth_fact", "flags")),
    Recipe("red_flags", (("flags",), ("checklist", "notes"), ("hot_take", "quote")),
           ("teach", "pov"), "shares", "the signs to look for, the kind people send to a co-founder",
           cta="save", stretch=("vs", "myth_fact")),
    Recipe("data_story", (("stat",), ("chart",), ("hot_take", "myth_fact")),
           ("proof", "timely", "teach"), "follows", "one number, its context, and what it means",
           cta="follow", stretch=("stat", "checklist"), needs=("stats",)),
    Recipe("build_log", (("chat",), ("steps",), ("terminal", "code")),
           ("process",), "follows", "how the work actually happens, shown rather than described",
           closer=("recap", "cta"), cta="follow", stretch=("notes", "timeline")),
    Recipe("proof_story", (("mockup",), ("stat",), ("quote", "timeline")),
           ("proof", "client_voice"), "follows", "one real project: the constraint, the build, the outcome",
           cta="follow", stretch=("steps", "post_card"), needs=("project",)),
    Recipe("iceberg_reveal", (("iceberg",), ("checklist",), ("hot_take", "framework")),
           ("teach", "process"), "saves", "what a buyer sees versus what the work actually takes",
           cta="save", stretch=("steps", "flags")),
    Recipe("tier_ranking", (("tier_list",), ("hot_take",), ("vs",)),
           ("pov",), "comments", "a ranking people will argue with in the comments",
           cta="comment", stretch=("myth_fact",)),
    Recipe("matrix_map", (("quadrant",), ("vs",), ("checklist",)),
           ("teach", "pov"), "comments", "places options on two axes so the trade-off is visible",
           cta="comment", stretch=("decision_tree",)),
    Recipe("founder_notes", (("notes",), ("chat",), ("hot_take", "post_card")),
           ("process", "pov"), "saves", "candid notes from building, the kind that read as human",
           closer=("recap", "cta"), cta="save", stretch=("checklist",)),
    Recipe("offer_plain", (("steps",), ("vs", "checklist"), ("quote", "stat")),
           ("direct_offer",), "clicks", "the free working prototype, stated plainly as a process",
           cta="follow", stretch=("flags",)),
    Recipe("timely_take", (("stat", "chart"), ("hot_take",), ("checklist",)),
           ("timely",), "comments", "what happened this week and what a founder should check",
           cta="comment", stretch=("myth_fact",)),
    # Plain and eligible everywhere: every rule above can exclude every other
    # recipe on some day, and this is what remains. A perfectly good deck.
    Recipe("straight_talk", (("hot_take",), ("steps",), ("checklist",)),
           ("proof", "teach", "pov", "process", "client_voice", "direct_offer", "timely"),
           "saves", "one clear argument, made in order", cta="save", stretch=("myth_fact", "flags")),
)
BY_NAME = {r.name: r for r in RECIPES}
FALLBACK = "straight_talk"

# Pillars the registry does not name, mapped to the ones its formats declare.
PILLAR_ALIASES = {"client_voice": ("proof", "pov"), "direct_offer": ("process", "proof")}

# What each pillar should FEEL like, matched against Look.moods.
PILLAR_MOODS = {
    "teach": ("clear", "calm", "technical", "friendly", "precise", "premium"),
    "pov": ("bold", "loud", "energetic", "editorial", "modern"),
    "proof": ("premium", "calm", "modern", "editorial"),
    "process": ("technical", "human", "playful", "precise", "hacker"),
    "client_voice": ("human", "editorial", "premium", "calm"),
    "direct_offer": ("premium", "bold", "modern"),
    "timely": ("energetic", "kinetic", "modern", "bold"),
}
# Audience taste per platform: B2B LinkedIn rewards clean and credible,
# Instagram rewards contrast and energy.
PLATFORM_MOODS = {
    "linkedin": ("premium", "clear", "editorial", "calm", "precise"),
    "instagram": ("bold", "energetic", "playful", "kinetic", "modern"),
    "pinterest": ("clear", "friendly", "calm", "premium"),
    "facebook": ("friendly", "clear", "bold"),
}

# Single-image posts: formats that carry a whole post on one canvas, by pillar.
SINGLE_BIAS = {
    "teach": ("cheat_sheet", "checklist", "flags", "vs", "decision_tree", "iceberg", "framework", "quadrant"),
    "pov": ("hot_take", "post_card", "myth_fact", "tier_list", "poll"),
    "proof": ("stat", "mockup", "quote", "chart"),
    "process": ("steps", "chat", "notes", "terminal"),
    "client_voice": ("quote", "post_card"),
    "direct_offer": ("steps", "checklist", "vs"),
    "timely": ("stat", "hot_take", "checklist", "chart"),
}


# ── the plan ─────────────────────────────────────────────────────────────────


@dataclass
class SlidePlan:
    format: str
    layout: str
    place: str


@dataclass
class DesignPlan:
    platform: str
    pillar: str
    recipe: str
    goal: str
    feels_like: str
    canvas: str
    look: str
    accent: str
    art: str
    seed: int
    slides: list[SlidePlan] = field(default_factory=list)

    @property
    def formats(self) -> list[str]:
        return [s.format for s in self.slides]

    def choices(self) -> list[Choice]:
        """One registry Choice per slide; the art seed shifts per slide so a
        deck's backgrounds rhyme without repeating."""
        return [Choice(format=s.format, layout=s.layout, look=self.look, accent=self.accent,
                       art=self.art, place=s.place, seed=self.seed + i * 97)
                for i, s in enumerate(self.slides)]

    def to_record(self) -> dict:
        d = asdict(self)
        d["slides"] = [asdict(s) for s in self.slides]
        return d

    def brief(self) -> str:
        shape = " -> ".join(f"{s.format}/{s.layout}" for s in self.slides)
        return f"{self.recipe} [{shape}] look={self.look}/{self.accent} art={self.art}"


def plan(
    *,
    platform: str,
    pillar: str,
    slides: int = 1,
    history: list[dict] | None = None,
    today: date | None = None,
    slot_key: str = "",
    has_stats: bool = False,
    has_project: bool = False,
    service_line: str = "",
    recipe: str = "",
    performance: dict | None = None,
) -> DesignPlan | None:
    """The design for one post, or None when the platform carries no image.

    `history` is recent visual_history rows for this platform, newest first
    (see recent()). `performance` is an optional {"format:<id>"|"look:<id>":
    weight} map - engagement feedback multiplies into the odds when it exists,
    and nothing depends on it existing.
    """
    if platform in TEXT_ONLY:
        return None
    rows = [r for r in (history or []) if isinstance(r, dict)]
    designs = [_design_of(r) for r in rows]
    designs = [d for d in designs if d]
    day = today or today_ist()
    rng = random.Random(f"{day.isoformat()}:{platform}:{pillar}:{slot_key}")
    canvas = PLATFORM_CANVAS.get(platform, "portrait")
    perf = performance or {}
    count = max(1, min(MAX_SLIDES, int(slides or 1)))

    if count == 1:
        chosen_recipe = None
        formats = [_single_format(pillar, canvas, designs, rng, has_stats, has_project, perf)]
        recipe_name, goal, feels = f"single:{formats[0]}", "saves", FORMATS[formats[0]].good_for
    else:
        count = max(MIN_SLIDES, count)
        chosen_recipe = _pick_recipe(pillar, rows, rng, has_stats, has_project, recipe)
        formats = _deck_formats(chosen_recipe, count, canvas, designs, rng, perf, pillar, has_stats, has_project)
        recipe_name, goal, feels = chosen_recipe.name, chosen_recipe.goal, chosen_recipe.feels_like

    look = _pick_look(pillar, platform, formats, designs, rng, perf)
    accent = _pick_accent(service_line)
    art = _pick_art(look, designs, rng)
    seed = int(hashlib.sha1(f"{day}:{platform}:{slot_key}:{look}".encode()).hexdigest()[:8], 16) % 900_000 + 1000
    plan_slides = _layouts_and_places(formats, look, art, designs, rng, chosen_recipe)

    return DesignPlan(platform=platform, pillar=pillar, recipe=recipe_name, goal=goal, feels_like=feels,
                      canvas=canvas, look=look, accent=accent, art=art, seed=seed, slides=plan_slides)


# ── pieces ───────────────────────────────────────────────────────────────────


def _design_of(row: dict) -> dict | None:
    d = row.get("design")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except ValueError:
            return None
    return d if isinstance(d, dict) else None


def _pillars_for(pillar: str) -> tuple[str, ...]:
    return (pillar, *PILLAR_ALIASES.get(pillar, ()))


def _eligible_format(fid: str, canvas: str, has_stats: bool, has_project: bool) -> bool:
    fmt = FORMATS.get(fid)
    if fmt is None:
        return False
    if canvas == "landscape" and not fmt.landscape_ok:
        return False
    if fid == "chart" and not has_stats:
        return False
    return has_project or not fmt.needs_svg


def _pick_recipe(pillar, rows, rng, has_stats, has_project, forced) -> Recipe:
    if forced and forced in BY_NAME:
        return BY_NAME[forced]
    pool = [r for r in RECIPES if pillar in r.pillars
            and ("stats" not in r.needs or has_stats) and ("project" not in r.needs or has_project)]
    pool = pool or [BY_NAME[FALLBACK]]
    used = [str(r.get("recipe") or "") for r in rows]
    fresh = [r for r in pool if r.name not in used]
    # Everything used this fortnight: choose between the two that ran longest
    # ago. (`used` is newest first, so a larger index is an older run.)
    pool = fresh or sorted(pool, key=lambda r: -used.index(r.name))[:2]
    # Keep the plain fallback for when nothing else is left.
    if len(pool) > 1:
        pool = [r for r in pool if r.name != FALLBACK] or pool
    return rng.choice(pool)


def _recent_formats(designs: list[dict], n: int = 6) -> list[str]:
    out: list[str] = []
    for d in designs[:n]:
        out += [s.get("format", "") for s in d.get("slides") or []]
    return out


def _weight(perf: dict, key: str) -> float:
    try:
        return max(0.2, min(3.0, float(perf.get(key, 1.0))))
    except (TypeError, ValueError):
        return 1.0


def _weighted(rng: random.Random, items: list, weights: list[float]):
    total = sum(weights)
    if total <= 0:
        return rng.choice(items)
    x = rng.random() * total
    for item, w in zip(items, weights, strict=False):
        x -= w
        if x <= 0:
            return item
    return items[-1]


# Formats a deck may borrow when it needs more slides than its recipe lists.
# Content formats only - never a second opener or closer.
_NOT_FILLER = frozenset({"hook", "cta", "recap", "poll", "post_card"})
# How often a format may appear in one deck. Some read as a series when
# repeated (three myths, two numbers); everything else is a set piece, and a
# second iceberg in one deck is filler. Only a true series may sit back to back.
REPEAT_LIMIT = {"myth_fact": 3, "stat": 2, "quote": 2, "hot_take": 2, "checklist": 2}
NUMBER_SLIDES = frozenset({"stat", "chart"})
SERIES = frozenset({"myth_fact"})


def _deck_formats(recipe: Recipe, count: int, canvas: str, designs: list[dict], rng, perf,
                  pillar: str = "", has_stats: bool = True, has_project: bool = True) -> list[str]:
    """hook, body..., climax, closer - exactly `count` slides where possible.

    The recipe's last body slide is its climax (the take, the verdict) and
    stays last however far the deck is stretched; extra slides go before it.
    A stretched deck borrows from the recipe's own list first, then from any
    content format that suits the pillar, and no format appears more than
    twice: a deck of four myth cards and three stats read as filler.
    """
    recent = _recent_formats(designs)
    ok_fmt = lambda f: _eligible_format(f, canvas, has_stats, has_project)  # noqa: E731
    body: list[str] = []
    for alternatives in recipe.body:
        ok = [f for f in alternatives if ok_fmt(f)]
        if ok:
            # The alternative seen least lately, weighted by performance.
            weights = [_weight(perf, f"format:{f}") / (1 + recent.count(f)) for f in ok]
            body.append(_weighted(rng, ok, weights))
    climax = body.pop() if len(body) >= 2 else None
    closer = [f for f in recipe.closer if ok_fmt(f)]
    room = count - 1 - len(closer) - (1 if climax else 0)
    if room < 1 and len(closer) > 1:
        # A very short deck drops the recap before it drops the ask.
        closer = closer[-1:]
        room = count - 1 - len(closer) - (1 if climax else 0)
    if room < 1 and climax and body:
        # Room for one content slide only: it is the recipe's core format,
        # not its closing take - a three-slide red-flags deck needs the flags.
        climax, body, room = body[0], [], 0
    used = [*body, *([climax] if climax else [])]
    wanted = set(_pillars_for(pillar)) if pillar else set()
    generic = [fid for fid, f in FORMATS.items()
               if fid not in _NOT_FILLER and f.family in ("both", "single") and ok_fmt(fid)
               and (not wanted or wanted & set(f.pillars))]
    rng.shuffle(generic)
    generic.sort(key=lambda f: recent.count(f))          # least seen lately first
    pool = [f for f in recipe.stretch if ok_fmt(f)] + [f for f in generic if f not in recipe.stretch]
    def fits(f: str) -> bool:
        if used.count(f) >= REPEAT_LIMIT.get(f, 1):
            return False
        # The facts hold a handful of figures; a third number slide sends the
        # writer looking for numbers that do not exist, and it invents them.
        if f in NUMBER_SLIDES and sum(x in NUMBER_SLIDES for x in used) >= 2:
            return False
        # never the same format twice running, unless it is a series
        return not body or body[-1] != f or f in SERIES

    for f in pool:
        if len(body) >= room:
            break
        if fits(f):
            body.append(f)
            used.append(f)
    # Trimming keeps the front of the body: the first content slide carries
    # the promise the hook made.
    seq = body[:max(room, 0)]
    if climax and seq and seq[-1] == climax and climax not in SERIES:
        # The climax would follow its own twin: move the twin somewhere it has
        # different neighbours on both sides.
        twin = seq.pop()
        for k in range(len(seq) + 1):
            left = seq[k - 1] if k > 0 else "hook"
            right = seq[k] if k < len(seq) else climax
            if twin not in (left, right):
                seq.insert(k, twin)
                break
    return ["hook", *seq, *([climax] if climax else []), *closer]


def _single_format(pillar, canvas, designs, rng, has_stats, has_project, perf) -> str:
    wanted = set(_pillars_for(pillar))
    pool = [fid for fid, f in FORMATS.items()
            if f.family in ("single", "both") and wanted & set(f.pillars)
            and _eligible_format(fid, canvas, has_stats, has_project)]
    pool = pool or ["hot_take"]
    bias = set(SINGLE_BIAS.get(pillar, ()))
    recent = _recent_formats(designs, 8)
    last = recent[0] if recent else ""
    candidates = [f for f in pool if f != last] or pool
    weights = [(2.2 if f in bias else 1.0) * _weight(perf, f"format:{f}") / (1 + 1.5 * recent.count(f))
               for f in candidates]
    return _weighted(rng, candidates, weights)


def _pick_look(pillar, platform, formats, designs, rng, perf) -> str:
    recent = [d.get("look", "") for d in designs]
    moods = set(PILLAR_MOODS.get(pillar, ()))
    taste = set(PLATFORM_MOODS.get(platform, ()))
    pool, weights = [], []
    for lid, look in LOOKS.items():
        if any(f in look.avoid for f in formats):
            continue
        if recent and lid == recent[0]:
            continue                                   # never twice in a row
        w = 1.0 + 1.0 * len(moods & set(look.moods)) + 0.5 * len(taste & set(look.moods))
        if lid in recent[:3]:
            w *= 0.25
        elif lid in recent[:7]:
            w *= 0.6
        w *= _weight(perf, f"look:{lid}")
        pool.append(lid)
        weights.append(w)
    if not pool:
        return rng.choice(list(LOOKS))
    return _weighted(rng, pool, weights)


def _pick_accent(service_line: str) -> str:
    """The website's colours, as the website uses them: brand blue, or the
    service's category colour when the post is about that service. Variety
    comes from looks, formats, layouts and art - never from new hues."""
    return SERVICE_ACCENT.get(service_line, "blue")


def _pick_art(look_id: str, designs: list[dict], rng) -> str:
    kinds = LOOKS[look_id].art
    if not kinds:
        return "none"
    recent = [d.get("art", "") for d in designs[:2]]
    pool = [k for k in kinds if k not in recent] or list(kinds)
    return rng.choice(pool)


# Layouts that are never chosen automatically. A donut says "parts of one
# whole", and the facts' figures are different kinds of count (projects,
# countries, testimonials): the first real donut sliced them into a pie. A
# ring needs a percentage, and the facts have none - choosing it asks the
# writer to find one, which is how numbers get invented.
NOT_AUTOMATIC = frozenset({("chart", "donut"), ("stat", "ring")})


def _layouts_and_places(formats, look, art, designs, rng, recipe) -> list[SlidePlan]:
    # The layout each format used most recently on this platform, to rotate off.
    last_layout: dict[str, str] = {}
    for d in designs:
        for s in d.get("slides") or []:
            last_layout.setdefault(s.get("format", ""), s.get("layout", ""))
    out: list[SlidePlan] = []
    in_deck: dict[str, list[str]] = {}
    for i, fid in enumerate(formats):
        fmt = FORMATS[fid]
        layouts = [lay for lay in fmt.layouts if (fid, lay) not in NOT_AUTOMATIC] or list(fmt.layouts)
        if fid == "cta" and recipe is not None and recipe.cta in layouts:
            layout = recipe.cta
        else:
            # Not the layout this format wore last time on this platform, and
            # not one it already wears in this deck.
            seen = in_deck.get(fid, [])
            fresh = [lay for lay in layouts if lay != last_layout.get(fid) and lay not in seen]
            fresh = fresh or [lay for lay in layouts if lay not in seen] or layouts
            layout = rng.choice(fresh)
        in_deck.setdefault(fid, []).append(layout)
        places = allowed_places(look, fid, art) if art != "none" else ("bg",)
        if fid == "hook" and layout == "split":
            place = "slot"
        elif i == 0 and "bg" in places:
            place = "bg"                               # the cover gets the full picture
        else:
            place = rng.choice(places)
        out.append(SlidePlan(fid, layout, place))
    return out


# ── the ledger ───────────────────────────────────────────────────────────────


def recent(config, platform: str, days: int = ROTATION_DAYS) -> list[dict]:
    """Recent decks on this platform, newest first. [] when unavailable."""
    from wizcore.db.conn import connect

    try:
        with connect(config.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT recipe, archetypes, layouts, theme, design, engine, posted_at "
                "FROM content.visual_history "
                "WHERE platform = %s AND posted_at > now() - make_interval(days => %s) "
                "ORDER BY posted_at DESC LIMIT 40",
                (platform, days),
            )
            return list(cur.fetchall())
    except Exception:
        log.warning("visual history unavailable; rotating from the seed alone", exc_info=True)
        return []


def record(config, design: DesignPlan, run_id: str = "") -> None:
    """Write the decision. Never raises: bookkeeping must not fail a publish."""
    from wizcore.db.conn import connect

    try:
        with connect(config.database_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO content.visual_history "
                "(platform, pillar, recipe, archetypes, layouts, theme, region, run_id, engine, design) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'v2',%s::jsonb)",
                (design.platform, design.pillar, design.recipe, design.formats,
                 [s.layout for s in design.slides], design.look, design.accent, run_id or None,
                 json.dumps(design.to_record())),
            )
    except Exception:
        log.warning("could not record visual history", exc_info=True)
