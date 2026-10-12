"""MCP entrypoint: run with python -m multimall.server (stdio)."""
from __future__ import annotations

import json
from typing import Any

from .browser import PlatformBrowserPool
from .evidence import enrich_offer, compact_research_report
from .core import PLATFORMS, allowlisted_url, compare_offers, platform_from_url

from .intelligence import (analyze_reviews as _analyze_reviews,
    match_same_products as _match_same_products, recommend_products as _recommend_products)
from .orchestration import search_all_platforms as _search_all_platforms, research_purchase as _research_purchase

browser = PlatformBrowserPool()

# Imported at launch, not required for unit-testing core functions.
from mcp.types import ToolAnnotations
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("multimall-shopping")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
def list_platforms() -> dict[str, Any]:
    """List six supported platforms, their browser-entry status and official API prerequisites."""
    return {
        "platforms": {key: {
            "name": value["name"], "type": value["kind"],
            "browser": "platform_visible_dom_adapter" if key in ("taobao", "jd", "pdd", "xianyu") else "manual_only",
            "session_tools": ["open_platform_session", "inspect_platform_session"],
            "api": value["api"],
            "api_connected": False,
            "guaranteed_live_search": False,
            "checkout_enabled": False,
        } for key, value in PLATFORMS.items()},
        "notice": "官方联盟 API 尚未配置凭证；浏览器读取依赖用户环境与页面权限。",
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
async def search_products(platform: str, keyword: str, limit: int = 10) -> dict[str, Any]:
    """Open a visible local browser to search ONE platform; return only observed links/prices.

    platform: taobao, jd, pdd, dewu, xianyu, meituan.
    Human handles login/captcha. Dewu/Meituan may require manual in-page search.
    Read-only: no cart/checkout actions. An empty result is NOT a negative search result.
    """
    try:
        return await browser.search(platform, keyword, limit)
    except Exception as e:
        return {"status": "error", "reason": str(e)[:320]}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
async def get_product_detail(url: str) -> dict[str, Any]:
    """Read a user-approved product page from allowlisted platforms (visible local browser).

    Returns page observations rather than asserting an actual SKU's payable price.
    """
    try:
        return await browser.details(url)
    except Exception as e:
        return {"status": "error", "reason": str(e)[:320]}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
def compare_products(products_json: str, budget_yuan: float | None = None,
                     include_secondhand: bool = False, location: str = "") -> dict[str, Any]:
    """Compare supplied observed offers across platforms; never fabricate missing data.

    products_json: JSON array with platform/title/url/displayed_price_yuan/condition.
    include_secondhand must be true to rank used goods as eligible.
    Provide a city/location for any Meituan offer. Human must match the same SKUs.
    """
    try:
        offers = json.loads(products_json)
        if not isinstance(offers, list):
            raise ValueError("products_json 必须是 JSON 数组")
        return compare_offers(offers, budget_yuan, include_secondhand, location)
    except (ValueError, TypeError) as e:
        return {"status": "invalid_input", "reason": str(e)[:320]}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
def prepare_purchase_review(platform: str, product_url: str, title: str,
                            maximum_budget_yuan: float) -> dict[str, Any]:
    """Prepare a human shopping review checklist; NEVER place, reserve, or pay an order."""
    if platform not in PLATFORMS or not allowlisted_url(product_url) or platform_from_url(product_url) != platform:
        return {"status": "invalid_product_link"}
    if maximum_budget_yuan <= 0:
        return {"status": "invalid_budget"}
    return {
        "status": "human_review_required", "platform": platform,
        "product_url": product_url, "title": title[:240],
        "maximum_budget_yuan": maximum_budget_yuan,
        "verify": ["准确 SKU / 尺码 / 型号", "新旧程度与卖家真实性", "收货地区、可配送性和运费", "最终优惠后的应付金额", "退换货和质保", "本人确认下单与付款"],
        "order_submitted": False, "payment_initiated": False,
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
async def close_browser() -> dict[str, Any]:
    """Close owned browsers or release a borrowed CLI session; preserve login profiles."""
    try:
        return await browser.close()
    except Exception as e:
        return {"status": "error", "reason": str(e)[:320]}



@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
async def search_all_platforms(keyword: str,
                               platforms_json: str = '["taobao","jd","pdd"]',
                               per_platform_limit: int = 8) -> dict[str, Any]:
    """Search multiple platforms in parallel in visible browsers; no guaranteed coverage.

    platforms_json: JSON list of 1-6 platform keys (taobao/jd/pdd/dewu/xianyu/meituan).
    Defaults to three retail marketplaces. Include all six explicitly when needed.
    Results expose each platform's actual success/restriction state, not invented data.
    """
    try:
        platforms = json.loads(platforms_json)
        return await _search_all_platforms(browser.search, keyword, platforms, per_platform_limit)
    except (ValueError, TypeError) as e:
        return {"status": "invalid_input", "reason": str(e)[:320]}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
def match_same_products(products_json: str) -> dict[str, Any]:
    """Group SKU candidates using explicit brand/model/specification/condition only.

    Raw titles alone are insufficient; records missing fields stay unmatched.
    """
    try:
        value = json.loads(products_json)
        return _match_same_products(value)
    except (ValueError, TypeError) as e:
        return {"status": "invalid_input", "reason": str(e)[:320]}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
def analyze_product_reviews(reviews_json: str) -> dict[str, Any]:
    """Summarize caller-supplied review excerpts and recurring defect signals.

    Does NOT claim to have collected or verified reviews. No synthetic quality score.
    """
    try:
        reviews = json.loads(reviews_json)
        return _analyze_reviews(reviews)
    except (ValueError, TypeError) as e:
        return {"status": "invalid_input", "reason": str(e)[:320]}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
def recommend_best_products(products_json: str,
                            budget_yuan: float | None = None,
                            include_secondhand: bool = False,
                            location: str = "", top_k: int = 3) -> dict[str, Any]:
    """Evidence-aware provisional shortlist, never a fabricated best-quality ranking.

    Supply explicit SKU fields to compare like-for-like. Optional shipping_yuan
    and coupon_yuan allow an *estimate*, not an authenticated checkout quote.
    """
    try:
        products = json.loads(products_json)
        return _recommend_products(products, budget_yuan, include_secondhand, location, top_k)
    except (ValueError, TypeError) as e:
        return {"status": "invalid_input", "reason": str(e)[:320]}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
async def research_purchase(keyword: str, budget_yuan: float | None = None,
                            platforms_json: str = '["taobao","jd","pdd"]',
                            include_secondhand: bool = False,
                            location: str = "", per_platform_limit: int = 8,
                            inspect_reviews_top_k: int = 2, inspect_details_top_k: int = 3,
                            inspect_details_per_platform: int = 1, compact: bool = True) -> dict[str, Any]:
    """One-call shopping research: search -> provenance -> provisional shortlist.

    Inspect one eligible detail per platform BEFORE ranking, then up to three shortlisted
    details and two review sections. Cached details are reused within this request.
    Compact output is the default to avoid client overflow; compact=False retains all evidence.
    Optionally (inspect_reviews_top_k=0..3) inspect visible review-like DOM text
    for shortlisted product pages; absent reviews must never become a quality score.
    """
    try:
        if not 0 <= inspect_reviews_top_k <= 3:
            raise ValueError("inspect_reviews_top_k 必须是 0-3")
        if not 0 <= inspect_details_top_k <= 3:
            raise ValueError("inspect_details_top_k 必须是 0-3")
        platforms = json.loads(platforms_json)
        result = await _research_purchase(browser.search, keyword, platforms, budget_yuan,
                                          include_secondhand, location, per_platform_limit,
                                          detail_provider=get_product_detail,
                                          inspect_details_per_platform=inspect_details_per_platform)
        result["checkout_verified"] = False
        result["checked"] = ["visible_search_links", "displayed_prices", "platform_coverage"]
        result["missing"] = ["authenticated_checkout_price", "verified_purchase_reviews", "certified_merchant_reputation"]
        if result["status"] == "provisional_results":
            enriched = []
            for item in result["shortlist"][:inspect_details_top_k]:
                detail = item.get("detail_evidence") or await get_product_detail(item["url"])
                merged = enrich_offer(item, detail)
                item.update(merged)
                if not item.get("structured_identity"):
                    item["structured_identity"] = {key:item.get(key, "") for key in ("brand","model","specification","condition","unit")}
                    item["missing_identity_fields"] = [key for key in ("brand","model","specification","condition") if item.get(key) in (None,"","unknown")]
                enriched.append(item)
                item["decision_reasons"] = ["展示价在预算内；同 SKU、运费与优惠资格仍待核验" if budget_yuan is not None else "按展示价生成候选；同 SKU、运费与优惠资格仍待核验"]
            result["checked"].append("shortlisted_visible_product_parameters")
            result["detail_identity_check"] = _match_same_products(enriched) if enriched else {"status":"not_checked"}
            result["missing"].append("same_sku_confirmation_if_identity_fields_missing")
        if result["status"] == "provisional_results" and inspect_reviews_top_k > 0:
            for item in result["shortlist"][:inspect_reviews_top_k]:
                evidence = await get_visible_reviews(item["url"], limit=20)
                item["review_summary"] = evidence["summary"]
                item["review_fetch_status"] = evidence["status"]
            samples = sum(item.get("review_summary", {}).get("sample_size", 0) for item in result["shortlist"])
            result["review_sample_size"] = samples
            result["quality"] = "limited_visible_review_evidence_not_independently_verified" if samples else "no_visible_review_evidence"
            result["risk_entries"] = [{**risk, "product_url":item["url"]} for item in result["shortlist"] for risk in item.get("review_summary", {}).get("risk_entries", [])]
        return compact_research_report(result) if compact else result
    except (ValueError, TypeError) as e:
        return {"status": "invalid_input", "reason": str(e)[:320]}



@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
async def get_visible_reviews(product_url: str, limit: int = 20) -> dict[str, Any]:
    """Read visible review-like text and summarize it, without inventing quality scores.

    Review sections requiring login/click/pagination may be unavailable.
    These are DOM observations, not proof of verified purchase or full review coverage.
    """
    try:
        result = await browser.visible_reviews(product_url, limit)
        if result.get("status") == "observed":
            result["summary"] = _analyze_reviews(result["reviews"])
        else:
            result["summary"] = _analyze_reviews([])
        return result
    except Exception as e:
        return {"status": "error", "reason": str(e)[:280],
                "reviews": [], "summary": _analyze_reviews([])}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
async def open_platform_session(platform: str, keyword: str = "") -> dict[str, Any]:
    """Open a dedicated persistent browser for human login/search. No credentials accepted.

    Login/verification is handled by the user in the browser. Keep this MCP process
    alive, then call inspect_platform_session to read without reloading the page.
    """
    try:
        return await browser.open_session(platform, keyword)
    except Exception:
        return {"status": "error", "reason": "无法打开专用会话；检查平台、浏览器安装及 Profile 占用。"}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))
async def inspect_platform_session(platform: str, limit: int = 10) -> dict[str, Any]:
    """Read current platform page after human login, without navigating or reloading.

    This reports observable page state, not an authenticated identity guarantee.
    """
    try:
        return await browser.inspect_session(platform, limit)
    except Exception:
        return {"status": "error", "reason": "当前会话读取失败，请检查浏览器窗口。"}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
