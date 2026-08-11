"""Writing prompts — CAMPAIGN.md §2, §3 and §5 as instructions.

Phrased as a professional brief rather than as commands. The ClaudeStore proxy's
injection guard rejects override-style phrasing ("reply with exactly X", "never
break character"), so constraints are expressed as *what a good answer looks
like*. The validators enforce them afterwards regardless of what the model does.
"""
from __future__ import annotations

# CAMPAIGN.md §3 — the tells. Enforced by validators/voice.py, repeated here so
# the model has a chance to avoid them before the gate rejects the draft.
BANNED_PHRASES = [
    "delve", "in today's fast-paced world", "unlock", "elevate", "game-changer",
    "game changer", "seamless", "revolutionise", "revolutionize", "robust solution",
    "cutting-edge", "cutting edge", "empower", "let's dive in", "lets dive in",
    "dive in", "thoughts?", "in the world of", "when it comes to",
    "at the end of the day", "needless to say", "it goes without saying",
    "first and foremost", "last but not least", "in conclusion",
    "take it to the next level", "supercharge", "turbocharge", "harness the power",
]

VOICE_RULES = """\
How WizCodes writes:

  - Open on tension, never on context. Not "In the world of software
    development..." but "A dental clinic in Leeds was losing nine appointments a
    week to no-shows."
  - One idea per post. If it needs two, it is two posts.
  - Specific beats impressive. "Sub-200ms" beats "lightning fast". "Nine
    appointments" beats "significant losses".
  - Vary sentence length deliberately. Uniform 15-word sentences are the
    strongest AI signal there is. Write a four-word sentence. Then a longer one
    that earns its length.
  - Name real things, and only things that appear in the facts below.
  - End with a real next step, or with nothing. "Happy to send the prototype
    spec if it's useful" is a real next step. "Thoughts?" is not.
  - Admit a limit somewhere. Saying what a thing does not do is the fastest way
    to sound human; perfect claims read as marketing.

Words and shapes that make writing read as machine-generated, so they never
appear: delve, unlock, elevate, seamless, game-changer, cutting-edge, empower,
robust solution, leverage as a verb, "It's not just X - it's Y", "Let's dive
in", "The result?" as a sentence, "Thoughts?" as a closing line, emoji bullet
lists, rocket emoji, and tricolon padding like "faster, smarter, better".

Never invent a client, a number, a testimonial, a project or a result. Every
figure and every name must appear in the facts provided. This is checked
automatically after you write, and anything that fails is discarded."""

# The two claims that are never publishable, stated as what a good answer looks
# like rather than as a prohibition — the proxy's injection guard rejects
# override-style phrasing. validators/claims.py enforces this regardless of
# what the model does with it, and it is repeated here so the usual case is a
# first draft that passes rather than a regeneration.
CLAIMS_RULES = """\
Two things never appear, in any post, in any form:

  - **How long anything takes us.** No "in 48 hours", no "within two weeks", no
    "same-day turnaround", no "ready by Friday". How long a build takes depends
    entirely on the requirements, so any number attached to delivery is a
    promise nobody has made. Describe the process without a duration: "a working
    prototype before any money changes hands" says everything the timeline would
    have, and is true.

  - **What we charge.** No figure, no range, no "starting at". Our cost depends
    on the requirements.

Both of those are about NUMBERS AND DURATIONS, not about the subject. Compare
our approach with how others price and deliver as much as you like. These are
all good, and the second half is where the useful writing lives:

  - "We build a working prototype before any money changes hands." (the offer -
    always fine, it has no figure in it)
  - "Most agencies bill discovery as a paid phase before anything gets built."
  - "Agencies quote for a specification. We build the thing and let you look."
  - "CuePilot answers in under 200ms." (a PERFORMANCE figure, not a delivery
    time - these are the best sentences in any proof post, use them)

ONE THING TO KNOW ABOUT COMPARISONS, because it is easy to get wrong:

Describe how the industry works, not what it charges in figures. "Typical agency
retainers run into five figures a month" reads well and is the kind of sentence
that gets a post rejected, because a number about someone ELSE'S business needs
a source we have actually fetched, and an evergreen post has none. The same
point without a figure is publishable and just as strong:

  instead of  "agencies charge £15,000 for a marketing site"
  write       "agencies quote a fixed price against a specification you have to
               write first, and changing it costs extra"

  instead of  "80% of projects run over budget"
  write       "the overrun conversation happens after the money is spent"

The only figures you may state are ones about WizCodes that appear in the facts
below, and — on a timely post only — figures from the verified sources supplied
with it."""

PILLAR_BRIEFS = {
    "proof": "Tell one real project as a story: the constraint the client had, "
             "what was built, and the measurable outcome. Name the project.",
    "teach": "Explain something a buyer can act on - what software actually "
             "costs, how to brief a developer, how to tell a good quote from a "
             "bad one. Useful enough to save.",
    "pov": "State a defensible opinion a buyer could argue with. It should cost "
           "something to say - an opinion nobody could disagree with is filler.",
    "process": "Show how the free prototype actually runs, week by week. Process, "
               "not an advert for the process.",
    "client_voice": "Retell a real client's experience as a story in your own "
                    "words, using only testimonials provided. Never present a "
                    "quote you were not given.",
    "direct_offer": "Make the offer plainly: a free working prototype before any "
                    "money changes hands. One post in thirty is this one, so it "
                    "can be direct without apologising for itself.",
    "timely": "React to something that happened THIS WEEK, using only the "
              "verified angle and sources supplied below. Open on the "
              "consequence, not the announcement. State what it means for a "
              "business owner and what they should check. Name the source "
              "in the text ('according to <publisher>') - never paste a URL, "
              "which is added separately as a first comment.",
}

TIMELY_BRIEF = """\
This is a TIMELY post about something that happened this week.

THE VERIFIED ANGLE - the only external facts you may state:

  What happened : {headline}
  Why it matters: {so_what}
  What to do    : {action}
  Source        : {publisher}

RULES SPECIFIC TO TIMELY POSTS:
  - Every figure you state must appear in the angle above. Nothing else is
    verified, and unverified numbers are rejected automatically.
  - Name the source in the sentence: "according to {publisher}". Do NOT paste
    the URL - it goes in the first comment, where it does not cost reach.
  - Criticise practices, never companies or people by name.
  - {service_note}
  - Do not force a connection to WizCodes. Most timely posts should have none,
    and a stretched link is obvious to a reader.
"""

SERVICE_NOTE_NONE = (
    "This one has NO service connection. Write it as pure value - the point is "
    "that a founder learns something, not that we sell something."
)
SERVICE_NOTE_SOME = (
    "This relates to {service_line}. You may end with one plain sentence "
    "connecting it, but only if it reads as help rather than an advert."
)

PLATFORM_BRIEFS = {
    "facebook": "A single short post for a local small-business audience: 40-80 "
                "words, plain sentences, at most two hashtags. One image.",
    # Budget stated well below the real 500 ceiling, for the reason recorded on
    # the Pinterest brief: given the exact limit a model treats it as a target
    # and overshoots. Told 380, its overshoot still lands inside 500.
    "threads": "HARD LIMIT: under 380 characters - roughly 60 words. One or two "
               "conversational sentences for builders and indie founders. At "
               "most one topic tag. It should read like a person thinking out "
               "loud, not a summary. Write short first rather than trimming.",
    "instagram": "A caption for a carousel: a strong first line that works as a "
                 "preview, then 40-90 words. Hashtags go in the first comment, "
                 "so do not put them in the caption.",
    "linkedin": "120-200 words for founders and operations leads. Exactly three "
                "hashtags at the end. No external link in the body - LinkedIn "
                "suppresses those, so the link goes in the first comment.",
    # The character budget goes FIRST and is stated below the real ceiling.
    # Measured: given "under 500", three consecutive drafts came back at 1148,
    # 619 and 699 characters and were all rejected. A model told the exact limit
    # treats it as a target and overshoots; told a tighter number, its overshoot
    # still lands inside the real one.
    "pinterest": "HARD LIMIT: the caption must be UNDER 400 CHARACTERS - about "
                 "60 words. That is the whole post; write it short first rather "
                 "than writing long and trimming. A keyword-rich description that "
                 "reads naturally, plus a title under 100 characters. No hashtags: "
                 "keywords in the description do the work on Pinterest.",
    "x": "A thread of 5-8 tweets for developers and technical founders. Separate "
         "each tweet with a BLANK LINE - those breaks are where the thread is "
         "split, so put them where you actually want them. Each tweet must be "
         "under 280 characters. The first tweet has to work alone: nobody reads "
         "tweet two unless tweet one earned it. One or two hashtags in-line "
         "where they read naturally, never appended as a block.",
    "youtube": "A short script for a screen recording, 45-60 seconds spoken. "
               "Write what is said, not shot directions.",
}

EMPHASIS_RULE = """\
Mark the phrase that should carry visual emphasis with *asterisks*. The template
turns that into the brand's gradient; the writing never mentions colour. Open
and close every emphasis - a stray asterisk loses the emphasis entirely.

Slides are PLAIN TEXT otherwise. No backticks, no markdown links, no headings,
no bullets, no HTML. Those characters reach the image and get set at 99 pixels."""


# Structured fields are lists or objects, so a character budget on the field
# itself would be meaningless. Their per-entry limits are described instead.
_STRUCTURED = {
    "steps": "3-4 objects, each {{title (max {step_title}), detail (max {step_detail})}}",
    "items": "3-5 strings, each max {item} chars",
    "nodes": "3-5 strings, each max {node} chars — two or three words",
    "stats": "exactly 3 objects, each {{value (max {stat_value}), label (max {stat_label})}}",
    "chart": "an object — see the JSON below. Series labels max {series_label} chars",
    "before": "an object {{label, text (max {body})}}",
    "after": "an object {{label, text (max {body})}}",
}


def _field_spec(field: str, budgets: dict[str, int]) -> str:
    """One field, with the limit the validator will actually apply.

    The exact character budget, not a word-count guess. Measured across three
    review runs: "keep titles under about 12 words" produced 43-, 44- and
    55-character cover titles against a 42 budget, every one a regeneration. A
    stated number is a constraint the writer can satisfy on the first attempt.
    """
    if field in _STRUCTURED:
        return f"{field}: " + _STRUCTURED[field].format(**budgets)
    budget = budgets.get(field)
    return f"{field} (max {budget} chars)" if budget else field


def carousel_spec(archetypes: list[str], budgets_note: bool = True) -> str:
    """The exact deck to write, generated from the archetype registry.

    Generated rather than written out, because a hand-maintained list of roles
    in a prompt is a second source of truth that drifts from
    `campaign/visual.py` the first time an archetype changes — and it drifts
    silently, producing JSON the validator then rejects for reasons the writer
    was never told.

    The deck's *shape* is chosen by the rotation ledger before this is called.
    The writer is told which archetypes to fill, not asked to pick them: asking
    is what produced one deck shape every day for a month.
    """
    from campaign import visual

    lines = [
        (
            f"This deck is {len(archetypes)} slides. Each slide has a fixed role, in "
            "this order, and the roles are not interchangeable:"
        ),
        "",
    ]
    for i, name in enumerate(archetypes, 1):
        a = visual.resolve(name)
        if not a:
            continue
        budgets = a.budgets()
        required = ", ".join(_field_spec(f, budgets) for f in a.required)
        optional = (
            "\n     optional: " + ", ".join(_field_spec(f, budgets) for f in a.optional)
            if a.optional else ""
        )
        lines.append(f"  {i}. {a.name} - {a.brief}")
        lines.append(f"     REQUIRED, every one of these or the slide is rejected: {required}"
                     f"{optional}")
    lines.append("")
    lines.append(_SHAPES_FOR(archetypes))
    if budgets_note:
        lines.append("")
        lines.append(
            "Those character limits are hard. Each field is set in large type on an "
            "image, and one that has to be shrunk to fit no longer looks like the "
            "same design - so an over-long field is rejected rather than squeezed."
        )
    lines.append("")
    lines.append(EMPHASIS_RULE)
    return "\n".join(lines)


def _SHAPES_FOR(archetypes: list[str]) -> str:
    """A worked JSON example for exactly the archetypes in this deck."""
    from campaign import visual

    examples = {
        "cover_bold": '{"role":"cover_bold","kicker":"Case study","title":"Nine no-shows a week, *gone*."}',
        "cover_question": '{"role":"cover_question","kicker":"Buying software","title":"What does a website *actually* cost?"}',
        "cover_stat": '{"role":"cover_stat","kicker":"Reach","value":"11","label":"countries with a live build"}',
        "cover_mockup": '{"role":"cover_mockup","kicker":"Work","title":"Shift planning for *three clinics*."}',
        "metric_hero": '{"role":"metric_hero","kicker":"Result","value":"<200ms","label":"median response","body":"..."}',
        "stat_row": '{"role":"stat_row","title":"Where the work has *landed*","stats":[{"value":"26","label":"projects"},{"value":"11","label":"countries"},{"value":"5","label":"open-source tools"}]}',
        "bar_chart": '{"role":"bar_chart","title":"Where the *seconds* went","chart":{"unit":"s","series":[{"label":"Images","value":3.1},{"label":"Scripts","value":1.8},{"label":"Fonts","value":0.7}]}}',
        "comparison_bar": '{"role":"comparison_bar","title":"Two ways to *start*","chart":{"unit":" weeks","series":[{"label":"Working prototype","value":1},{"label":"Paid discovery","value":4}]}}',
        "donut": '{"role":"donut","title":"Already on a *phone*","chart":{"value":78,"label":"of sessions on mobile"}}',
        "statement": '{"role":"statement","kicker":"The problem","title":"The booking page worked. *Nobody used it.*","body":"..."}',
        "steps": '{"role":"steps","title":"The *free prototype*","steps":[{"title":"You describe it","detail":"One call."},{"title":"We build it","detail":"Working, not a mockup."},{"title":"You decide","detail":"Or walk away."}]}',
        "checklist": '{"role":"checklist","title":"Four things to *ask for*","items":["Who owns the code","What happens if the developer leaves","Whether hosting is included","How changes are priced"]}',
        "flow_diagram": '{"role":"flow_diagram","title":"How a brief becomes *software*","nodes":["Brief","Prototype","Your call","Build","Handover"]}',
        "before_after": '{"role":"before_after","title":"Same content. *Different* result.","before":{"label":"Before","text":"..."},"after":{"label":"After","text":"..."}}',
        "myth_fact": '{"role":"myth_fact","myth":"You need the full spec first.","fact":"You need *one working screen*."}',
        "mockup_browser": '{"role":"mockup_browser","kicker":"Work","title":"A booking desk that *answers*.","url":"wizcodes.site/work/cuepilot"}',
        "graphic_embed": '{"role":"graphic_embed","kicker":"From the blog","title":"The four *guardrails*"}',
        "quote": '{"role":"quote","quote":"They shipped the thing they said they would.","attribution":"Priya Raman, Northgate Dental"}',
        "cta_pill": '{"role":"cta_pill","title":"See it before you *pay for it*.","body":"...","pill":"wizcodes.site/get-started"}',
        "cta_split": '{"role":"cta_split","title":"See it before you *pay for it*.","pill":"wizcodes.site/get-started","note":"No retainer."}',
    }
    lines = ["Return a JSON object shaped exactly like this:",
             '{"caption": "...", "hashtags": ["..."], "slides": [']
    for name in archetypes:
        a = visual.resolve(name)
        key = a.name if a else name
        lines.append("  " + examples.get(key, '{"role":"' + key + '"}') + ",")
    if len(lines) > 2:
        lines[-1] = lines[-1].rstrip(",")
    lines.append("]}")
    imaged = [n for n in archetypes if visual.is_imaged(n)]
    if imaged:
        lines.append("")
        lines.append(
            "Do NOT write an `image` or `svg` field. Artwork for "
            f"{', '.join(sorted(set(imaged)))} is attached from the site's own "
            "graphics library after you write - you supply only the words."
        )
    return "\n".join(lines)


def post_system_prompt(facts_block: str, stats_block: str = "") -> str:
    stats = f"\n\n{stats_block}" if stats_block else ""
    return f"""\
You write short social posts for WizCodes, a small software studio in Ahmedabad \
building web, mobile and AI products for clients mostly in the US, UK and EU. \
The offer that makes it unusual is a free working prototype before any money \
changes hands.

Every post argues exactly one of three things:
  1. "We have actually built this."   - named projects, real constraints, real numbers
  2. "We will show you before you pay." - the free prototype, told as process
  3. "We think clearly about your problem." - an opinion a buyer can test

A post that is none of those is filler, and filler teaches an audience to scroll
past you.

{VOICE_RULES}

{CLAIMS_RULES}

REAL WIZCODES FACTS - the only facts you may use:

{facts_block}{stats}"""


def post_user_prompt(
    pillar: str,
    platform: str,
    fmt: str,
    slides: int,
    extra: str = "",
    *,
    archetypes: list[str] | None = None,
    region_brief: str = "",
    phrase_brief: str = "",
) -> str:
    lines = [
        f"Write one {platform} post.",
        "",
        f"Pillar: {pillar}. {PILLAR_BRIEFS.get(pillar, '')}",
        f"Platform: {PLATFORM_BRIEFS.get(platform, '')}",
    ]
    if region_brief:
        lines += ["", region_brief]
    if phrase_brief:
        lines += ["", phrase_brief]
    if extra:
        lines += ["", extra]
    if fmt == "carousel":
        lines += ["", carousel_spec(archetypes or [])]
    else:
        lines += [
            "",
            "Return a JSON object shaped like:",
            (
                '{"caption": "the post text", "hashtags": ["..."], '
                '"image_prompt": "one line describing the single image, or empty"}'
            ),
        ]
    lines += ["", "Return the JSON object on its own, with nothing before or after it."]
    return "\n".join(lines)


REGENERATE_NOTE = """\
The previous draft was rejected by an automated check. Here is what it flagged:

{reasons}

Write a fresh version that avoids those problems. Keep every claim traceable to \
the facts you were given."""
