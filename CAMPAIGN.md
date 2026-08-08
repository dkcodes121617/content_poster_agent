# WizCodes — Social Distribution Campaign

> The content system this agent executes. Written to be run by an agent but judged by a
> human: if a post reads like it came from a content tool, it has failed regardless of
> whether it published successfully.
>
> Starting point: one intro post on each platform. This document takes it from there.

---

## 1. What changed from the original plan

**No approval gate.** The agent drafts, validates and publishes on its own. Telegram becomes
a *notification and task* channel, not a permission channel:

| Telegram now does | Telegram no longer does |
|---|---|
| "Published to LinkedIn + FB + Threads — here are the links" | Ask permission before publishing |
| "**Post this on X yourself** — copy block below" | Wait for a button press |
| "3 new leads, highest is …" | Block a run for days |
| "Something failed: <reason>" | |

What replaces the human gate is a **validator stack** (§7). A gate that a human clicks
through in two seconds was never really a quality control; a gate that refuses to publish a
post containing an invented statistic is.

**A kill switch still exists.** `DRY_RUN=1` stops every outward action across every agent.
And any post can be pulled after the fact — Telegram carries the permalink for exactly that.

---

## 2. Positioning — what every post is secretly arguing

WizCodes is a small studio in Ahmedabad building web, mobile and AI products for clients
mostly in the US, UK and EU. The offer that makes it unusual is the **free prototype**: a
working thing before money changes hands.

Every post is one of three arguments:

1. **"We have actually built this."** Named projects, real constraints, real numbers.
2. **"We will show you before you pay."** The free prototype, told as process, not as an ad.
3. **"We think clearly about your problem."** Opinions a buyer can test against their own
   experience.

Nothing else gets posted. A post that is not one of these three is filler, and filler is what
teaches an audience to scroll past you.

---

## 3. Voice — the rules that keep it from reading as AI

These are enforced by a validator (§7.2), not left to the model's judgement.

**Banned outright** — these are the tells:

```
delve · in today's fast-paced world · unlock · elevate · game-changer · seamless
revolutionise · leverage (as a verb) · robust solution · cutting-edge · empower
"It's not just X — it's Y" · "Let's dive in" · "The result? " as a one-word sentence
emoji bullet lists · 🚀 anywhere · "Thoughts?" as a closing line
tricolon padding ("faster, smarter, better")
```

**Required:**

- **Open on tension, never on context.** Not "In the world of software development…" but
  "A dental clinic in Leeds was losing nine appointments a week to no-shows."
- **One idea per post.** If it needs two, it is two posts.
- **Specific beats impressive.** "Sub-200ms" beats "lightning fast". "Nine appointments"
  beats "significant losses".
- **Vary sentence length deliberately.** Uniform 15-word sentences are the strongest AI
  signal there is. Write a four-word sentence. Then a longer one that earns its length.
- **Name real things.** CuePilot, SolarSathi, ClarivueXAI, Destiny AI Journal — pulled from
  the site repo, never invented.
- **End with a real next step**, or nothing. "Happy to send the prototype spec if it's
  useful" is a real next step. "Thoughts?" is not.
- **Admit a limit somewhere.** The single fastest way to sound human is to say what a thing
  does *not* do. Perfect claims read as marketing; hedged claims read as experience.

**Never:** invent a client, a number, a testimonial or a result. Grounding comes from
`facts/snapshot.py` reading the site repo. This is a hard validator, not a style note.

---

## 4. Content pillars and their mix

| Pillar | Share | What it is | Where it works hardest |
|---|---|---|---|
| **Proof** | 30% | A real project, the constraint, what we did, the measurable outcome | LinkedIn, Instagram carousel |
| **Teach** | 25% | Cost breakdowns, architecture explainers, "how to brief a developer" | LinkedIn, X, dev.to |
| **POV** | 20% | A defensible opinion a buyer can argue with | Threads, X, LinkedIn |
| **Process** | 15% | How the free prototype actually runs, week by week | Instagram, Facebook |
| **Client voice** | 7% | A testimonial retold as a story, never as a pull-quote graphic | LinkedIn, Facebook |
| **Direct offer** | 3% | "Free prototype, here's the form" | Everywhere, sparingly |

**The 3% is not a typo.** One direct-offer post in roughly thirty. Everything else earns the
right to make it. An account that sells in every post gets muted; an account that sells in
one post out of thirty gets read when it does.

---

## 5. Platform matrix

Each platform is a different room with a different conversation. The same post cross-published
everywhere is the second-strongest signal (after voice) that nobody is really there.

| Platform | Audience | Format that wins | Images | Cadence | Post time (IST) | API |
|---|---|---|---|---|---|---|
| **LinkedIn** | Founders, ops leads, buyers | 120–200 word text post, or a 7–10 slide document carousel | 1 hero **or** 7–10 carousel slides | 3×/week | 18:30–19:30 (= 9am ET) | ⏳ in review |
| **Instagram** | Founders, designers, local SMBs | 5–8 slide carousel, 4:5 | **5–8** | 3×/week | 11:00 or 20:00 | ✅ **live** (§5.1) |
| **Facebook** | Local SMB, Gujarat + retargeting pool | Single image, 1:1, short copy | 1 | 3×/week | 20:00 | ✅ live |
| **Threads** | Builders, indie founders | Text-first, conversational, 1–2 sentences | 0–1 | 5×/week | 21:00 | ✅ live |
| **X / Twitter** | Devs, technical founders | 5–8 tweet thread | 1–4 | 3×/week | 19:00 | ❌ **manual via Telegram** |
| **dev.to** | Developers, long-tail SEO | Full blog syndication, canonical → wizcodes.site | inherits post | on every blog publish | — | ✅ live, `@wizcodes` |
| **Pinterest** | Long-tail visual search | Web-design visuals → /work pages | 1 | 2×/week | any | ✅ live, needs a board |
| ~~Hashnode~~ | — | — | — | — | — | ❌ **API went paid 13 May 2026** — every request now needs a Pro plan. Dropped. |
| **Google Business Profile** | Local search, Maps | 100–300 word update + 1 image | 1 | 1×/week | any | ⏳ access request (§5.2) |
| **YouTube Shorts** | — | screen-recording of a prototype | video | later | — | ❌ manual |

### 5.1 Instagram publishes without the Facebook Page link

The Instagram restriction was never a blocker — it blocked a route Instagram publishing does
not need.

The **Page-linked route** (`graph.facebook.com/<ig_business_id>/media`) requires the Business
Portfolio link Meta has restricted on this account. The **Instagram Login route**
(`graph.instagram.com/me/media`) uses an Instagram User token obtained through Instagram's own
OAuth, with no Facebook Page in the loop at all.

Verified against the live account:

```
GET  /me                        -> @wiz_codes, account_type BUSINESS
GET  /me/media                  -> 200, media listed        (instagram_business_basic)
POST /me/media (no image)       -> 400 "image_url is required"
GET  /me/content_publishing_limit -> 200 {"quota_usage": 0}
```

That `400` is the proof. A token lacking the publish scope returns a **permissions** error;
this one returned a **missing-parameter** error, which only happens once authorisation has
already passed. Token scopes confirmed:
`instagram_business_basic, instagram_business_content_publish, instagram_business_manage_comments, instagram_business_manage_insights, instagram_business_manage_messages`.

So `INSTAGRAM_APP_ACCESS_TOKEN` was already the right credential, and
`META_IG_BUSINESS_ACCOUNT_ID` is not needed — `PLATFORMS_ENABLED` now includes `instagram`.

**What the Instagram Login path costs:** hashtag *search*, product tagging and Partnership Ads.
None of the six content pillars touch any of them. Publishing, comments and insights all work.

**Token lifetime:** 60 days, refreshable indefinitely via
`GET graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token`. Already refreshed
once; the agent should call it on a weekly cron whenever the token is inside 20 days of expiry,
which makes it effectively permanent without a human in the loop.

### 5.2 Google Business Profile is gated, and the error says so

The `429 RESOURCE_EXHAUSTED` is misleading — read `"quota_limit_value": "0"`. A quota of zero
is not rate limiting; it means the project has **never been granted access**. Google gates the
Business Profile APIs behind a manual approval, and until it is granted every call fails this
way no matter how slowly you make it.

1. In the Cloud project, enable **Google My Business Account Management API**, **Business
   Profile APIs** and **My Business Business Information API**.
2. Submit the **Business Profile API access request form** (linked from Google's Business
   Profile API prerequisites page) with the project number `80579058468`, the business name and
   the GBP account that owns the listing.
3. Wait for the approval email — days to weeks, like LinkedIn.
4. Quota lifts from 0 on approval. Nothing else changes; the OAuth client is already created.

Requesting more quota via the "Request a higher quota limit" link in that error will **not**
work — there is no quota to raise until access is granted. Treat GBP exactly like LinkedIn:
start the request, build without it, switch it on when it lands.

**Why dev.to, Hashnode, GBP and Pinterest are in here and were not in the original plan:**
all four have free APIs, none needs approval, and each reaches an audience the four social
platforms do not. Syndicating an existing blog post to dev.to costs one API call and can
out-traffic the original. Google Business Profile posts are the cheapest local-SEO surface
that exists. These are the highest return-per-effort additions available, which is why they
come before chasing anything harder.

**The manual queue.** X and YouTube have no usable free API. The agent writes the content and
sends it to Telegram formatted for copy-paste — thread numbered, hashtags separated, images
attached. `core.manual_queue` tracks what has been handed over and what is still outstanding,
so a missed post shows up in the daily digest instead of vanishing.

---

## 6. The weekly rhythm

Fixed slots, because an audience learns a schedule and a schedule makes the agent's job
deterministic. All times IST.

| Day | LinkedIn | Instagram | Facebook | Threads | X (manual) | Other |
|---|---|---|---|---|---|---|
| **Mon** | — | Carousel · **Proof** (5–8 slides) | — | POV, 1 line | — | Pinterest ×1 |
| **Tue** | Text · **Teach** | — | Single · **Process** | Reaction to Mon's carousel | Thread · **Teach** | — |
| **Wed** | Carousel · **Proof** (7–10) | Carousel · **Process** | — | Behind-the-scenes line | — | GBP update |
| **Thu** | Text · **POV** | — | Single · **Client voice** | POV, 1 line | Thread · **Proof** | Pinterest ×1 |
| **Fri** | — | Carousel · **Teach** | Single · **Proof** | Week-in-review, 2 lines | Thread · **POV** | — |
| **Sat** | — | — | — | Light/human line | — | — |
| **Sun** | — | — | — | — | — | — |

Weekly totals: LinkedIn 3, Instagram 3, Facebook 3, Threads 5, X 3, GBP 1, Pinterest 2.
**Plus** whatever the blog and case-study agents publish, which syndicates automatically.

**Saturday is deliberately light and Sunday is empty.** Accounts that post seven days a week
at identical times read as automated, because they are. The gap is a signal.

**Jitter every slot by ±25 minutes.** A post that lands at exactly 20:00:00 every single time
is a fingerprint.

---

## 7. What replaces human approval

Four gates. A post that fails any of them is not published; it is logged and reported to
Telegram with the reason.

### 7.1 Grounding gate
Every named project, number, client and claim must appear in the facts snapshot built from
the site repo. A post citing a statistic that is not in the source data is rejected outright.
This is the gate that matters most — it is the difference between an agent that markets you
and an agent that invents things about you in public.

### 7.2 Voice gate
The banned-phrase list from §3, plus structural checks: sentence-length variance above a
floor, no emoji bullets, no "It's not just X" construction, opening line is not a
context-setting throat-clear.

### 7.3 Repetition gate
Embedding similarity against the last 60 published posts. Over threshold → regenerate. The
blog agent already proves this pattern works; the same uniqueness machinery applies here, and
it is what stops month three sounding like month one.

### 7.4 Platform gate
Character limits, image count and aspect ratio, hashtag count, link placement (LinkedIn
suppresses posts with external links in the body — the link goes in the first comment).

---

## 8. Hashtags

Hashtags are a discovery tool on two platforms and noise on the rest.

| Platform | Count | Strategy |
|---|---|---|
| **Instagram** | 8–12 | 3 broad (100k–1M), 5 niche (10k–100k), 2 branded. Placed in the **first comment**, not the caption. |
| **LinkedIn** | 3 | Exactly three, at the end. More than three measurably reduces reach. |
| **X** | 1–2 | In-line where it reads naturally, never appended as a block. |
| **Facebook** | 0–2 | Facebook hashtags do almost nothing; 2 is the ceiling before it looks like spam. |
| **Threads** | 1 | Threads supports a single topic tag. |
| **Pinterest** | 0 | Keywords in the description do the work instead. |

Rotate from a pool per pillar so the same block never repeats verbatim. Branded tags:
`#WizCodes` `#BuiltByWizCodes`.

---

## 9. The eight-week launch

One intro post is a standing start. The sequence below builds credibility before it asks for
anything.

**Weeks 1–2 — Proof only.** No offer, no CTA beyond a link to the work. Six LinkedIn posts,
six Instagram carousels, all Proof and Process pillars. The goal is that a visitor landing on
the profile sees a body of real work, not an account that started selling on day one.

**Weeks 3–4 — Add Teach.** Cost breakdowns, "what a realistic MVP budget looks like", "how to
brief a developer". This is the pillar that gets saved and shared, which is what grows reach
without paid spend. Start X threads here.

**Weeks 5–6 — Add POV.** Opinions with a real edge: why fixed-scope beats hourly, why most
agencies' discovery phase is a paid sales call, what the free prototype costs us and why we
do it anyway. This is where an audience starts arguing in the comments, and arguments are
distribution.

**Week 7 — First direct offer.** By now there are ~40 posts of evidence behind it. One post,
clearly framed, on LinkedIn and Facebook.

**Week 8 onward — steady state**, on the §6 rhythm and the §4 mix.

**Measure at week 8, not before.** Follower count is the wrong metric. The ones that matter:
profile visits, link clicks to `/get-started`, and inbound conversations. All three land in
`core.leads` via the Wico/contact-form pipe, so the campaign's effect is measurable in the
same table the outreach agent drains.

---

## 10. Image system — HTML/CSS rendered in a real browser

The original design composited one image per post with Pillow. Both halves of that were
wrong. Instagram and LinkedIn reward multi-slide carousels, so one image is the weakest
possible unit on either; and Pillow draw calls cannot reproduce the site's look.

**Slides are now real web pages, screenshotted.** `templates/slide.html` + `brand.css`,
rendered by headless Chromium at `deviceScaleFactor: 2`.

**Why this and not Pillow or SVG:** the premium feel of the site's hero and CTA sections comes
from specific CSS — the clipped-gradient headline (`--gradient-text`), the radial wash from
the top, the dot grid masked to fade, `--shadow-mockup`, and real Google Sans Flex kerning.
That is CSS the site already ships. Re-implementing it as draw calls means maintaining a
second, worse copy of the design system that drifts the moment the site changes. Rendering
the actual CSS means the slides **inherit** the design rather than imitate it.

`templates/brand.css` copies the `:root` tokens from `globals.css` **verbatim** — the same
`#2E90C4`, the same `linear-gradient(135deg,#2E90C4,#1E7AAB)`, the same two-tone wordmark. It
is a copy on purpose: the render runs on Modal with no access to the site repo's CSS. **Sync
rule:** when the site's tokens change, change them here. A social image in last year's blue
reads as a third-party tool posting on your behalf, which is the exact impression this system
exists to avoid.

**Seven slide roles**, one template, so the atmosphere and footer cannot drift between slides:

| Role | What it is |
|---|---|
| `cover` | Dark navy. Six words max. The only slide most people see. |
| `statement` | One idea, light background. |
| `metric` | One number, enormous. Never two — a slide with two numbers has neither. |
| `steps` | 3–4 numbered cards. The free-prototype process lives here. |
| `mockup` | Browser chrome around a real screenshot. Depicting real software is what separates a portfolio from a template. |
| `quote` | A client's words as a sentence, not a quote-card graphic. Quote cards read as stock; a sentence reads as a person. |
| `cta` | Dark navy, gradient pill. Closes the carousel. |

A carousel opens dark, runs light through the middle and closes dark. That rhythm is what
makes eight slides read as one piece.

**Canvases** (`tools/render.py --sizes`) — each platform gets its true aspect ratio, portrait
or landscape as the campaign needs:

```
instagram_portrait  1080x1350 (4:5)    linkedin_carousel  1080x1350 (4:5)
instagram_square    1080x1080 (1:1)    facebook_link      1200x630  (1.91:1)
instagram_story     1080x1920 (9:16)   x_post             1600x900  (16:9)
pinterest           1000x1500 (2:3)
```

**Emphasis is authored, not styled.** The writer marks a phrase with `*asterisks*`; the
template decides that means the clipped-gradient accent. The copy layer never touches colour.

**FLUX's role shrinks to background art only** — abstract texture and gradient fields behind
the CSS layer, on the slides that want depth. It is never asked to render text or a logo.

**Consistency is the point.** Eight slides that look like one system beat eight beautiful
unrelated images. That is what makes a small studio look established.

```powershell
python tools/render.py --demo    # renders a real 5-slide carousel to output/
```

---

## 11. Prerequisites for this agent

| Need | State |
|---|---|
| Facebook Page publishing | ✅ live, token never expires |
| Threads publishing | ✅ live, `@wiz_codes` |
| **Instagram publishing** | ✅ **live** via Instagram Login (§5.1) — no Page link needed |
| dev.to syndication | ✅ live, `@wizcodes` |
| Pinterest | ✅ token live, domain-verify tag added to `layout.tsx`. **Create one board** — a Pin with no board 400s. |
| Brand fonts + renderer | ✅ Google Sans Flex/Code committed; Chromium installed; demo carousel renders |
| LinkedIn | ⏳ Community Management API review — highest-value platform, start it now |
| Google Business Profile | ⏳ access request, not a quota bump (§5.2) |
| ~~Hashnode~~ | ❌ dropped — API requires a paid Pro plan as of 13 May 2026 |
| X / YouTube | ❌ no free API — manual queue via Telegram, by design |

**Two site-side actions:** deploy `wizcodes_next` so the Pinterest `p:domain_verify` tag goes
live (already added to `layout.tsx`, `tsc` clean), then click **Claim** in Pinterest settings.
