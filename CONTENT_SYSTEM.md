# Content system v2 — visuals, variety, geography, ramp

> Analysis and proposed architecture. **Nothing here is implemented.** It builds
> on CAMPAIGN.md (voice, pillars, calendar) and TRENDS.md (timeliness) rather
> than replacing either.
>
> Written after auditing the 24 images the showcase run actually produced, not
> from theory.

---

## 1. The image audit — what is actually broken

Three defects, in descending order of how bad they look in public.

### 1.1 Literal asterisks render on the largest text in the deck

`instagram_proof_03.png` shows a giant floating `*` and the headline number as
`<200ms*`. Both are raw markup that escaped onto the canvas.

**Root cause, exactly.** `templates/slide.html` has two text helpers: `esc()`
escapes HTML, `grad()` escapes *and* converts `*starred*` into the gradient
accent. Only five fields use `grad()` — cover title, statement title, steps
title, quote, cta title. Everything else uses `esc()`:

| Field | Helper | Result if the model writes `*x*` |
|---|---|---|
| `metric.value` | `esc` | **renders `*x*` literally** |
| `metric.label` | `esc` | renders literally |
| `*.body` | `esc` | renders literally |
| `steps[].title` / `.detail` | `esc` | renders literally |
| `quote.attribution` | `esc` | renders literally |

CAMPAIGN.md §10 tells the writer "mark a phrase with `*asterisks*`" as a global
rule. The template honours that in five places out of eleven. The model is
following instructions correctly; the renderer is inconsistent.

`metric.value` is the worst case because that element **already carries
`class="grad"`** — the whole number is gradient-filled by design. Asterisks
there can only ever be noise.

**Fix (three parts, because one is not enough):**

1. Route every authored text field through `grad()`, and strip asterisks
   entirely in fields that are already styled (`metric.value`).
2. A **pre-render validator** that rejects any slide whose text contains
   unpaired `*`, `**bold**`, backticks, `_underscore_`, or `[md](links)`. A
   template fix stops today's markup; the validator stops tomorrow's. Same
   reasoning as `no_write_endpoints.py` — the rule has to fail a build, not live
   in a prompt.
3. Cap `metric.value` length (≤ 10 characters) in that validator.

### 1.2 The metric value wraps and breaks

The `*` sat on its own line because `*<200ms*` was too wide for the canvas at
the metric font size, so it wrapped. Any long value — `£12,500/mo`,
`3.4x faster` — will do the same.

**Fix:** fit-to-width sizing (shrink the font until the value fits on one line)
plus the length cap above. A number that wraps is not a metric slide.

### 1.3 Every slide is vertically centred, so short slides look unfinished

On `instagram_proof_04.png` the content occupies roughly the middle 60% of a
4:5 canvas with large dead bands top and bottom. It is not *wrong*, but it is
the same shape on every slide of every deck, which is most of why the output
reads as templated.

**Fix:** layout variants per archetype (§3.2), chosen by content length rather
than fixed.

### 1.4 The `mockup` role exists but has never rendered

`slide.html` defines a `mockup` role expecting `D.image`. Nothing in the
pipeline ever supplies one, so the role is unreachable and every carousel is
text-only. This is the single biggest reason the decks feel flat.

---

## 2. The discovery that changes the visual answer

`wizcodes_next/public/graphics/` holds **95 brand-designed SVGs**, already
live on the site and already in the studio's visual language:

```
3d-model-viewer-web-platform.svg
ai-business-platform-web-platform.svg
ai-lead-agent-architecture-flow-17jpa.svg
add-ai-agent-to-your-product-four-guardrails-build-adding-hv535.svg
...
```

Two families: **per-project artwork** (`<slug>-<category>.svg`) and **blog
diagram artwork** (`<post-slug>-<concept>-<hash>.svg`).

This means the mockup and diagram archetypes need **no new design work and no
screenshots** — the assets exist, they are on-brand, they are public URLs, and
they are already grounded in real projects and real posts. Embedding them is a
fetch, not a design project.

It also means a "visual explainer" post can reuse the exact diagram from the
blog post it promotes, which ties the two pipelines together for free.

**Caveat to verify before building:** `projects.ts` carries no image field, so
project → graphic must be matched by slug convention. That mapping needs a
check, and a project with no matching graphic must degrade to a text archetype
rather than render a broken image.

---

## 3. The variety engine

The real problem is not "the templates are basic". It is that **there is one
deck shape**: cover → statement → metric → steps → statement → cta, centred,
same background, every time. Variety cannot come from the prompt, because the
prompt already asks for variety and this is what it produced.

Variety has to be **structural and enforced by a ledger**, the same way
repetition and idempotency already are.

### 3.1 Archetypes — from 7 roles to ~18

| Family | Archetypes |
|---|---|
| **Openers** | `cover_bold` · `cover_question` · `cover_stat` · `cover_mockup` |
| **Data** | `metric_hero` · `stat_row` (3 tiles) · `bar_chart` · `comparison_bar` · `donut` |
| **Explainers** | `steps` · `checklist` · `flow_diagram` · `before_after` · `myth_fact` |
| **Proof** | `mockup_browser` · `mockup_phone` · `graphic_embed` · `quote` |
| **Closers** | `cta_pill` · `cta_split` |

The site's own hero sections are the reference and they are full of reusable
motifs: the blue square grid, the phone frame with a chart inside, browser
chrome with a URL bar, floating status cards ("New lead — call booked Tue
10:00", "Task received / Report completed"), the pill row of services, the
3-up stat tiles (30 / 11 / 100%). Each of those is an archetype.

### 3.2 Layouts — the second axis

Independent of archetype: `centred` · `top_anchored` · `split_5050` ·
`full_bleed` · `offset_grid`. Archetype × layout × theme (dark/light/tinted)
gives far more surface variation than adding templates alone would.

### 3.3 Deck recipes — variety you can name

A recipe is an ordered archetype sequence with a personality:

| Recipe | Shape | Feels like |
|---|---|---|
| `data_story` | cover_stat → bar_chart → stat_row → statement → cta | analyst |
| `teardown` | cover_question → before_after → checklist → mockup → cta | consultant |
| `explainer` | cover_bold → flow_diagram → steps → statement → cta | teacher |
| `proof_narrative` | cover_mockup → statement → metric_hero → quote → cta | case study |
| `myth_buster` | cover_question → myth_fact ×3 → statement → cta | opinionated |
| `visual_first` | cover_mockup → graphic_embed ×3 → cta | portfolio |

The pillar picks a *set* of eligible recipes; the ledger picks which one.

### 3.4 The rotation ledger — the part that actually guarantees variety

`content.visual_history (platform, recipe, archetypes[], posted_at)`.

Rules, enforced in code:
- Never the same recipe twice within 14 days on one platform.
- Never the same *opener archetype* twice in a row.
- At least 3 distinct recipes per platform per fortnight.

This is the same discipline as the repetition gate, applied to design rather
than words. Without it, "use variety" is a hope; with it, it is a property.

### 3.5 Charts must be grounded like everything else

Charts render as **inline SVG in the template** — no chart library, no external
fetch, consistent with the no-dependency approach elsewhere.

The data behind any chart obeys the existing two-corpus rule: figures come from
the site facts snapshot (about us) or from captured trend sources (about the
world). **A chart is just a number with a bigger font — an invented chart is an
invented statistic, and the grounding gate must read chart data, not only prose.**
That is a real extension to the validator, not a formatting change.

---

## 4. US / UK / EU targeting

Currently everything is geography-blind. Four concrete changes:

**Trend queries become regional.** Google News RSS takes `gl` and `ceid`, so
one query set becomes three: `gl=US/ceid=US:en`, `gl=GB/ceid=GB:en`,
`gl=DE|NL|IE`. Tavily takes `include_domains`, so UK trends can be biased
toward UK outlets. Store `region` on `trend_items` and rotate which region
leads each day.

**Query vocabulary matters more than the geo parameter.** A US SMB owner
searches "cost to build an app", a UK one "app development agency near me", an
EU one is often GDPR-first. The query bank should be written per region, not
translated.

**Hashtags per region and platform.** `#SmallBusinessUK`, `#SMBTech`,
`#Mittelstand` are different audiences. A single global bank is why agency
accounts get no regional reach. Store as a per-region bank, rotated per pillar.

**Spelling and idiom.** en-GB for UK/IE/EU-facing posts ("optimise",
"personalise"), en-US for US. Cheap to do, and getting it wrong is a small
constant signal that the account is not local. Add a locale field to the slot
and one line to the prompt.

**Timing.** CAMPAIGN.md already notes 18:30 IST = 9am ET. Add an explicit
per-region window so a UK-targeted post lands in UK morning, not US morning.

---

## 5. The ramp — and one honest disagreement

The ask: when LinkedIn and Google Business Profile unlock, ramp volume hard to
"catch up and get in sync".

**I would push back on catching up by volume, and here is why it matters.** A
brand-new LinkedIn company page that starts posting 5×/day is indistinguishable
from spam to both the algorithm and a human visitor, and early-page reach
penalties are sticky. The same is true of a GBP listing posting several times a
day. What "catching up" actually buys is **consistency and archive depth**, and
those come from cadence over weeks, not from a burst.

So the recommendation is: ramp *fast but bounded*, and let the calendar become
capacity-driven rather than fixed.

**Replace the fixed 17-slot calendar with a target-per-day model.**
`content.posting_plan (platform, target_per_day, effective_from)` with safe
ceilings:

| Platform | Launch | Steady | Hard ceiling |
|---|---|---|---|
| LinkedIn | 1/day | 1–2/day | 2/day |
| Instagram | 3/week | 1/day | 1/day |
| Facebook | 3/week | 1/day | 1/day |
| Threads | 5/week | 2/day | 3/day |
| X | 3/week | 2/day | 3/day |
| GBP | — | 2/week | 1/day |
| Pinterest | 2/week | 1/day | 3/day |

When a platform flips on, it enters at **launch** rate and steps up weekly.
The scheduler fills from the plan, so enabling LinkedIn changes one row and the
system starts producing for it — no code change, no calendar rewrite.

**Backfill is a separate, deliberate mode.** For a newly-enabled platform, the
agent may re-publish the *best already-validated* posts from the last 30 days
(they were never seen on that platform) at up to launch rate. That is genuine
catch-up: an archive appears without a spam burst, and the content is already
proven. `content.social_posts` already stores captions, so this is a query, not
new generation.

---

## 6. Campaign phasing — awareness first

CAMPAIGN.md §9 describes an eight-week launch. **It is not implemented** — the
pillar mix is a static dict. Proposal: derive a phase from `CAMPAIGN_START_DATE`
and shift the mix.

| Phase | Weeks | Mix | Not yet |
|---|---|---|---|
| **Introduce** | 1–2 | proof 45 · process 30 · client_voice 15 · teach 10 | no offers, no POV, no timely |
| **Teach** | 3–4 | proof 30 · teach 30 · process 20 · client_voice 10 · pov 10 | no offers |
| **Opinion** | 5–6 | proof 25 · teach 25 · pov 20 · timely 15 · process 15 | first timely |
| **Full** | 7+ | the CAMPAIGN.md §4 mix, incl. direct_offer 3% | — |

The reasoning behind the order: a visitor who lands on a two-week-old profile
should see a body of real work, not opinions from an account with no evidence
behind them. POV lands *because* proof came first. And timely content is
deferred because reacting to news from an account nobody recognises has no
authority to trade on.

---

## 7. Claims policy — a hard validator, not a prompt note

You asked for no delivery timelines and no fixed prices, ever. That must be a
validator, because it is exactly the kind of thing a model will do helpfully and
unprompted ("get your prototype in 48 hours!").

**Reject** any output containing:
- delivery-time claims: `in N days/weeks`, `within N hours`, `same day`,
  `by Friday`, `24-hour turnaround`, `overnight`, `guaranteed delivery`
- fixed prices for us: currency + amount near words like *cost*, *price*,
  *from*, *starting at*, *quote*, *package*

**Allow** — because these are the useful half:
- how the *industry* prices: "most agencies bill discovery as a paid phase"
- comparative claims: "typical agency retainers run into five figures a month"
- process without duration: "a working prototype before any money changes hands"
- ranges attributed to a cited source (the trend-source corpus)

The nuance worth encoding: "free prototype" is a *pricing statement* about us
and must stay allowed, because it is true and it is the core offer. The rule is
about **numbers and durations**, not about mentioning the offer.

---

## 8. Things I would add that you did not ask for

1. **Automated image QA.** Eyeballing 24 images caught three bugs; it will not
   scale to hundreds. A pixel pass after render can check: no glyph within N px
   of an edge, no text region overflowing its container, contrast ≥ 4.5:1, and
   no more than X% of the canvas empty. Cheap, and it catches the class of
   defect §1 is full of.
2. **A visual regression baseline.** Render one deck per archetype on every
   template change and diff against a stored baseline. A CSS edit that breaks
   the metric slide should fail before it publishes, not after.
3. **Reuse blog diagram SVGs on social.** §2 — the strongest visual asset you
   own is already drawn, and it ties the blog and social pipelines together.
4. **Archetype performance tracking.** Store which recipe produced each post so
   that, once any engagement data exists, "which designs work" is answerable.
   Nothing ingests analytics today; storing the field now costs nothing and
   makes it possible later.
5. **Locale-aware CTA.** `/get-started` is right for everyone, but the phrasing
   before it should differ: US direct, UK understated. One line in the prompt.

---

## 9. Decisions — settled 8 Aug 2026

These are the contract. Changing one means changing this section first.

| Decision | Chosen |
|---|---|
| **Visual scope** | **Full 18-archetype system** (§3.1), all layouts, recipes and the rotation ledger |
| **Ramp** | **Bounded ramp + backfill** (§5) — launch rates stepping up weekly, plus republishing proven posts to newly-enabled platforms |
| **Chart data** | **Add a curated stats file to the site repo**, then chart from it — keeps the single-source-of-truth rule intact and improves the site |
| **Geography** | **Per-region rotation** (§4) — regional queries, hashtag banks, en-GB/en-US spelling, per-region posting windows |

---

## 10. Build order

Sequenced so each step is testable when built and nothing blocks on the step
after it. The showcase harness (`tools/showcase.py`) is the check at every
stage — it renders real images through the real pipeline, which is how §1's
bugs were found in the first place.

1. **Render correctness first.** The asterisk fix, the pre-render markup
   validator, fit-to-width metric sizing. Everything downstream renders through
   this, so a defect here multiplies across 18 archetypes.
2. **The claims validator** (§7). Small, independent, and currently a live
   exposure — a model will write "prototype in 48 hours" unprompted.
3. **Layout variants** (§3.2) — the second axis. Cheap once §1.3 is understood,
   and it changes how every existing archetype looks.
4. **Archetypes**, in dependency order: the data family needs the curated stats
   file; `graphic_embed` needs the slug→SVG mapping verified (§2 caveat);
   `mockup_*` needs neither and can go first.
5. **Recipes + rotation ledger** (§3.3, §3.4). Meaningless before there are
   enough archetypes to rotate between, essential the moment there are.
6. **Grounding for chart data** — extend the gate to read numeric series, not
   only prose. Must land with the data family, not after it.
7. **Geo rotation** (§4) — regional queries, hashtag banks, locale, windows.
8. **Campaign phasing** (§6) — derive the phase, shift the mix.
9. **Capacity-driven scheduling + backfill** (§5). Last, because it only pays
   off when LinkedIn/GBP actually unlock, and it is the piece most likely to
   need tuning against real behaviour.

Items 1–2 are the ones worth doing even if nothing else is: they fix defects
that are visible in public today.
