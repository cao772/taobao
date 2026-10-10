"""Multi-platform fanout with per-platform evidence provenance and honest coverage.

Searchers are injected for deterministic unit tests and can later be replaced
by authorized API-backed providers without changing MCP tool contracts.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from .core import PLATFORMS, allowlisted_url, platform_from_url
from .intelligence import recommend_products, validated_offer

SearchProvider = Callable[[str, str, int], Awaitable[dict[str, Any]]]
DEFAULT_PLATFORMS = ("taobao", "jd", "pdd")


def normalize_platforms(platforms: list[str] | None) -> list[str]:
    selected = list(DEFAULT_PLATFORMS) if platforms is None else platforms
    if not isinstance(selected, list) or not 1 <= len(selected) <= 6:
        raise ValueError("platforms 需为 1-6 个平台名称")
    if len(set(selected)) != len(selected):
        raise ValueError("platforms 不能重复")
    if any(not isinstance(p, str) or p not in PLATFORMS for p in selected):
        raise ValueError(f"不支持的平台；可选：{', '.join(PLATFORMS)}")
    return selected


async def search_all_platforms(provider: SearchProvider, query: str,
                               platforms: list[str] | None = None,
                               per_platform_limit: int = 8,
                               concurrency: int = 2) -> dict[str, Any]:
    selected = normalize_platforms(platforms)
    if not isinstance(query, str) or not query.strip() or len(query) > 120:
        raise ValueError("商品关键词不能为空，且不得超过 120 字符")
    if not 1 <= per_platform_limit <= 20 or not 1 <= concurrency <= 3:
        raise ValueError("per_platform_limit 取 1-20，concurrency 取 1-3")

    semaphore = asyncio.Semaphore(concurrency)

    async def one(platform: str) -> dict[str, Any]:
        async with semaphore:
            try:
                result = await provider(platform, query, per_platform_limit)
                if not isinstance(result, dict):
                    raise ValueError("Provider 结果不是对象")
                items = result.get("products", [])
                if not isinstance(items, list):
                    raise ValueError("Provider products 不是数组")
                offers = []
                rejected = 0
                for item in items[:per_platform_limit]:
                    try:
                        checked = validated_offer(item)
                        if checked["platform"] != platform:
                            raise ValueError("返回结果跨平台")
                        offers.append(checked)
                    except (ValueError, TypeError, KeyError):
                        rejected += 1
                status = str(result.get("status") or "unknown")
                # Never describe a failure or manual step as successful search.
                if status not in ("observed", "no_extractable_products",
                                  "manual_search_required", "navigation_error",
                                  "unexpected_redirect", "error", "blocked_url",
                                  "invalid_platform"):
                    status = "unknown"
                if status != "observed":
                    offers = []  # avoid accidental leakage of stale/partial data
                return {
                    "platform": platform, "status": status,
                    "products": offers, "rejected_records": rejected,
                    "reason": str(result.get("reason") or result.get("notice") or "")[:280],
                    "search_entry": str(result.get("opened_url") or "")[:400],
                }
            except Exception as exc:
                return {"platform": platform, "status": "error", "products": [],
                        "rejected_records": 0, "reason": str(exc)[:280]}

    results = await asyncio.gather(*(one(p) for p in selected))
    products = [item for res in results for item in res["products"]]
    success = [r["platform"] for r in results if r["status"] == "observed"]
    restricted = [r["platform"] for r in results if r["status"] != "observed"]
    return {
        "status": "observed_all" if not restricted else ("partial" if success else "no_verified_search_results"),
        "query": query.strip(),
        "requested_platforms": selected, "observed_platforms": success,
        "limited_platforms": restricted, "per_platform": results,
        "products": products, "products_count": len(products),
        "source_notice": "仅汇总即时可见商品记录；受限平台不推断有无商品或价格。价格未经结算验证。",
    }


async def research_purchase(provider: SearchProvider, query: str,
                            platforms: list[str] | None = None,
                            budget_yuan: float | None = None,
                            include_secondhand: bool = False, location: str = "",
                            per_platform_limit: int = 8) -> dict[str, Any]:
    discovery = await search_all_platforms(provider, query, platforms, per_platform_limit)
    candidates = discovery["products"]
    if not candidates:
        return {
            "status": "needs_more_evidence",
            "discovery": discovery,
            "shortlist": [],
            "reason": "没有任何平台返回可核实的商品记录；不能给出推荐。",
            "next_step": "检查真实登录/权限/页面变化，或由用户提供具体商品链接。",
        }
    ranked = recommend_products(candidates, budget_yuan, include_secondhand, location)
    return {
        "status": "provisional_results",
        "discovery": {k: v for k, v in discovery.items() if k != "products"},
        "shortlist": ranked["recommendations"],
        "recommendation_analysis": {k: v for k, v in ranked.items() if k != "recommendations"},
        "quality": "not_assessed_no_verified_reviews",
        "next_step": "确认同 SKU，再获取可信的评价和商家证据；实付价格以结算页为准。",
    }
