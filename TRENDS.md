# Timely content — the trend intelligence layer

> Design for giving the agents awareness of the outside world, so they can post
> about what is happening now instead of only about what WizCodes has already
> built. Written as a proposal: nothing here is implemented yet.
>
> It supersedes nothing. CAMPAIGN.md still governs voice, pillars and the
> validator stack; this adds a source of *subjects* and one new pillar.

---

## 1. Verdict on the proposal

The instinct is right and the pipeline shape is right. Two parts I would change,
and one problem that will stop the whole thing on day one if it is not designed
for.

**Right — the diagnosis.** Evergreen content compounds slowly and never spikes.
Timely content is how a small account gets reach it has not earned yet, because
the algorithm is looking for recency on a topic people are already searching.
An agency account that only posts its own case studies reads as a brochure.

**Right — the pipeline shape.** Crawl raw → LLM structures and verifies →
existing generation pipeline continues. That separation is correct and it is
what keeps the LLM out of the fetching business, where it is slow, expensive and
unreliable.

**Change 1 — not Playwright or Selenium.** You already removed the browser stack
from the Outreach agent, for reasons that apply here word for word: ~400 MB in
the image, two-minute cold starts, and a renderer that silently renders
differently is worse than no renderer. Every source worth having for trend
detection publishes JSON or RSS:

| Want | How, without a browser |
|---|---|
| Hacker News front page + Show HN | Algolia API — **already integrated** in the Lead Finder |
| Reddit (r/programming, r/SaaS, …) | redditapis — **already integrated** |
| X / Twitter discussion | twitterapis — **already integrated** |
| Developer Q&A volume | Stack Exchange — **already integrated** |
| News + verification + recency | **Tavily** — key already live, `topic=news`, `time_range=day` |
| New AI/open-source tools | GitHub Search API (`created:>date sort:stars`), free, no key needed for search |
| Product launches | Product Hunt GraphQL, free |
| Broad headlines | Google News RSS (`news.google.com/rss/search?q=`), free, no key |
| Developer commentary | dev.to `/api/articles?top=1`, free |

Selenium/Playwright buys access to exactly one class of source: JS-rendered
sites that block APIs. Nothing in that table is one. Chromium is already in the
Content Poster image for slide rendering, so if a specific source later demands
a browser, it costs nothing to add — but building on it *by default* means
paying its cost on every run for a capability almost nothing needs.

**Change 2 — DuckDuckGo scraping is a trap.** The unofficial HTML endpoint is
rate-limited, unversioned, changes without notice and is against their terms.
Tavily is already paid for, returns clean extracted content instead of HTML, and
gives a relevance score and recency filter. Use it.

**The problem nobody has hit yet — see §2.** It is the reason this cannot just
be bolted on.

---

## 2. The problem that breaks this on day one

**The grounding gate will reject 100% of trend content, and it will be right to.**

The hardest rule in the system today is: *every number, client and claim in any
output must come from the site repo via the facts snapshot.* That rule is what
stands between an agent that markets WizCodes and one that invents things about
WizCodes in public. It is not negotiable and it has already caught a live
hallucination.

But a timely post says things like "Anthropic shipped X on Tuesday" or "that
framework crossed 50k stars". Those facts are true, they are the entire point of
the post, and **none of them are in wizcodes.site**. The current gate rejects
every one.

The wrong fix is to relax the gate for trend posts. That trades the system's
single best safety property for reach, and the failure mode — confidently
publishing an invented statistic about a company that is not yours — is worse
than the one the gate was built for.

### The fix: two corpora, two rules, one gate

| Claim about | Must trace to | Rule |
|---|---|---|
| **WizCodes** — our projects, clients, numbers, results | the site-repo facts snapshot | unchanged, absolute |
| **The world** — anyone else's product, release, statistic | a **captured source document** in `content.trend_sources`, with URL and retrieval timestamp | must exist, must be recent, must be corroborated |

So the gate gets *stricter*, not looser: an external figure with no stored
source is still rejected, exactly as an invented WizCodes figure is. The
difference is that there is now a legitimate way to satisfy it — go and capture
the source first.

Three consequences fall out of this, all good:

1. **Citations become free.** You cannot cite what you did not capture; once you
   capture to cite, the citation is already there. This is what makes the
   AEO/GEO ambitions in §7 real rather than aspirational.
2. **Corroboration becomes enforceable.** Require ≥2 independent sources for any
   hard number before it may be published. Breaking news is wrong often enough
   that a single-source statistic is a liability.
3. **Staleness becomes visible.** A stored `retrieved_at` makes "this claim is
   four days old" a query, not a guess.

---

## 3. Architecture

```
                    ┌──────────── harvest (hourly, cheap) ─────────────┐
  HN · Reddit · X · SE · GitHub · ProductHunt · GoogleNews RSS · dev.to
                    └───────────────────┬──────────────────────────────┘
                                        ▼
                          content.trend_items  (raw, deduped)
                                        │
                    ┌───────────────────▼──────────────────┐
                    │  score  (Groq — cheap, high volume)  │
                    │  novelty · velocity · relevance      │
                    └───────────────────┬──────────────────┘
                                        │  top N only
                    ┌───────────────────▼──────────────────┐
                    │  verify (Tavily)                     │
                    │  corroborate · capture source text   │
                    └───────────────────┬──────────────────┘
                                        ▼
                       content.trend_sources  (cited, timestamped)
                                        │
                    ┌───────────────────▼──────────────────┐
                    │  angle (Claude proxy, opus-4-8)      │
                    │  trend  ->  what it means for a      │
                    │             founder  ->  our service │
                    └───────────────────┬──────────────────┘
                                        ▼
                          content.trend_angles  (ready to post)
                                        │
                                        ▼
                    existing calendar → write → validate → publish
```

**Where it lives.** A `trends/` package inside `content_poster_agent`, plus its
own Modal cron. Not a fourth agent: it has no schedule of its own worth
defending, it writes only to the `content` schema, and its only consumer is the
writer that already lives here. A fourth agent would mean a fourth deploy, a
fourth secret and a fourth thing to monitor for one package of code.

**Two crons, not one.** Harvest is hourly and cheap (free APIs, no LLM). Scoring
and angle synthesis run twice a day on whatever accumulated. Splitting them
means a spike in trend volume costs API calls, not LLM budget.

**Three tables**, all in `content` (this agent owns them):

```sql
content.trend_items    -- raw: source, external_id, title, url, summary,
                       -- surfaced_at, velocity signals, UNIQUE(source, external_id)
content.trend_sources  -- captured evidence: trend_id, url, title, extract,
                       -- retrieved_at, publisher  ← what citations and the
                       --                             grounding gate read
content.trend_angles   -- the usable output: trend_id, angle, service_line,
                       -- claims[], status, used_at, expires_at
```

---

## 4. The relevance gate — most trends must be rejected

This is where systems like this usually fail. Not from lack of input, but from
posting about everything, because the pipeline was built to produce output and
producing nothing feels like failure.

**Rejecting is the normal outcome.** WizCodes builds web apps, mobile apps and
AI automation for small businesses in the US, UK and EU. Most of what trends on
Hacker News has nothing useful to say to that audience, and a post that stretches
to connect them is transparently a stretch — which is worse than silence,
because it reads as a brand chasing relevance.

Three questions, all of which must pass:

1. **Is it true, and can we prove it?** ≥2 independent sources for any hard
   number. Single-source claims may be *referenced* ("reports suggest") but
   never asserted as fact.
2. **Does a founder or business owner care?** Not "is it interesting to
   developers". The audience is a person who runs a dental practice or a
   fifteen-person SaaS. A Rust compiler improvement fails this. "The AI tool
   your competitors just started using does X" passes.
3. **Can we say something *true* that connects to what we do?** Not "can we
   mention our service". If the honest answer to "so what should a business
   owner do about this?" does not naturally touch web, mobile or AI automation,
   skip it. There will be plenty of others.

A trend passing 1 and 2 but failing 3 is still worth posting as pure Teach
content with no service connection at all. That is the value-first behaviour you
described, and it should be the *majority* of timely posts — roughly 4 in 5.
An account that ties every trend back to its own services is doing native
advertising and everyone can tell.

---

## 5. The bridge: trend → service, without an advert

The hard creative problem. The structure that works, and the one to prompt for:

```
1. The news, stated plainly and cited.        "X shipped Y this week."
2. The second-order consequence.              "Which means Z is now trivial /
                                               newly broken / no longer a moat."
3. What a business owner should actually do.  "If you run a booking flow,
                                               the thing to check is …"
4. (only sometimes) how we relate.            "We rebuilt exactly this for
                                               <real project>." — and only if
                                               that project genuinely exists.
```

Step 4 is optional and should be **absent from most posts**. Steps 2 and 3 are
where the value is, and they are what makes step 4 credible on the one post in
five where it appears. Reversing that ratio is how an account gets muted.

**Storytelling and psychology, concretely** — not as adjectives:

- Open on the consequence, never the announcement. Not "OpenAI released X" but
  "Your competitor's support queue got 40% cheaper on Tuesday."
- Specificity is the credibility mechanism. A named tool, a real number with a
  citation, a dated event.
- One idea per post. A trend post that also explains your services is two posts.
- Admit the limit. "This does not work if your data is in a PDF" earns more
  trust than any claim.

---

## 6. A new pillar, and where it sits in the mix

CAMPAIGN.md §4 has six pillars. Add a seventh and rebalance — timely content
should be a meaningful share without displacing proof, which is what actually
converts:

| Pillar | Now | Proposed |
|---|---|---|
| Proof | 30% | 25% |
| Teach | 25% | 20% |
| **Timely** | — | **20%** |
| POV | 20% | 15% |
| Process | 15% | 12% |
| Client voice | 7% | 5% |
| Direct offer | 3% | 3% |

Timely posts are the only ones that may be **inserted off-calendar**. A trend
with real velocity is worth a post today, not on Thursday at 18:30 — that is
the entire advantage of having this layer. Cap it: at most one inserted post per
day, per platform, so the fixed rhythm an audience learns is disturbed rather
than replaced.

---

## 7. SEO, AEO, GEO, LLMO — where each actually applies

Worth being precise, because three of these four do almost nothing on Instagram.

| | What it is | Where it works here |
|---|---|---|
| **SEO** | ranking in classic search | **blog + dev.to only.** Social captions are not meaningfully indexed. |
| **AEO** | being the answer in a featured snippet / voice result | **blog.** Needs a direct question answered in the first 40 words. |
| **GEO** | being cited by generative search (AI Overviews, Perplexity) | **blog + dev.to.** Rewards clear structure, dates, named sources, statistics. |
| **LLMO** | being retrieved and quoted by an LLM | **blog + `llms.txt`.** Rewards factual density and unambiguous attribution. |

So the honest split:

- **On social**, discovery is platform-native: the first line, the hashtags, the
  format. Chasing SEO in an Instagram caption is effort spent on nothing.
- **On the blog and dev.to**, all four apply — and this is the highest-leverage
  part of the whole proposal, because those pages persist and compound.

**Which suggests the most valuable output of this layer is not a social post.**
A trend that clears §4's three gates is a *blog topic*, and the blog agent is
already good at writing those. Feeding the trend store into the blog agent's
topic selection turns a one-day social spike into a page that ranks for a year —
and the social post then promotes it. That is the compounding version.

**Citations, and the tension with reach.** The platform validator already knows
LinkedIn suppresses posts with links in the body. Resolution:

- Name the source inline, always: "Stack Overflow's 2026 survey found …"
- Put the URL in the **first comment** (LinkedIn, Instagram).
- On the blog, full inline links plus a dated sources list — that is what GEO
  and LLMO actually reward.

---

## 8. Brand safety

You asked for "slightly controversial while remaining professional". That is
achievable, and it needs a hard boundary because the failure is not recoverable.

**Have opinions about:** technology choices, pricing models, agency practices,
build-vs-buy, whether a hyped tool is worth it, industry norms that waste money.
These are defensible, on-topic, and a buyer can argue back — which is the point.

**Never:** politics, religion, war, individual people or named competitors as
targets, layoffs, anything involving a tragedy, and any take on a story less
than a few hours old. A `NO_GO_TOPICS` list enforced as a validator, not a
prompt instruction — the same discipline as `no_write_endpoints.py`, because a
rule in a prompt is a suggestion.

**Two more gates:**

- **Cool-off.** Nothing under ~6 hours old. Breaking stories get corrected, and
  the reputational cost of confidently amplifying a wrong one is far larger than
  the reach lost by waiting.
- **Named-entity care.** Criticise a *practice*, not a *company*. "Per-seat
  pricing for AI tools is going to age badly" is a take. Naming a company as bad
  is a liability with no upside for a studio that wants their customers.

---

## 9. Cost

Everything below is free-tier or already paid for:

| Source | Cost | Note |
|---|---|---|
| HN Algolia, Google News RSS, GitHub Search, dev.to, Product Hunt | $0 | no key, or free key |
| Reddit / X | already budgeted | reuse the Lead Finder's caps |
| Tavily | already configured | 1 credit/basic search; verify current free allowance before enabling |
| Groq scoring | free tier | shared account pool with the Lead Finder — budget as one |
| Claude proxy | existing cap | only for the top few angles per day, never for scoring |

Add a `trends` provider to `core.spend_ledger` with its own daily cap, same as
every other metered call.

---

## 10. Things you did not ask for, that I would add

1. **Feed the blog agent, not just social.** §7 — the compounding play, and
   probably the highest-value item in this document.
2. **A trend memory, so the same story is not posted twice.** `trend_items` is
   deduped by `(source, external_id)`, but the *story* repeats across sources.
   Cluster by embedding or title similarity before scoring.
3. **Velocity, not just presence.** A topic appearing in three sources within
   six hours is a trend; the same topic in one source is noise. Cross-source
   corroboration is both the safety mechanism and the ranking signal — one
   design serving two purposes.
4. **Expiry.** Every angle gets `expires_at`. An unused timely angle is deleted,
   not queued — a stale take published late is worse than none.
5. **A weekly "what we did not post" line in the digest.** The rejects are the
   best signal for whether the relevance gate is calibrated. If it rejects
   everything for a week, it is too tight; if nothing, too loose.
6. **Reuse the Lead Finder's fetches.** It already pulls HN, Reddit, X and
   Stack Exchange every 30 minutes and throws away everything that is not a
   lead. Writing those same payloads to `trend_items` on the way past costs one
   INSERT and zero API calls.

---

## 11. Decisions — settled 7 Aug 2026

These are the contract. Changing one means changing this section first.

| Decision | Chosen | Consequence |
|---|---|---|
| **Location** | `trends/` inside `content_poster_agent` | Not a fourth agent. Owns `content.trend_*`. |
| **Scope** | **Blog + social** | The trend store is readable by the blog agent for topic selection. That is the compounding play (§7): a ranked page lasts a year, a post lasts a day. Blog agent lives in another repo, so it reads the store rather than importing anything. |
| **Risk** | **Practices, never people** | Opinions on pricing models, build-vs-buy, agency practice, whether a hyped tool earns its hype. Never a named company or person as a target. Enforced by a validator, not a prompt (§8). |
| **Timing** | **Insert off-calendar, max 1/day/platform** | Timeliness is the whole point; a take posted three days late is worthless. The cap keeps the learned rhythm disturbed rather than replaced. |
| **Volume** | **Piggyback + light Tavily** | The Lead Finder already fetches HN/Reddit/X/SE every 30 minutes and discards non-leads. Those payloads get written to `trend_items` on the way past: zero extra API calls. Tavily is used only for verification of items that already scored well. |

### What the volume decision implies

The Lead Finder becomes a **producer for two consumers**. That is a deliberate
crossing of the single-writer rule and it needs stating precisely, because the
rule is what makes the rest of the system safe:

- `core.leads` — still **Lead Finder only**. Unchanged, absolute.
- `content.trend_items` — written by the Lead Finder as a by-product, read by
  the Content Poster.

The Lead Finder is therefore the sole writer of *both* tables. No second writer
appears anywhere. What crosses is that one agent now writes into another agent's
schema — acceptable because the direction is one-way, the table is append-only,
and the alternative is paying twice for identical HTTP requests.
