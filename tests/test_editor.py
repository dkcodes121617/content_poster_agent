"""The editorial gate, the search-phrase scope and LinkedIn token rotation."""
import dataclasses

from campaign import deck as deck_mod
from config import CONFIG
from validators import editor


def test_parse_passes_at_the_threshold_and_fails_below():
    good = editor.parse({"hook": 8, "value": 8, "specificity": 7, "originality": 7,
                         "overall": 7, "problems": [], "revision": ""}, 7)
    assert good.ok and good.overall == 7
    weak = editor.parse({"overall": 4, "problems": ["reads like sales copy"],
                         "revision": "Open on the client's problem."}, 7)
    assert not weak.ok
    reasons = weak.reasons()
    assert reasons[0].startswith("editor scored it 4/10")
    assert any("sales copy" in r for r in reasons)
    assert any("Open on the client's problem." in r for r in reasons)


def test_parse_clamps_and_coerces_scores():
    r = editor.parse({"overall": "9.6", "hook": 14, "value": -3}, 7)
    assert r.overall == 10 and r.scores["hook"] == 10 and r.scores["value"] == 0


def test_parse_rejects_a_reply_without_an_overall_score():
    try:
        editor.parse({"hook": 8}, 7)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


class _Broken:
    def complete(self, **_kw):
        raise RuntimeError("proxy down")


class _Scores:
    def __init__(self, overall):
        self.overall = overall

    def complete(self, **_kw):
        return ('```json\n{"hook": 6, "value": 6, "specificity": 6, "originality": 6, '
                f'"overall": {self.overall}, "problems": ["generic"], "revision": "x"}}\n```')


def test_scores_survive_a_malformed_reply():
    # An unescaped quote inside "problems" breaks the object; the extractor then
    # returns the problems ARRAY. The verdict must still come from the scores.
    raw = ('Here is my review:\n{"hook": 4, "value": 3, "specificity": 2, '
           '"originality": 3, "overall": 3, "problems": ["opens with "If you\'re hunting"", '
           '"no insight"], "revision": "Lead with the client problem."}')

    class _Raw:
        def complete(self, **_kw):
            return raw

    r = editor.review(_Raw(), CONFIG, platform="threads", pillar="teach", caption="x")
    assert not r.skipped and not r.ok and r.overall == 3
    assert r.revision == "Lead with the client problem."


def test_a_failed_editor_call_lets_the_draft_through():
    r = editor.review(_Broken(), CONFIG, platform="threads", pillar="teach", caption="x")
    assert r.ok and r.skipped


def test_review_reads_a_fenced_reply_and_applies_the_threshold():
    cfg = dataclasses.replace(CONFIG, editor_enabled=True, editor_min_score=7)
    assert not editor.review(_Scores(5), cfg, platform="threads", pillar="teach", caption="x").ok
    assert editor.review(_Scores(8), cfg, platform="threads", pillar="teach", caption="x").ok


def test_editor_can_be_switched_off():
    cfg = dataclasses.replace(CONFIG, editor_enabled=False)
    assert editor.review(_Broken(), cfg, platform="threads", pillar="teach", caption="x").ok


class _Snap:
    class _P:
        def __init__(self, name, client=""):
            self.name, self.client = name, client

    projects = [_P("CuePilot", "LeoTech"), _P("Noorly", "Artem")]


def test_unanchored_studio_stories_are_rejected():
    from validators import anecdote

    for text in (
        "A client asked us to add an 'Industry' field to their CRM.",
        "We added a Priority field to every lead. Sales ignored it.",
        "One of our clients wanted dashboards before data.",
        "One client added Industry to route leads. Another added Budget.",
        "A client added a Budget field and never used it.",
    ):
        assert anecdote.check(text, _Snap()), text


def test_anchored_stories_and_scenarios_pass():
    from validators import anecdote

    assert not anecdote.check("We learned this building CuePilot for LeoTech.", _Snap())
    assert not anecdote.check("A team adds a Priority field to every lead.", _Snap())
    assert not anecdote.check("Most teams add custom fields the moment someone asks.", _Snap())
    # Generic advice that merely mentions "a client" is not a story.
    assert not anecdote.check("Show a client the prototype before you quote.", _Snap())


def test_search_phrases_only_go_to_search_platforms():
    cfg = dataclasses.replace(CONFIG, seo_phrases=True,
                              seo_phrase_platforms=["pinterest", "devto"])
    assert deck_mod._wants_phrase(cfg, "pinterest")
    assert deck_mod._wants_phrase(cfg, "devto")
    for platform in ("threads", "instagram", "linkedin"):
        assert not deck_mod._wants_phrase(cfg, platform)
    assert not deck_mod._wants_phrase(dataclasses.replace(cfg, seo_phrases=False), "pinterest")


def test_linkedin_rotation_reports_a_missing_refresh_token(monkeypatch):
    from platforms import tokens

    monkeypatch.setattr(tokens.credentials, "get", lambda *a, **k: "")
    cfg = dataclasses.replace(CONFIG, linkedin_refresh_token="", linkedin_client_id="id",
                              linkedin_client_secret="s")
    out = tokens.refresh_linkedin(cfg)
    assert out["ok"] is False and "linkedin_auth.py" in out["error"]


def test_linkedin_rotation_stores_the_new_token(monkeypatch):
    from platforms import tokens

    stored = {}
    monkeypatch.setattr(tokens.credentials, "get", lambda *a, **k: "refresh-abc")
    monkeypatch.setattr(tokens.credentials, "put",
                        lambda name, value, *a, **k: stored.setdefault(name, value) or True)

    class _Resp:
        status_code = 200

        def json(self):
            return {"access_token": "new-access", "expires_in": 5184000}

    monkeypatch.setattr(tokens.requests, "post", lambda *a, **k: _Resp())
    cfg = dataclasses.replace(CONFIG, linkedin_client_id="id", linkedin_client_secret="s")
    out = tokens.refresh_linkedin(cfg)
    assert out["ok"] and stored["LINKEDIN_ACCESS_TOKEN"] == "new-access"
    assert out["expires_in_days"] == 60
