"""Deck recipes and the rotation ledger — CONTENT_SYSTEM.md §3.3 and §3.4.

A recipe is an ordered archetype sequence with a personality. The pillar decides
which recipes are *eligible*; the ledger decides which one is *used*.

## Why the ledger is the load-bearing half

The archetype registry makes variety possible. It does not make it happen. A
picker choosing freely from six eligible recipes lands on the same comfortable
one most weeks, for the same reason the prompt asking for variety produced one
deck shape — and after a fortnight the feed looks exactly as it did before,
except now there is a registry to point at.

So the rules below are enforced against `content.visual_history`, in code:

  * never the same recipe twice within 14 days on one platform
  * never the same opener archetype twice in a row
  * at least 3 distinct recipes per platform per fortnight

That is the repetition gate's discipline applied to design instead of words.
Without it "use variety" is a hope; with it, it is a property of a query.

## Degrading

Every function here works with no database. `pick()` falls back to a
deterministic seeded choice, which still rotates across days — worse than the
ledger, better than always picking the first. A publishing run must never fail
because the variety bookkeeping was unavailable.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from campaign import visual
from campaign.calendar import today_ist

log = logging.getLogger("content_poster.recipes")

ROTATION_WINDOW_DAYS = 14
MIN_DISTINCT_PER_FORTNIGHT = 3


@dataclass(frozen=True)
class Recipe:
    name: str
    shape: tuple[str, ...]
    feels_like: str
    # Pillars this recipe suits. A `data_story` for `client_voice` would be a
    # bar chart of someone's testimonial, which is not a thing.
    pillars: tuple[str, ...]
    # Needs the curated stats file to have numbers in it (§3.5). When the file
    # is empty or unreachable these are simply not eligible, rather than
    # producing a chart of invented figures.
    needs_stats: bool = False
    # Needs a real blog DIAGRAM from the site graphics manifest. Mockups are
    # generated (imaging/mockups.py) and always available, so only
    # `graphic_embed` can be blocked by missing artwork now.
    needs_art: bool = False


ALL_PILLARS = ("proof", "teach", "pov", "process", "client_voice", "direct_offer", "timely")

RECIPES: tuple[Recipe, ...] = (
    Recipe(
        "data_story",
        ("cover_stat", "bar_chart", "stat_row", "statement", "cta_pill"),
        "analyst",
        pillars=("teach", "pov", "timely", "proof"),
        needs_stats=True,
    ),
    Recipe(
        "teardown",
        ("cover_question", "before_after", "checklist", "mockup_browser", "cta_pill"),
        "consultant",
        pillars=("teach", "proof", "pov"),
    ),
    Recipe(
        "explainer",
        ("cover_bold", "flow_diagram", "steps", "statement", "cta_pill"),
        "teacher",
        pillars=("teach", "process", "pov", "timely"),
    ),
    Recipe(
        "proof_narrative",
        ("cover_mockup", "statement", "metric_hero", "quote", "cta_pill"),
        "case study",
        pillars=("proof", "client_voice"),
    ),
    Recipe(
        "myth_buster",
        ("cover_question", "myth_fact", "myth_fact", "statement", "cta_pill"),
        "opinionated",
        pillars=("pov", "teach", "timely"),
    ),
    Recipe(
        "visual_first",
        ("cover_bold", "graphic_embed", "graphic_embed", "statement", "cta_split"),
        "portfolio",
        pillars=("teach", "proof", "process"),
        needs_art=True,
    ),
    # Deliberately plain, and deliberately eligible everywhere. Every rule above
    # can exclude every other recipe on some particular day — a platform with a
    # busy fortnight and no stats file and no artwork has nothing left. This is
    # what it falls back to, and it is a perfectly good deck.
    Recipe(
        "straight_talk",
        ("cover_bold", "statement", "steps", "statement", "cta_pill"),
        "plainspoken",
        pillars=ALL_PILLARS,
    ),
    Recipe(
        "offer",
        ("cover_bold", "checklist", "metric_hero", "cta_split"),
        "direct",
        pillars=("direct_offer", "process"),
    ),
)

BY_NAME: dict[str, Recipe] = {r.name: r for r in RECIPES}
FALLBACK = "straight_talk"


def eligible(pillar: str, *, has_stats: bool = False, has_art: bool = False) -> list[Recipe]:
    """Recipes this pillar may use, given what the run can actually draw."""
    out = [
        r for r in RECIPES
        if pillar in r.pillars
        and (has_stats or not r.needs_stats)
        and (has_art or not r.needs_art)
    ]
    return out or [BY_NAME[FALLBACK]]


def fit_to_length(recipe: Recipe, slides: int) -> list[str]:
    """The recipe's shape, stretched or trimmed to `slides` entries.

    Trimming drops from the middle and never from the ends: the opener is the
    only slide most people see and the closer is the only one that asks for
    anything. Stretching repeats the middle, which is where a recipe's body
    archetypes live and where repetition reads as rhythm rather than as padding.
    """
    shape = list(recipe.shape)
    if slides <= 0 or slides == len(shape):
        return shape
    if slides < len(shape):
        keep = [shape[0], *shape[1:-1][: max(slides - 2, 0)], shape[-1]]
        return keep[:slides] if slides >= 2 else shape[:1]
    middle = shape[1:-1] or [shape[0]]
    out = [shape[0]]
    i = 0
    while len(out) < slides - 1:
        out.append(middle[i % len(middle)])
        i += 1
    out.append(shape[-1])
    return out


# ── the ledger ───────────────────────────────────────────────────────────────
def recent(config, platform: str, days: int = ROTATION_WINDOW_DAYS) -> list[dict]:
    """What this platform has looked like lately. `[]` when unavailable."""
    from wizcore.db.conn import connect

    try:
        with connect(config.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT recipe, archetypes, layouts, theme, posted_at "
                "FROM content.visual_history "
                "WHERE platform = %s AND posted_at > now() - make_interval(days => %s) "
                "ORDER BY posted_at DESC LIMIT 40",
                (platform, days),
            )
            return list(cur.fetchall())
    except Exception:
        log.warning("visual history unavailable; falling back to seeded rotation", exc_info=True)
        return []


def record(config, *, platform: str, pillar: str, recipe: str, archetypes: list[str],
           layouts: list[str], theme: str = "", region: str = "", run_id: str = "") -> None:
    """Write the decision. Never raises — bookkeeping must not fail a publish."""
    from wizcore.db.conn import connect

    try:
        with connect(config.database_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO content.visual_history "
                "(platform, pillar, recipe, archetypes, layouts, theme, region, run_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (platform, pillar, recipe, archetypes, layouts,
                 theme or None, region or None, run_id or None),
            )
    except Exception:
        log.warning("could not record visual history", exc_info=True)


def pick(
    config,
    *,
    platform: str,
    pillar: str,
    slides: int,
    has_stats: bool = False,
    has_art: bool = False,
    today: date | None = None,
    history: list[dict] | None = None,
) -> tuple[Recipe, list[str], list[str], str]:
    """`(recipe, archetypes, layouts, theme)` for one deck.

    The rules are applied as *filters that may all fail*, and that is
    deliberate. Refusing to publish because every recipe was used recently would
    trade a real post for a bookkeeping preference. So each rule narrows the
    pool, and an empty pool falls back to the previous, wider one.
    """
    pool = eligible(pillar, has_stats=has_stats, has_art=has_art)
    rows = recent(config, platform) if history is None else history

    used_recipes = [r["recipe"] for r in rows]
    fresh = [r for r in pool if r.name not in used_recipes]
    # If a fortnight has used everything, prefer whatever was used longest ago
    # rather than refusing. `used_recipes` is newest-first, so a recipe's index
    # in it is how recently it ran; absent means never.
    pool = fresh or sorted(pool, key=lambda r: -used_recipes.index(r.name))

    last_opener = ""
    for row in rows:
        arche = row.get("archetypes") or []
        if arche:
            last_opener = arche[0]
            break
    if last_opener:
        varied = [r for r in pool if r.shape[0] != last_opener]
        if varied:
            pool = varied

    distinct = len({*used_recipes})
    if distinct < MIN_DISTINCT_PER_FORTNIGHT and len(pool) > 1:
        # Under quota: bias hard away from anything seen at all this fortnight.
        unseen = [r for r in pool if r.name not in used_recipes]
        pool = unseen or pool

    # Seeded, not arbitrary. The same slot on the same day must resolve to the
    # same deck however many times a run is retried — a recipe re-rolled on a
    # retry would render a different carousel under an idempotency key that says
    # the post already happened.
    day = today or today_ist()
    rng = random.Random(f"{day.isoformat()}:{platform}:{pillar}")
    recipe = rng.choice(pool)

    archetypes = fit_to_length(recipe, slides)
    layouts = [_layout_for(name, rng) for name in archetypes]
    return recipe, archetypes, layouts, _theme_cycle(rng)


def _layout_for(role: str, rng: random.Random) -> str:
    """A layout the archetype actually composes in.

    Choosing from the registry rather than freely is what lets this be random
    and still always right — `full_bleed` is only ever offered to archetypes
    that carry artwork, and `split_5050` only to the two whose builders emit
    panes for the row to divide.
    """
    return rng.choice(list(visual.layouts_for(role)))


def _theme_cycle(rng: random.Random) -> str:
    """The deck's middle theme. Openers and closers are always dark.

    Weighted, not uniform: `light` is the reading surface and should dominate,
    `tinted` is a change of pace rather than an equal third.
    """
    return rng.choices(("light", "tinted"), weights=(0.68, 0.32))[0]


def apply_themes(archetypes: list[str], middle_theme: str) -> list[str]:
    """One theme per slide. Open dark, run light through the middle, close dark.

    That rhythm is what makes eight slides read as one piece rather than as
    eight images that happen to share a footer.
    """
    out: list[str] = []
    for i, role in enumerate(archetypes):
        arche = visual.resolve(role)
        family = arche.family if arche else ""
        first_or_last = i == 0 or i == len(archetypes) - 1
        theme = "dark" if (first_or_last or family in ("opener", "closer")) else middle_theme
        out.append(theme if arche is None or theme in arche.themes else arche.themes[0])
    return out


def summarise(rows: list[dict]) -> str:
    """One line for the digest: how varied the last fortnight actually was."""
    if not rows:
        return "no decks recorded"
    recipes = [r["recipe"] for r in rows]
    distinct = len(set(recipes))
    newest = rows[0].get("posted_at")
    when = newest.strftime("%d %b") if isinstance(newest, datetime) else "?"
    verdict = "ok" if distinct >= MIN_DISTINCT_PER_FORTNIGHT else "TOO SAME"
    return f"{len(rows)} decks, {distinct} distinct recipes ({verdict}), newest {when}"


def stale_before(days: int = ROTATION_WINDOW_DAYS) -> datetime:
    return datetime.now().astimezone() - timedelta(days=days)
