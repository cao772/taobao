"""Provider registry, offer normalization, comparisons and host security.

No platform data is fabricated. Browser prices are unverified display observations,
not a guarantee of checkout price. Business logic does not import the MCP SDK.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse, quote
import re

PLATFORMS = {
    "taobao": {
        "name": "淘宝/天猫",
        "hosts": ("taobao.com", "tmall.com"),
        "search_url": "https://s.taobao.com/search?q={query}",
        "api": "淘宝客物料搜索（需应用权限；商品覆盖有限）",
        "kind": "retail",
    },
    "jd": {
        "name": "京东",
        "hosts": ("jd.com", "360buy.com"),
        "search_url": "https://search.jd.com/Search?keyword={query}",
        "api": "京东联盟商品查询（需联盟权限）",
        "kind": "retail",
    },
    "pdd": {
        "name": "拼多多",
        "hosts": ("yangkeduo.com", "pinduoduo.com"),
        "search_url": "https://mobile.yangkeduo.com/search_result.html?search_key={query}",
        "api": "多多进宝商品搜索（需开放平台权限）",
        "kind": "retail",
    },
    "dewu": {
        "name": "得物",
        "hosts": ("dewu.com", "poizon.com"),
        "search_url": "https://www.dewu.com/",
        "api": "暂未集成官方消费端全站搜索；第三方商业接口须另行授权核实",
        "kind": "retail",
    },
    "xianyu": {
        "name": "闲鱼",
        "hosts": ("goofish.com", "2.taobao.com", "idlefish.com"),
        "search_url": "https://www.goofish.com/search?q={query}",
        "api": "闲鱼服务商接口通常需要准入/授权；非通用全站搜索",
        "kind": "secondhand",
    },
    "meituan": {
        "name": "美团",
        "hosts": ("meituan.com", "dianping.com"),
        "search_url": "https://www.meituan.com/",
        "api": "美团联盟商品查询（需联盟权限）；区域/门店/时段影响价格",
        "kind": "local_service",
    },
}


def allowlisted_url(url: str) -> bool:
    try:
        parts = urlparse(url)
        host = (parts.hostname or "").lower().rstrip(".")
        return parts.scheme == "https" and parts.username is None and parts.password is None and any(
            host == root or host.endswith("." + root)
            for p in PLATFORMS.values() for root in p["hosts"]
        )
    except ValueError:
        return False


def platform_from_url(url: str) -> str | None:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    for key, p in PLATFORMS.items():
        if any(host == root or host.endswith("." + root) for root in p["hosts"]):
            return key
    return None


def search_url(platform: str, query: str) -> str:
    if platform not in PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}; allowed={list(PLATFORMS)}")
    if not query.strip() or len(query) > 120:
        raise ValueError("query 不能为空，长度不得超过 120")
    return PLATFORMS[platform]["search_url"].format(query=quote(query.strip()))


def parse_price(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            dec = Decimal(str(value))
            return dec if dec.is_finite() and 0 < dec < 10000000 else None
        except InvalidOperation:
            return None
    text = str(value).strip().replace(",", "")
    m = re.search(r"(?:[¥￥]\s*|CNY\s*|RMB\s*)(\d{1,8}(?:\.\d{1,2})?)", text, re.I)
    if not m and re.fullmatch(r"\d{1,8}(?:\.\d{1,2})?", text):
        m = re.match(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        dec = Decimal(m.group(1))
        return dec if dec.is_finite() and 0 < dec < 10000000 else None
    except InvalidOperation:
        return None


@dataclass
class Offer:
    platform: str
    title: str
    url: str
    displayed_price_yuan: str | None
    condition: str = "unknown"  # new, used, unknown
    source: str = "browser_observation"
    price_status: str = "unverified_display"  # checkout price MUST be separately confirmed
    specification: str = ""
    merchant: str = ""
    observed_at_utc: str = ""
    raw_price_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_offer(platform: str, title: str, url: str, raw_price: Any,
               *, condition: str = "unknown", specification: str = "",
               merchant: str = "", source: str = "browser_observation") -> Offer:
    if platform not in PLATFORMS:
        raise ValueError("不支持的平台")
    if not allowlisted_url(url) or platform_from_url(url) != platform:
        raise ValueError("商品链接域名不在指定平台的允许列表中")
    price = parse_price(raw_price)
    if condition not in ("new", "used", "unknown"):
        raise ValueError("condition 必须是 new/used/unknown")
    return Offer(
        platform=platform, title=str(title)[:240], url=url,
        displayed_price_yuan=str(price) if price is not None else None,
        condition=condition, source=source,
        specification=str(specification)[:200], merchant=str(merchant)[:160],
        observed_at_utc=datetime.now(timezone.utc).isoformat(),
        raw_price_text=str(raw_price)[:120],
    )


def compare_offers(payload: list[dict[str, Any]], budget_yuan: float | None = None,
                   include_secondhand: bool = False, location: str = "") -> dict[str, Any]:
    if not 1 <= len(payload) <= 100:
        raise ValueError("需要 1-100 条商品记录")
    if budget_yuan is not None and budget_yuan <= 0:
        raise ValueError("预算必须大于零")
    parsed: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, item in enumerate(payload):
        try:
            p = item["platform"]
            item_url = str(item["url"])
            if not allowlisted_url(item_url) or platform_from_url(item_url) != p:
                raise ValueError("平台与商品 URL 不匹配")
            condition = item.get("condition", "unknown")
            if condition not in ("new", "used", "unknown"):
                raise ValueError("成色标记无效")
            raw = item.get("displayed_price_yuan", item.get("price", None))
            price = parse_price(raw)
            if raw is not None and price is None:
                raise ValueError("价格不可解析")
            parsed.append({
                "platform": p, "title": str(item.get("title", ""))[:240],
                "url": item_url, "displayed_price_yuan": str(price) if price is not None else None,
                "condition": condition,
                "merchant": str(item.get("merchant", ""))[:160],
                "specification": str(item.get("specification", ""))[:200],
                "source": item.get("source", "user_supplied"),
                "price_status": item.get("price_status", "unverified_display"),
                "eligible": ((condition != "used" and PLATFORMS[p]["kind"] != "secondhand") or include_secondhand) and
                    (p != "meituan" or bool(location)) and price is not None and
                    (budget_yuan is None or price <= Decimal(str(budget_yuan))),
            })
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f"第 {i + 1} 条: {e}")
    parsed.sort(key=lambda x: (
        not x["eligible"],
        Decimal(x["displayed_price_yuan"]) if x["displayed_price_yuan"] is not None else Decimal("Infinity")
    ))
    return {
        "status": "ok" if not errors else "partial",
        "offers": parsed,
        "errors": errors,
        "warnings": [
            "仅基于提供的展示价排序；未核实券、运费、会员资格、地区价和真实结算价。",
            "不同规格/新旧程度/服务类型不能仅按金额视为同款；由 Agent 或用户先核对型号。",
            "美团商品需要城市和配送/门店条件，未提供 location 时不会列为 eligible。",
            "本工具不下单、不支付、不自动加购物车。",
        ],
    }
