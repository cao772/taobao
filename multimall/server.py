"""MCP entrypoint: run with python -m multimall.server (stdio)."""
from __future__ import annotations

import json
from typing import Any

from .browser import ReadOnlyBrowser
from .core import PLATFORMS, allowlisted_url, compare_offers, platform_from_url

browser = ReadOnlyBrowser()

# Imported at launch, not required for unit-testing core functions.
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("multimall-shopping")


@mcp.tool()
def list_platforms() -> dict[str, Any]:
    """List six supported platforms, their browser-entry status and official API prerequisites."""
    return {
        "platforms": {key: {
            "name": value["name"], "type": value["kind"],
            "browser": "best_effort_visible_read_only",
            "api": value["api"],
            "api_connected": False,
            "guaranteed_live_search": False,
            "checkout_enabled": False,
        } for key, value in PLATFORMS.items()},
        "notice": "官方联盟 API 尚未配置凭证；浏览器读取依赖用户环境与页面权限。",
    }


@mcp.tool()
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


@mcp.tool()
async def get_product_detail(url: str) -> dict[str, Any]:
    """Read a user-approved product page from allowlisted platforms (visible local browser).

    Returns page observations rather than asserting an actual SKU's payable price.
    """
    try:
        return await browser.details(url)
    except Exception as e:
        return {"status": "error", "reason": str(e)[:320]}


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
async def close_browser() -> dict[str, str]:
    """Close the dedicated shopping browser; does not clear session cookies from profile."""
    try:
        return await browser.close()
    except Exception as e:
        return {"status": "error", "reason": str(e)[:320]}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
