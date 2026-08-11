"""US / UK / EU targeting — CONTENT_SYSTEM.md §4.

Everything was geography-blind: one query bank, one hashtag set, one spelling,
one posting time. For a studio in Ahmedabad selling to buyers in three
continents, that is not neutral — it reads as "somewhere else" to all three.

Four things vary by region, and only one of them is a parameter on an API call:

  **Query vocabulary**, which matters more than the geo parameter. A US small
  business owner searches "cost to build an app"; a UK one searches "app
  development agency near me"; an EU buyer starts from GDPR. The banks below are
  written per region rather than translated, because a translated query finds
  the same articles in a different accent.

  **Hashtags.** `#SmallBusinessUK`, `#SMBTech` and `#Mittelstand` are three
  different audiences. One global bank is why agency accounts get no regional
  reach.

  **Spelling and idiom.** en-GB for UK/IE/EU-facing posts, en-US for US. Cheap
  to do, and getting it wrong is a small constant signal that the account is not
  local.

  **Timing.** A UK-targeted post should land in UK morning, not US morning.

## Rotation, not segmentation

One region *leads* each day and the others are not excluded. Splitting the feed
into three regional streams would third the volume each audience sees, and none
of these accounts has the reach to spend that. The rotation is seeded by date,
so it is stable within a day and even across a fortnight.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date

from campaign.calendar import today_ist


@dataclass(frozen=True)
class Region:
    code: str
    name: str
    locale: str                      # en-GB | en-US
    # Google News takes gl/ceid; a blank `gl` means "no geo restriction".
    news_gl: str = ""
    news_ceid: str = ""
    # Tavily takes include_domains. Regional outlets, not national broadsheets:
    # the goal is trade press a business owner in that market actually reads.
    prefer_domains: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    hashtags: tuple[str, ...] = ()
    # IST hour at which a post lands in this region's morning. The agent runs on
    # Asia/Kolkata, so every window is expressed there rather than converted at
    # read time in three places.
    windows_ist: tuple[int, ...] = ()
    spelling_note: str = ""
    audience_note: str = ""
    _idioms: dict[str, str] = field(default_factory=dict)


US = Region(
    code="US",
    name="United States",
    locale="en-US",
    news_gl="US",
    news_ceid="US:en",
    prefer_domains=("techcrunch.com", "theverge.com", "inc.com", "entrepreneur.com"),
    queries=(
        "cost to build an app",
        "small business software costs",
        "hiring a development agency",
        "AI tools for small business",
        "custom software vs off the shelf",
        "app development quote",
    ),
    hashtags=(
        "SmallBusiness", "SMBTech", "StartupLife", "BuildInPublic", "TechForBusiness",
        "SmallBizTech", "FounderLife", "BusinessAutomation", "SaaS", "WebDevelopment",
        "AppDevelopment", "DigitalTransformation", "Bootstrapped", "TechStartup",
    ),
    # 18:30 IST = 09:00 ET. CAMPAIGN.md already noted this; it is now a per-region
    # window rather than a comment.
    windows_ist=(18, 19, 20, 21),
    spelling_note="US spelling: optimize, personalize, analyze, color, center.",
    audience_note=(
        "American small-business owners and founders. Direct, outcome-first. "
        "State the benefit in the first line; they will not wait for it."
    ),
)

UK = Region(
    code="GB",
    name="United Kingdom & Ireland",
    locale="en-GB",
    news_gl="GB",
    news_ceid="GB:en",
    prefer_domains=("theregister.com", "bbc.co.uk", "computerweekly.com", "uktech.news"),
    queries=(
        "app development agency near me",
        "website redesign cost UK",
        "small business digital transformation UK",
        "software development quote UK",
        "outsourcing development UK small business",
        "Making Tax Digital software",
    ),
    hashtags=(
        "SmallBusinessUK", "UKBusiness", "SMEUK", "UKTech", "BusinessGrowthUK",
        "UKSmallBiz", "BritishBusiness", "SMESupport", "UKStartups", "WebDesignUK",
        "AppDevelopmentUK", "DigitalUK", "TechUK", "BusinessUK",
    ),
    # 13:30 IST = 09:00 BST.
    windows_ist=(13, 14, 15, 16),
    spelling_note="British spelling: optimise, personalise, analyse, colour, centre.",
    audience_note=(
        "UK and Irish SME owners. Understated. Overclaiming reads as a sales "
        "pitch; a plain sentence with a real number reads as competence."
    ),
)

EU = Region(
    code="EU",
    name="Europe",
    locale="en-GB",
    # Google News has no pan-EU edition. Ireland's English-language edition is
    # the closest single feed that surfaces EU regulatory news in English,
    # which is what this region's buyers actually care about.
    news_gl="IE",
    news_ceid="IE:en",
    prefer_domains=("euractiv.com", "sifted.eu", "tech.eu", "heise.de"),
    queries=(
        "GDPR compliant software development",
        "EU AI Act small business",
        "Mittelstand digitalisation",
        "European SME software costs",
        "data residency EU SaaS",
        "e-invoicing mandate software",
    ),
    hashtags=(
        "Mittelstand", "EUTech", "GDPR", "EuropeanBusiness", "DigitalEurope",
        "EUStartups", "Digitalisierung", "TechEurope", "SMEEurope", "DataPrivacy",
        "EuropeanTech", "CloudEurope", "AIAct", "Innovation",
    ),
    # 12:30 IST = 09:00 CET.
    windows_ist=(12, 13, 14, 15),
    spelling_note="British spelling: optimise, personalise, analyse, colour, centre.",
    audience_note=(
        "European SME owners and operations leads. Compliance and data "
        "residency are first-order concerns here, not footnotes. Say where "
        "data lives before saying how fast the thing is."
    ),
)

REGIONS: tuple[Region, ...] = (US, UK, EU)
BY_CODE: dict[str, Region] = {r.code: r for r in REGIONS}
DEFAULT = US


def get(code: str) -> Region:
    return BY_CODE.get((code or "").upper(), DEFAULT)


def leading(day: date | None = None) -> Region:
    """The region leading today.

    Seeded by the ISO week and weekday rather than random, so the rotation is
    stable within a day (a retry must not target a different market than the
    first attempt) and even over a fortnight rather than clustering.
    """
    day = day or today_ist()
    return REGIONS[(day.toordinal()) % len(REGIONS)]


def for_slot(platform: str, hour_ist: int, day: date | None = None) -> Region:
    """The region a slot at this hour is aimed at.

    The window is the strong signal: a post landing at 13:00 IST is landing in
    UK morning whatever the rotation says, and pretending otherwise would mean
    writing US idiom for a British audience at breakfast. The day rotation only
    breaks ties between regions whose windows overlap, which US and UK do.
    """
    candidates = [r for r in REGIONS if hour_ist in r.windows_ist]
    if not candidates:
        return leading(day)
    if len(candidates) == 1:
        return candidates[0]
    day = day or today_ist()
    rng = random.Random(f"{day.isoformat()}:{platform}:{hour_ist}")
    return rng.choice(candidates)


# Tags that work anywhere, used only to top up a request the regional bank
# cannot fill on its own. Instagram wants 8 to 12 and the first version of the
# banks held 5, so every Instagram post came back short and was rejected by the
# platform gate — a regional feature breaking a platform requirement.
_GLOBAL_TOPUP = (
    "SoftwareDevelopment", "CustomSoftware", "ProductDesign", "UXDesign",
    "Automation", "AItools", "NoCode", "TechConsulting", "MVP", "Prototyping",
)


def hashtags_for(region: Region, platform: str, pillar: str, count: int,
                 day: date | None = None) -> list[str]:
    """A rotated subset of this region's bank, topped up if it is short.

    Rotated rather than fixed: the same three tags on every post is a pattern
    the platforms recognise, and the point of a bank is that it is bigger than
    what any one post uses.

    The regional tags always come first. Topping up adds reach without diluting
    the signal that made the bank regional in the first place.
    """
    if count <= 0:
        return []
    day = day or today_ist()
    rng = random.Random(f"{day.isoformat()}:{platform}:{pillar}:{region.code}")
    bank = list(region.hashtags)
    rng.shuffle(bank)
    if len(bank) < count:
        topup = [t for t in _GLOBAL_TOPUP if t not in bank]
        rng.shuffle(topup)
        bank += topup
    return bank[:count]


def brief(region: Region) -> str:
    """The regional block for a writing prompt."""
    return (
        f"AUDIENCE REGION: {region.name} ({region.locale}).\n"
        f"  {region.audience_note}\n"
        f"  {region.spelling_note}\n"
        "  Write for a reader in that market. Do not mention the region by name "
        "unless it is genuinely part of the story."
    )


def news_params(region: Region) -> dict:
    """Google News RSS parameters for this region."""
    params = {"hl": region.locale, "gl": region.news_gl, "ceid": region.news_ceid}
    return {k: v for k, v in params.items() if v}
