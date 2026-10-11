import asyncio
import json

import pytest

from multimall.intelligence import (
    analyze_reviews, match_same_products, recommend_products,
)
from multimall.orchestration import search_all_platforms, research_purchase


def offer(platform="jd", url="https://item.jd.com/123.html", **kwargs):
    base = {
        "platform": platform, "url": url,
        "title": "ESP32-S3 N16R8 1.75 AMOLED",
        "displayed_price_yuan": "129",
        "condition": "new", "brand": "ESPRESSIF", "model": "ESP32-S3",
        "specification": "N16R8 1.75 AMOLED",
    }
    base.update(kwargs)
    return base


def test_exact_structured_match_across_platforms():
    a = offer()
    b = offer(platform="taobao", url="https://item.taobao.com/item.htm?id=24",
              brand="espressif", model="ESP32 S3", specification="N16R8 1.75-AMOLED")
    result = match_same_products([a, b])
    assert len(result["candidate_groups"]) == 1
    assert len(result["candidate_groups"][0]["offers"]) == 2
    assert "manual_confirmation_required" in result["candidate_groups"][0]["match_status"]


def test_similar_title_different_hardware_not_grouped():
    a = offer()
    b = offer(platform="taobao", url="https://item.taobao.com/item.htm?id=25",
              model="ESP32-S3", specification="N8R8 1.75 AMOLED")
    result = match_same_products([a, b])
    assert not result["candidate_groups"]
    assert len(result["singletons"]) == 2


def test_missing_product_identity_must_not_claim_match():
    rows = [
        offer(model="", title="ESP32-S3 same listing"),
        offer(platform="taobao", url="https://item.taobao.com/item.htm?id=25",
              model="", title="ESP32-S3 same listing"),
    ]
    result = match_same_products(rows)
    assert not result["candidate_groups"]
    assert len(result["unmatched"]) == 2


def test_reviews_dont_produce_quality_score_and_handle_negation():
    result = analyze_reviews([
        {"text": "已经用了一周，没有故障，好用", "rating": 5},
        {"text": "有故障，无法使用，售后不管", "rating": 1},
        {"text": "这个是假货，型号不对", "rating": 1},
    ])
    assert result["quality_score"] is None
    assert result["sample_size"] == 3
    assert result["issue_topics"]["function_failure"] == 1
    assert result["issue_topics"]["counterfeit_concern"] == 1
    assert result["mean_rating_from_supplied_samples"] == 2.33


def test_no_reviews_returns_not_assessed():
    r = analyze_reviews([])
    assert r["status"] == "no_review_evidence"
    assert r["quality_score"] is None


def test_provisional_ranking_does_not_claim_quality_or_verified_sku():
    rows = [
        offer(displayed_price_yuan="159"),
        offer(platform="taobao", url="https://item.taobao.com/item.htm?id=25",
              displayed_price_yuan="129"),
    ]
    r = recommend_products(rows, budget_yuan=160)
    assert r["status"] == "provisional_shortlist"
    assert r["recommendations"][0]["platform"] == "taobao"
    assert r["recommendations"][0]["same_sku_confirmed"] is False
    assert r["recommendations"][0]["quality_evidence"] == "missing_or_unverified"


def test_shipping_coupon_estimate_exceeds_budget_and_excluded():
    r = recommend_products([
        offer(displayed_price_yuan="100", shipping_yuan=20, coupon_yuan=0),
        offer(platform="taobao", url="https://item.taobao.com/item.htm?id=25",
              displayed_price_yuan="100", shipping_yuan=0, coupon_yuan=10),
    ], budget_yuan=110)
    assert r["total_eligible"] == 1
    assert r["recommendations"][0]["estimated_total_yuan"] == "90"
    assert r["excluded"][0]["reasons"] == ["含运费估算价超预算"]


def test_invalid_merchant_url_cannot_enter_recommendation():
    r = recommend_products([offer(url="https://jd.com.attacker.example/evil")])
    assert r["status"] == "insufficient_evidence"
    assert len(r["excluded"]) == 1


def test_no_used_without_opt_in_and_meituan_location():
    row = offer(platform="xianyu", url="https://www.goofish.com/item?id=2", condition="used")
    r = recommend_products([row])
    assert not r["recommendations"]
    assert recommend_products([row], include_secondhand=True)["recommendations"]

    local = offer(platform="meituan", url="https://www.meituan.com/deal/1234")
    assert not recommend_products([local])["recommendations"]
    assert recommend_products([local], location="广州")["recommendations"]


def test_platform_search_is_concurrent_and_keeps_restricted_results():
    active = 0
    maximum = 0

    async def provider(p, q, n):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.02)
        active -= 1
        if p == "pdd":
            return {"status": "manual_search_required", "products": [],
                    "reason": "需用户登录"}
        urls = {
            "jd": "https://item.jd.com/123.html",
            "taobao": "https://item.taobao.com/item.htm?id=25",
        }
        return {"status": "observed", "products": [offer(platform=p, url=urls[p])]}

    result = asyncio.run(search_all_platforms(provider, "ESP32-S3", ["jd", "taobao", "pdd"]))
    assert maximum == 2
    assert result["status"] == "partial"
    assert result["observed_platforms"] == ["jd", "taobao"]
    assert result["limited_platforms"] == ["pdd"]
    assert result["products_count"] == 2


def test_provider_failure_does_not_fabricate_results():
    async def provider(p, q, n):
        if p == "jd":
            raise RuntimeError("blocked login")
        return {"status": "observed", "products": [
            offer(platform="jd", url="https://item.jd.com/123.html")]}

    r = asyncio.run(search_all_platforms(provider, "screen", ["jd", "taobao"]))
    assert r["products_count"] == 0
    assert r["status"] == "no_verified_search_results"
    assert r["per_platform"][0]["status"] == "error"
    assert r["per_platform"][1]["rejected_records"] == 1


def test_all_missing_must_not_issue_shortlist():
    async def provider(p, q, n):
        return {"status": "no_extractable_products", "products": []}
    r = asyncio.run(research_purchase(provider, "ESP32-S3"))
    assert r["status"] == "needs_more_evidence"
    assert r["shortlist"] == []


def test_one_call_research_returns_provisional_shortlist():
    async def provider(p, q, n):
        if p == "jd":
            return {"status": "observed", "products": [offer()]}
        return {"status": "no_extractable_products", "products": []}
    r = asyncio.run(research_purchase(provider, "ESP32-S3"))
    assert r["status"] == "provisional_results"
    assert len(r["shortlist"]) == 1
    assert r["quality"] == "not_assessed_no_verified_reviews"


def test_invalid_platform_and_bounds_rejected():
    async def p(a, b, c):
        return {"status": "observed", "products": []}
    with pytest.raises(ValueError):
        asyncio.run(search_all_platforms(p, "item", ["jd", "unknown"]))
    with pytest.raises(ValueError):
        asyncio.run(search_all_platforms(p, "", ["jd"]))
    with pytest.raises(ValueError):
        analyze_reviews([{}] * 301)


def test_source_unverified_not_cloaked_as_real_checkout():
    r = recommend_products([offer(price_status="checkout_verified")])
    assert "结算页核实" in r["warnings"][2]
    assert r["recommendations"][0]["same_sku_confirmed"] is False


def test_review_trace_dedup_and_later_failure():
    rows = [{"text": "开始没有故障，后来故障死机", "source_url": "https://item.jd.com/123.html", "observed_at_utc": "2026-10-11T01:00:00Z"}]*2
    result = analyze_reviews(rows)
    assert result['sample_size'] == 1
    assert result['duplicate_snippets_removed'] == 1
    assert result['risk_entries'][0]['evidence_ids'] == [result['review_evidence'][0]['evidence_id']]
    assert result['review_evidence'][0]['text'] == rows[0]['text']
    assert result['quality_score'] is None


def test_pack_and_product_form_prevent_false_merge():
    for changes in ({'pack_count':2}, {'product_form':'bare_display'}, {'unit':'套'}):
        rows = [offer(pack_count=1, product_form='development_board', unit='个'), offer(url='https://item.jd.com/124.html', pack_count=1, product_form='development_board', unit='个') | changes]
        assert not match_same_products(rows)['candidate_groups']


def test_board_research_excludes_explicit_digital_resources_and_cases():
    async def provider(platform,query,limit):
        return {'status':'observed','products':[offer(title='ESP32-S3 AMOLED 开发板外壳'),offer(url='https://item.jd.com/124.html',title='软件资源分享ESP32-S3 AMOLED开发板'),offer(url='https://item.jd.com/125.html',title='ESP32-S3 AMOLED开发板') ]}
    result=asyncio.run(research_purchase(provider,'ESP32-S3 AMOLED开发板',['jd']))
    assert len(result['intent_excluded']) == 2
    assert len(result['shortlist']) == 1
    assert result['shortlist'][0]['url'].endswith('/125.html')


def test_mouse_research_excludes_receiver_but_keeps_mouse_with_receiver():
    async def provider(platform,query,limit):
        return {'status':'observed','products':[offer(title='罗技M185无线鼠标接收器'),offer(url='https://item.jd.com/124.html',title='罗技M185无线鼠标带接收器')]}
    result=asyncio.run(research_purchase(provider,'罗技M185无线鼠标',['jd']))
    assert len(result['intent_excluded']) == 1
    assert len(result['shortlist']) == 1


def test_mouse_receiver_word_does_not_remove_complete_or_receiver_missing_mouse():
    async def provider(platform,query,limit):
        return {'status':'observed','products':[offer(title='罗技 M185 无线鼠标 带无线2.4G接收器'),offer(url='https://item.jd.com/124.html',title='罗技 M185 无线鼠标 无接收器'),offer(url='https://item.jd.com/125.html',title='罗技 M187p 无线鼠标')]}
    result=asyncio.run(research_purchase(provider,'罗技 M185 无线鼠标',['jd']))
    assert len(result['shortlist']) == 2
    assert len(result['intent_excluded']) == 1
    assert '型号' in result['intent_excluded'][0]['reason']
