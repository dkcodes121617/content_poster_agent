"""LinkedIn publisher: slides go out as a document, one slide as an image."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image

from platforms import linkedin as li
from platforms.base import Draft


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = str(body)

    def json(self):
        return self._body


def _cfg():
    return SimpleNamespace(
        live_linkedin_token="tok", linkedin_org_id="123", http_timeout=5,
    )


def _pngs(tmp_path, n):
    paths = []
    for i in range(n):
        p = tmp_path / f"s{i}.png"
        Image.new("RGB", (1080, 1350), (20, 40, 200)).save(p)
        paths.append(str(p))
    return paths


@pytest.fixture
def calls(monkeypatch):
    log = []
    monkeypatch.setattr(li.time, "sleep", lambda s: None)

    def post(self, url, **kw):
        log.append(("POST", url, kw.get("json")))
        if "initializeUpload" in url:
            kind = "document" if "/documents" in url else "image"
            return Resp(200, {"value": {"uploadUrl": "https://up.example/x",
                                        kind: f"urn:li:{kind}:abc"}})
        return Resp(201, {}, {"x-restli-id": "urn:li:share:9"})

    def put(self, url, **kw):
        log.append(("PUT", url, len(kw.get("data") or b"")))
        return Resp(201)

    def get(self, url, **kw):
        log.append(("GET", url, None))
        return Resp(200, {"status": "AVAILABLE"})

    monkeypatch.setattr(li.LinkedInPlatform, "_post", post)
    monkeypatch.setattr(li.LinkedInPlatform, "_put", put)
    monkeypatch.setattr(li.LinkedInPlatform, "_get", get)
    return log


def test_carousel_goes_out_as_one_pdf_document(tmp_path, calls):
    d = Draft(platform="linkedin", pillar="teach", caption="Hello",
              slides=[{"title": "How to scope an MVP"}])
    d.raw["local_images"] = _pngs(tmp_path, 3)
    r = li.LinkedInPlatform(_cfg()).publish(d)
    assert r.ok and r.external_id == "urn:li:share:9"
    assert any("/documents?action=initializeUpload" in c[1] for c in calls)
    post = next(c for c in calls if c[0] == "POST" and c[1].endswith("/posts"))[2]
    assert post["content"]["media"] == {"id": "urn:li:document:abc",
                                        "title": "How to scope an MVP"}


def test_single_slide_goes_out_as_image(tmp_path, calls):
    d = Draft(platform="linkedin", pillar="pov", caption="Hello")
    d.raw["local_images"] = _pngs(tmp_path, 1)
    r = li.LinkedInPlatform(_cfg()).publish(d)
    assert r.ok
    post = next(c for c in calls if c[0] == "POST" and c[1].endswith("/posts"))[2]
    assert post["content"]["media"]["id"] == "urn:li:image:abc"


def test_media_failure_does_not_post_text_only(tmp_path, calls, monkeypatch):
    monkeypatch.setattr(li.LinkedInPlatform, "_get",
                        lambda self, url, **kw: Resp(200, {"status": "PROCESSING_FAILED"}))
    d = Draft(platform="linkedin", pillar="teach", caption="Hello")
    d.raw["local_images"] = _pngs(tmp_path, 2)
    r = li.LinkedInPlatform(_cfg()).publish(d)
    assert not r.ok and "media" in r.error
    assert not any(c[1].endswith("/posts") for c in calls)


def test_pdf_has_one_page_per_slide(tmp_path):
    from pathlib import Path
    pdf = li.build_pdf([Path(p) for p in _pngs(tmp_path, 4)])
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 1
