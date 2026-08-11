"""Configuration for the Content Poster.

Validation asserts only what `PLATFORMS_ENABLED` actually needs. That is what
makes a blocked platform a clean skip rather than a failed run: LinkedIn is in
API review and Google Business Profile is awaiting an access grant, so both are
simply absent from the list and nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from wizcore.config import ConfigError, env_bool, env_int, env_list, env_str, load_env

AGENT_ROOT = Path(__file__).resolve().parent
load_env(AGENT_ROOT)

AGENT_NAME = "content_poster"

PLATFORM_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "facebook": ("META_PAGE_ID", "META_PAGE_ACCESS_TOKEN", "META_GRAPH_VERSION"),
    "threads": ("THREADS_ACCESS_TOKEN",),
    # The Instagram Login route (graph.instagram.com/me/media), NOT the
    # Page-linked route. It needs no META_IG_BUSINESS_ACCOUNT_ID, which is why
    # the Facebook-Instagram link restriction never blocked this.
    "instagram": ("INSTAGRAM_APP_ACCESS_TOKEN",),
    "pinterest": ("PINTEREST_TOKEN",),
    "devto": ("DEVTO_API_KEY",),
    "linkedin": ("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_ORG_ID"),
    # X and YouTube have no usable free API, so they need no credentials: the
    # agent writes the content and hands it to Telegram for a human to post.
    # They are real platforms in the calendar, not a TODO — CAMPAIGN.md §6 gives
    # X three slots a week, and content that is written but never scheduled is
    # content that never gets written.
    "x": (),
    "youtube": (),
}

# Platforms delivered by a human rather than an API. They are recorded in
# content.manual_queue so an item that scrolls past in Telegram shows up in the
# digest instead of vanishing.
MANUAL_PLATFORMS = frozenset({"x", "youtube"})

ALL_PLATFORMS = tuple(PLATFORM_REQUIREMENTS)

# Rotating token -> the Config field holding its deploy-time fallback.
_TOKEN_ATTRS = {
    "INSTAGRAM_APP_ACCESS_TOKEN": "instagram_token",
    "THREADS_ACCESS_TOKEN": "threads_token",
    "PINTEREST_TOKEN": "pinterest_token",
    "PINTEREST_REFRESH_TOKEN": "pinterest_refresh_token",
}

# Platforms that need an image URL Meta can FETCH. Meta's publish API does not
# accept a raw upload, so these cannot run without R2.
NEEDS_IMAGE_HOSTING = frozenset({"facebook", "instagram", "pinterest"})


@dataclass(frozen=True)
class Config:
    dry_run: bool = env_bool("DRY_RUN", True)
    log_level: str = env_str("LOG_LEVEL", "INFO")
    display_tz: str = env_str("DISPLAY_TZ", "Asia/Kolkata")

    database_url: str = env_str("NEON_DATABASE_URL")
    checkpoint_schema: str = env_str("LANGGRAPH_CHECKPOINT_SCHEMA", "cp_ckpt")

    site_repo: str = env_str("SITE_REPO", "dkcodes121617/wizcodes_main_website")
    site_branch: str = env_str("SITE_REPO_BRANCH", "main")
    site_read_token: str = env_str("SITE_READ_TOKEN")
    site_local_dir: str = env_str("SITE_LOCAL_DIR")

    platforms_enabled: list[str] = field(
        default_factory=lambda: env_list("PLATFORMS_ENABLED", "facebook,threads")
    )

    # ── Meta / Threads / Instagram ──
    meta_app_id: str = env_str("META_APP_ID")
    meta_app_secret: str = env_str("META_APP_SECRET")
    meta_page_id: str = env_str("META_PAGE_ID")
    meta_page_token: str = env_str("META_PAGE_ACCESS_TOKEN")
    meta_graph_version: str = env_str("META_GRAPH_VERSION", "v26.0")
    threads_token: str = env_str("THREADS_ACCESS_TOKEN")
    instagram_token: str = env_str("INSTAGRAM_APP_ACCESS_TOKEN")
    instagram_user_id: str = env_str("INSTAGRAM_USER_ID")
    pinterest_token: str = env_str("PINTEREST_TOKEN")
    pinterest_board_id: str = env_str("PINTEREST_BOARD_ID")
    # Pinterest has no permanent token. The access token lasts 30 days and the
    # continuous refresh token lasts 60 but is refreshable INDEFINITELY, so the
    # refresh token is what makes this effectively permanent — the same shape as
    # Instagram's 60-day token. Without it, the only alternative is a dashboard
    # test token, which expires after 24 hours and cannot be refreshed at all.
    pinterest_app_id: str = env_str("PINTEREST_APP_ID")
    pinterest_app_secret: str = env_str("PINTEREST_APP_SECRET")
    pinterest_refresh_token: str = env_str("PINTEREST_REFRESH_TOKEN")
    devto_api_key: str = env_str("DEVTO_API_KEY")
    linkedin_token: str = env_str("LINKEDIN_ACCESS_TOKEN")
    linkedin_org_id: str = env_str("LINKEDIN_ORG_ID")

    # ── R2 (Meta fetches images by URL; it never accepts an upload) ──
    r2_access_key_id: str = env_str("R2_ACCESS_KEY_ID")
    r2_secret_access_key: str = env_str("R2_SECRET_ACCESS_KEY")
    r2_bucket_endpoint: str = env_str("R2_BUCKET_ENDPOINT")
    r2_bucket_name: str = env_str("R2_BUCKET_NAME")
    r2_public_base_url: str = env_str("R2_PUBLIC_BASE_URL")
    r2_key_prefix: str = env_str("R2_KEY_PREFIX", "social")

    # ── LLM ──
    # Measured, not guessed: opus-4-8 produced 0 banned phrases and, critically,
    # **0 invented figures**. sonnet-5 invented one, which is disqualifying for a
    # job where every number must trace back to the site repo.
    voice_model: str = env_str("ANTHROPIC_VOICE_MODEL", "claude-opus-4-8")
    groq_api_key: str = env_str("GROQ_API_KEY")
    huggingface_token: str = env_str("HUGGINGFACE_TOKEN")
    flux_model: str = env_str("FLUX_MODEL", "black-forest-labs/FLUX.1-schnell")
    use_flux_backgrounds: bool = env_bool("USE_FLUX_BACKGROUNDS", False)

    # ── campaign ──
    brand_font_path: str = env_str("BRAND_FONT_PATH", str(AGENT_ROOT / "assets"))
    max_regenerations: int = env_int("MAX_REGENERATIONS", 2)
    repetition_lookback: int = env_int("REPETITION_LOOKBACK", 60)
    repetition_threshold: float = float(env_str("REPETITION_THRESHOLD", "0.86"))
    jitter_minutes: int = env_int("JITTER_MINUTES", 25)

    # ── phasing (CONTENT_SYSTEM.md §6) ──
    # ISO date the campaign began. Blank means steady state, which is the safe
    # default: an unset value on a system already running for months must not
    # silently withhold two thirds of the pillars.
    campaign_start_date: str = env_str("CAMPAIGN_START_DATE")
    # Extra slots for the first N weeks, so an empty profile fills up fast. 0
    # disables it. Weighted toward Pinterest, which is a search index and does
    # not penalise volume - see the boost block in campaign/calendar.py.
    boost_weeks: int = env_int("BOOST_WEEKS", 3)

    # ── visual variety (§3) ──
    # Off means the original single deck shape, for comparing against.
    visual_variety: bool = env_bool("VISUAL_VARIETY", True)
    # Charts are only offered when the curated stats file has usable figures.
    # Set false to keep them off entirely regardless.
    charts_enabled: bool = env_bool("CHARTS_ENABLED", True)
    # Reuse the site's brand SVGs on slides (§2). Needs SITE_READ_TOKEN.
    site_artwork: bool = env_bool("SITE_ARTWORK", True)

    # ── search phrases (campaign/keywords.py) ──
    # The opening line of a post is its URL slug on LinkedIn and dev.to, so it
    # is written to carry a phrase people actually search for.
    seo_phrases: bool = env_bool("SEO_PHRASES", True)
    # Reject a draft whose opening line does not carry the phrase. Off by
    # default: on platforms where the first line is not a URL this is a
    # preference, and a preference should not cost a slot.
    seo_phrase_required: list[str] = field(
        default_factory=lambda: env_list("SEO_PHRASE_REQUIRED", "linkedin,devto")
    )

    # ── geography (§4) ──
    geo_targeting: bool = env_bool("GEO_TARGETING", True)
    # Regions in rotation. Removing one is an env edit, not a code change.
    regions_enabled: list[str] = field(
        default_factory=lambda: env_list("REGIONS_ENABLED", "US,GB,EU")
    )

    # ── capacity + backfill (§5) ──
    # When false the fixed weekly calendar governs volume on its own, which is
    # correct until a platform actually unlocks.
    capacity_scheduling: bool = env_bool("CAPACITY_SCHEDULING", False)
    backfill_enabled: bool = env_bool("BACKFILL_ENABLED", False)
    backfill_per_run: int = env_int("BACKFILL_PER_RUN", 1)

    # ── trend intelligence (TRENDS.md) ──
    trends_enabled: bool = env_bool("TRENDS_ENABLED", True)
    tavily_api_key: str = env_str("TAVILY_API_KEY")
    # Same model the Lead Finder triages with. Named identically on purpose:
    # both agents share one Groq account and one free-tier pool, so budgeting
    # them as one thing requires them to be configured as one thing.
    groq_classify_model: str = env_str("GROQ_CLASSIFY_MODEL", "llama-3.3-70b-versatile")
    # "proxy" routes EVERY LLM call through the Claude proxy — one credential,
    # one vendor, one place the quirks live. "mixed" restores Groq for the
    # high-volume triage jobs. See trends/score.py for the measured trade.
    llm_provider: str = env_str("LLM_PROVIDER", "proxy").lower()
    # Cheap, fast model for classification-shaped work on the proxy. Measured:
    # haiku answered a batch in 4.2s against opus-5's 10.6s and every model
    # agreed on the labels, so size buys nothing here.
    classify_model: str = env_str("ANTHROPIC_FALLBACK_CLASSIFY_MODEL", "claude-haiku-4.5")
    # Harvest knobs. Deliberately conservative: this runs alongside the Lead
    # Finder's piggyback, which supplies most of the volume for free.
    trend_github_days: int = env_int("TREND_GITHUB_DAYS", 14)
    trend_github_min_stars: int = env_int("TREND_GITHUB_MIN_STARS", 300)
    trend_hn_min_points: int = env_int("TREND_HN_MIN_POINTS", 80)
    trend_devto_days: int = env_int("TREND_DEVTO_DAYS", 2)
    trend_news_per_query: int = env_int("TREND_NEWS_PER_QUERY", 12)
    trend_news_queries: list[str] = field(
        default_factory=lambda: env_list(
            "TREND_NEWS_QUERIES",
            "AI tools for small business,small business software,"
            "AI automation for business,website cost,app store policy change",
        )
    )
    # Scoring. `trend_min_relevance` is the single most important number here:
    # raise it and the agent posts less but better. 65 is deliberately high —
    # rejecting is the normal outcome (TRENDS.md §4).
    trend_score_batch: int = env_int("TREND_SCORE_BATCH", 40)
    trend_min_relevance: int = env_int("TREND_MIN_RELEVANCE", 65)
    trend_velocity_weight: int = env_int("TREND_VELOCITY_WEIGHT", 6)
    trend_velocity_cap: int = env_int("TREND_VELOCITY_CAP", 3)
    # Safety. Nothing under the cool-off; breaking stories get corrected.
    trend_cool_off_hours: int = env_int("TREND_COOL_OFF_HOURS", 6)
    # Verification. Two distinct publishers before a figure may be asserted.
    trend_min_sources: int = env_int("TREND_MIN_SOURCES", 2)
    trend_max_sources: int = env_int("TREND_MAX_SOURCES", 5)
    trend_time_range: str = env_str("TREND_TIME_RANGE", "week")
    trend_verify_per_run: int = env_int("TREND_VERIFY_PER_RUN", 6)
    # Angle synthesis — the only step that uses the expensive model.
    trend_angles_per_run: int = env_int("TREND_ANGLES_PER_RUN", 3)
    trend_angle_attempts: int = env_int("TREND_ANGLE_ATTEMPTS", 2)
    trend_angle_ttl_hours: int = env_int("TREND_ANGLE_TTL_HOURS", 48)
    trend_item_retention_days: int = env_int("TREND_ITEM_RETENTION_DAYS", 21)

    budget_caps: dict[str, float] = field(
        default_factory=lambda: {
            "claude_proxy": env_int("BUDGET_CLAUDE_KTOKENS", 300),
            "huggingface": env_int("BUDGET_FLUX_IMAGES", 20),
            "groq": env_int("BUDGET_GROQ_CALLS", 200),
            # Tavily bills per search. Capped separately so trend verification
            # can never eat the Outreach agent's share of the same account.
            "tavily": env_int("BUDGET_TAVILY_SEARCHES", 40),
        }
    )
    http_timeout: int = env_int("HTTP_TIMEOUT", 45)

    def active_platforms(self) -> list[str]:
        return [p for p in self.platforms_enabled if p in PLATFORM_REQUIREMENTS]

    def start_date(self):
        """`CAMPAIGN_START_DATE` as a date, or None.

        None means steady state. Returning None for an unparseable value as well
        as an empty one is deliberate — `validate()` reports the bad value, and
        between those two points a run should behave as though phasing is simply
        off rather than crash on a date format.
        """
        from datetime import date

        if not self.campaign_start_date:
            return None
        try:
            return date.fromisoformat(self.campaign_start_date.strip())
        except ValueError:
            return None

    def token(self, name: str) -> str:
        """The freshest value for a rotating token: database, then environment.

        Rotating tokens (Instagram, Threads, Pinterest) live in
        `core.agent_credentials` because a Modal container cannot write its own
        secret — so a refreshed token had nowhere to persist and the weekly
        refresh achieved nothing. Reading through here is what makes automatic
        rotation actually take effect.

        Falls back to the environment, so this works on a fresh database, before
        the first rotation, and in local development.
        """
        from wizcore.db import credentials

        return credentials.get(name, self.database_url) or getattr(
            self, _TOKEN_ATTRS.get(name, ""), ""
        )

    # ── live token accessors — use these, not the raw fields ──
    @property
    def live_instagram_token(self) -> str:
        return self.token("INSTAGRAM_APP_ACCESS_TOKEN")

    @property
    def live_threads_token(self) -> str:
        return self.token("THREADS_ACCESS_TOKEN")

    @property
    def live_pinterest_token(self) -> str:
        return self.token("PINTEREST_TOKEN")

    def has_image_hosting(self) -> bool:
        return bool(
            self.r2_access_key_id
            and self.r2_secret_access_key
            and self.r2_bucket_endpoint
            and self.r2_bucket_name
            and self.r2_public_base_url
        )

    def validate(self) -> None:
        problems: list[str] = []
        if not self.database_url:
            problems.append("NEON_DATABASE_URL is not set")
        unknown = [p for p in self.platforms_enabled if p not in PLATFORM_REQUIREMENTS]
        if unknown:
            problems.append(
                f"PLATFORMS_ENABLED names unknown platform(s): {', '.join(unknown)}. "
                f"Known: {', '.join(ALL_PLATFORMS)}"
            )
        if not self.active_platforms():
            problems.append("PLATFORMS_ENABLED is empty - the run would publish nothing")

        for platform in self.active_platforms():
            for key in PLATFORM_REQUIREMENTS[platform]:
                if not env_str(key):
                    problems.append(f"platform '{platform}' needs {key}, which is not set")

        if set(self.active_platforms()) & NEEDS_IMAGE_HOSTING and not self.has_image_hosting():
            problems.append(
                "facebook/instagram/pinterest publish by URL - Meta FETCHES the image "
                "rather than accepting an upload - so R2_* must all be set"
            )
        if not self.site_read_token and not self.site_local_dir:
            problems.append(
                "SITE_READ_TOKEN is not set and SITE_LOCAL_DIR is empty - grounding "
                "facts cannot be built, and an ungrounded run must not publish"
            )
        if self.campaign_start_date and not self.start_date():
            problems.append(
                f"CAMPAIGN_START_DATE={self.campaign_start_date!r} is not an ISO date "
                "(YYYY-MM-DD). Leave it blank for steady state."
            )
        unknown_regions = [
            r for r in self.regions_enabled if r.upper() not in ("US", "GB", "EU")
        ]
        if unknown_regions:
            problems.append(
                f"REGIONS_ENABLED names unknown region(s): {', '.join(unknown_regions)}. "
                "Known: US, GB, EU"
            )
        if problems:
            raise ConfigError(
                "content_poster configuration is not runnable:\n  - " + "\n  - ".join(problems)
            )


CONFIG = Config()
