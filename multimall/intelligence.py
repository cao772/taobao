"""Deterministic shopping evidence analysis, not a model-generated quality verdict.

This module deliberately does not scrape reviews or infer the truth of merchant claims.
Missing evidence stays missing; matching different SKU variants is unsafe.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
import re
from typing import Any

from .core import PLATFORMS, allowlisted_url, parse_price, platform_from_url

_NEGATIVE_TOPICS = {
    "function_failure": ("故障", "不能用", "无法使用", "坏了", "损坏", "死机", "defective", "broken"),
    "counterfeit_concern": ("假货", "疑似假", "假冒", "仿品", "fake", "counterfeit"),
    "delivery_damage": ("破损", "磕碰", "包装破", "漏液", "shipping damage"),
    "after_sales": ("不给退", "拒绝退款", "售后差", "不保修", "售后不管"),
    "spec_mismatch": ("货不对板", "参数不符", "少配件", "型号不对", "与描述不符"),
}
_POSITIVE = ("好用", "不错", "满意", "稳定", "做工好", "符合描述", "质量好")
_NEGATE = ("没有", "并未", "不是", "未发现", "无", "不")


def _identity(value: Any) -> str:
    # E.g. "ESP32-S3" and "esp32 s3" normalize alike, but S3 and S3-N16R8 do not.
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def validated_offer(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("商品记录应为对象")
    platform = row.get("platform")
    url = row.get("url")
    if platform not in PLATFORMS or not isinstance(url, str) or not allowlisted_url(url) or platform_from_url(url) != platform:
        raise ValueError("商品平台或 URL 不符合白名单")
    condition = row.get("condition", "unknown")
    if condition not in ("new", "used", "unknown"):
        raise ValueError("condition 必须是 new/used/unknown")
    price = parse_price(row.get("displayed_price_yuan", row.get("price")))
    return {
        "platform": platform,
        "url": url,
        "title": str(row.get("title") or "")[:240],
        "brand": str(row.get("brand") or "")[:80],
        "model": str(row.get("model") or "")[:120],
        "specification": str(row.get("specification") or "")[:200],
        "condition": condition,
        "merchant": str(row.get("merchant") or "")[:120],
        "displayed_price_yuan": str(price) if price else None,
        "price_status": str(row.get("price_status") or "unverified_display")[:60],
        "source": str(row.get("source") or "unspecified")[:100],
        "observed_at_utc": str(row.get("observed_at_utc") or "")[:60],
        "shipping_yuan": row.get("shipping_yuan"),
        "coupon_yuan": row.get("coupon_yuan"),
        "seller_rating": row.get("seller_rating"),
        "seller_rating_count": row.get("seller_rating_count"),
        "return_policy": row.get("return_policy"),
        "raw_price_text": str(row.get("raw_price_text") or "")[:120],
        "evidence": row.get("evidence") if isinstance(row.get("evidence"), dict) else {},
    }


def identity_key(row: dict[str, Any]) -> str | None:
    """Only structured explicit brand + model + variant permit grouping.

    Unknown condition is not assumed new; missing specification does not match
    a specified SKU. Even an identity group remains a *candidate*, not a guarantee.
    """
    brand, model, spec = (_identity(row.get(key)) for key in ("brand", "model", "specification"))
    if not brand or not model or not spec or row.get("condition", "unknown") == "unknown":
        return None
    return "|".join((brand, model, spec, row["condition"]))


def match_same_products(products: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(products, list) or not 1 <= len(products) <= 100:
        raise ValueError("需要 1-100 条候选商品")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unmatched: list[dict[str, Any]] = []
    errors = []
    for i, raw in enumerate(products):
        try:
            row = validated_offer(raw)
            key = identity_key(row)
            if key is None:
                unmatched.append({"index": i, "url": row["url"], "title": row["title"], "reason": "brand/model/specification/condition 缺失，不能认定同款"})
            else:
                groups[key].append({"index": i, "url": row["url"], "platform": row["platform"], "displayed_price_yuan": row["displayed_price_yuan"]})
        except (ValueError, TypeError) as e:
            errors.append({"index": i, "reason": str(e)})
    return {
        "status": "partial" if errors else "ok",
        "candidate_groups": [
            {"identity_key": k, "match_status": "structured_fields_agree_manual_confirmation_required", "offers": v}
            for k, v in sorted(groups.items()) if len(v) >= 2
        ],
        "singletons": [
            {"identity_key": k, "offers": v}
            for k, v in sorted(groups.items()) if len(v) == 1
        ],
        "unmatched": unmatched,
        "errors": errors,
        "warning": "仅比较显式品牌、型号、变体规格与新旧状态完全一致的候选；不保证真正同 SKU，需核对商家详情。",
    }


def analyze_reviews(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize caller-provided review snippets; no fabricated sentiment/quality rating."""
    if not isinstance(reviews, list) or len(reviews) > 300:
        raise ValueError("reviews 必须为最多 300 项的数组")
    topic_counts: Counter[str] = Counter()
    positive = negative = rated = 0
    ratings = []
    accepted = []
    for i, row in enumerate(reviews):
        if not isinstance(row, dict):
            continue
        txt = str(row.get("text") or "").strip()[:2000]
        if not txt:
            continue
        rated_value = row.get("rating")
        if isinstance(rated_value, (int, float)) and not isinstance(rated_value, bool) and 1 <= rated_value <= 5:
            ratings.append(float(rated_value))
            rated += 1
        hits = []
        lowered = txt.lower()
        for topic, words in _NEGATIVE_TOPICS.items():
            for word in words:
                position = lowered.find(word.lower())
                if position < 0:
                    continue
                prefix = lowered[max(0, position - 4):position]
                # Short negation phrase: "没有故障" shouldn't count as a fault.
                if any(prefix.endswith(neg) for neg in _NEGATE):
                    continue
                hits.append(topic)
                break
        if hits:
            negative += 1
            topic_counts.update(hits)
        elif any(w in lowered for w in _POSITIVE):
            positive += 1
        accepted.append({"index": i, "issue_topics": hits,
                         "source_url": str(row.get("source_url") or "")[:300]})
    n = len(accepted)
    return {
        "status": "no_review_evidence" if n == 0 else "evidence_summary",
        "sample_size": n,
        "rating_samples": rated,
        "mean_rating_from_supplied_samples": round(sum(ratings) / rated, 2) if rated else None,
        "positive_keyword_mentions": positive,
        "issue_review_mentions": negative,
        "issue_topics": dict(topic_counts),
        "review_evidence": accepted,
        "quality_score": None,
        "evidence_level": "limited_unverified_snippets" if n < 20 else "unverified_snippets_only",
        "caveat": "只分析传入的评论片段，未验证是否真实购买、刷评、样本是否有偏或覆盖全部差评；不输出产品质量分。",
    }


def _final_price(row: dict[str, Any]) -> dict[str, Any]:
    display = parse_price(row["displayed_price_yuan"])
    shipping = parse_price(row.get("shipping_yuan"))
    coupon = parse_price(row.get("coupon_yuan"))
    # Explicit zero values are valid, parse_price rejects 0 by design.
    def money_zero(v: Any) -> Decimal | None:
        if v is None or isinstance(v, bool):
            return None
        if str(v).strip() in ("0", "0.0", "0.00", "¥0", "￥0"):
            return Decimal("0")
        return parse_price(v)

    shipping = money_zero(row.get("shipping_yuan"))
    coupon = money_zero(row.get("coupon_yuan"))
    if display is None or shipping is None or coupon is None or coupon > display:
        return {"estimated_total_yuan": None, "reason": "展示价/运费/优惠缺失或金额无效"}
    return {"estimated_total_yuan": str(display + shipping - coupon),
            "reason": "基于输入字段估算；优惠资格和真实结算金额仍需人工核实"}


def recommend_products(products: list[dict[str, Any]], budget_yuan: float | None = None,
                       include_secondhand: bool = False, location: str = "",
                       top_k: int = 3) -> dict[str, Any]:
    """Offer provisional, evidence-aware price shortlist, never assert one true best seller.

    Actual review/seller verification is out of scope until platform adapters exist.
    Rank on comparable display prices ONLY; do not synthesize quality scores.
    """
    if not isinstance(products, list) or not 1 <= len(products) <= 100:
        raise ValueError("需要 1-100 条商品")
    if budget_yuan is not None and (not isinstance(budget_yuan, (int, float)) or isinstance(budget_yuan, bool) or not 0 < budget_yuan < 10_000_000):
        raise ValueError("预算无效")
    if not 1 <= top_k <= 10:
        raise ValueError("top_k 必须为 1-10")
    matches = match_same_products(products)
    scored: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for i, raw in enumerate(products):
        try:
            row = validated_offer(raw)
        except (TypeError, ValueError) as e:
            excluded.append({"index": i, "reason": str(e)})
            continue
        reasons = []
        amount = parse_price(row["displayed_price_yuan"])
        if amount is None:
            reasons.append("无可解析的展示价")
        if (row["condition"] == "used" or PLATFORMS[row["platform"]]["kind"] == "secondhand") and not include_secondhand:
            reasons.append("未授权二手商品")
        if row["platform"] == "meituan" and not location.strip():
            reasons.append("美团商品缺少使用城市/配送地区")
        if amount is not None and budget_yuan is not None and amount > Decimal(str(budget_yuan)):
            reasons.append("展示价超预算")
        if reasons:
            excluded.append({"index": i, "title": row["title"], "url": row["url"], "reasons": reasons})
            continue
        group = identity_key(row)
        computed = _final_price(row)
        if computed["estimated_total_yuan"] is not None and budget_yuan is not None and Decimal(computed["estimated_total_yuan"]) > Decimal(str(budget_yuan)):
            excluded.append({"index": i, "title": row["title"], "url": row["url"], "reasons": ["含运费估算价超预算"]})
            continue
        scored.append({
            "index": i,
            "title": row["title"],
            "platform": row["platform"],
            "merchant": row["merchant"],
            "url": row["url"],
            "displayed_price_yuan": row["displayed_price_yuan"],
            "observed_at_utc": row["observed_at_utc"],
            "source": row["source"],
            "evidence": row["evidence"],
            "raw_price_text": row["raw_price_text"],
            "estimated_total_yuan": computed["estimated_total_yuan"],
            "price_explanation": computed["reason"],
            "identity_key": group,
            "same_sku_confirmed": False,
            "seller_evidence": "unverified" if row["seller_rating"] is not None else "missing",
            "quality_evidence": "missing_or_unverified",
            "recommendation_basis": "displayed_price_only_no_quality_assessment",
        })
    # Sorting does not infer equivalence: identity_key None sorts into a separate provisional bucket.
    scored.sort(key=lambda x: (
        x["identity_key"] or "~unmatched",
        Decimal(x["estimated_total_yuan"] or x["displayed_price_yuan"]),
        x["platform"], x["url"],
    ))
    for rank, offer in enumerate(scored):
        offer["rank_within_identity_group"] = sum(
            1 for other in scored[:rank + 1] if other["identity_key"] == offer["identity_key"])
    return {
        "status": "provisional_shortlist" if scored else "insufficient_evidence",
        "recommendations": scored[:top_k],
        "total_eligible": len(scored),
        "excluded": excluded,
        "identity_check": matches,
        "ranking_scope": "within_explicit_variant_groups_only; incomplete_identity_not_comparable",
        "warnings": [
            "该列表不是最终质量排名，也不能据此认定最值得买：商品评价、真伪、卖家信誉、售后均未独立核实。",
            "只有明确品牌/型号/规格/新旧完全一致的候选才属于同款候选组；需要人工确认实物 SKU。",
            "展示价格不等于最终实付价；运费、优惠券、会员、地区价及库存必须在结算页核实。",
            "不执行购物车、下单和支付操作。",
        ],
    }
