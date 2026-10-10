"""MCP integration tests with a fake visible browser; no live site scraping."""
import asyncio

import multimall.server as server


class FakePool:
    async def search(self, platform, query, limit):
        if platform != "jd":
            return {"status": "no_extractable_products", "products": []}
        return {"status": "observed", "products": [{
            "platform": "jd",
            "url": "https://item.jd.com/111.html",
            "title": "ESP32-S3 N16R8 AMOLED",
            "displayed_price_yuan": "139",
            "condition": "new",
            "source": "browser_observation",
        }]}

    async def visible_reviews(self, url, limit=20):
        return {
            "status": "observed",
            "reviews": [
                {"text": "屏幕破损且无法使用，售后不管", "source_url": url},
                {"text": "不错，很稳定，安装方便", "source_url": url}
            ],
            "page_url": url,
        }


def test_one_call_automatically_adds_optional_review_evidence(monkeypatch):
    monkeypatch.setattr(server, "browser", FakePool())
    r = asyncio.run(server.research_purchase(
        "ESP32-S3", budget_yuan=200, inspect_reviews_top_k=1))
    assert r["status"] == "provisional_results"
    assert len(r["shortlist"]) == 1
    assert r["shortlist"][0]["review_summary"]["quality_score"] is None
    assert r["shortlist"][0]["review_summary"]["issue_topics"]["delivery_damage"] == 1
    assert r["shortlist"][0]["review_fetch_status"] == "observed"


def test_browser_error_must_not_create_fake_reviews(monkeypatch):
    class ErrorPool(FakePool):
        async def visible_reviews(self, url, limit=20):
            return {"status": "no_visible_reviews", "reviews": []}
    monkeypatch.setattr(server, "browser", ErrorPool())
    r = asyncio.run(server.research_purchase(
        "ESP32-S3", inspect_reviews_top_k=1))
    assert r["shortlist"][0]["review_summary"]["sample_size"] == 0
    assert r["shortlist"][0]["review_fetch_status"] == "no_visible_reviews"
