"""Merge bounded visible product evidence without promoting titles into SKU facts."""
from __future__ import annotations
from typing import Any
from .adapters import safe_page_url


def enrich_offer(offer: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    row = dict(offer)
    row['detail_evidence'] = detail
    data = detail.get('data') or {}
    if detail.get('status') != 'observed' or safe_page_url(str(data.get('url') or '')) != safe_page_url(row['url']):
        row['detail_merge_status'] = 'unavailable_or_product_mismatch'
        return row
    attributes = data.get('attributes') or {}
    sources = {}
    for key in ('brand', 'model', 'unit'):
        field = attributes.get(key) or {}
        if field.get('value'):
            row[key] = str(field['value'])
            sources[key] = field
    selected = data.get('selected_specification') or ''
    if selected:
        row['specification'] = selected
        sources['specification'] = {'value':selected, 'selected_options':[o for o in data.get('sku_options', []) if o.get('selected')]}
    condition = attributes.get('condition') or {}
    value = str(condition.get('value') or '')
    if value in ('全新', '全新未拆封', '未使用'):
        row['condition'] = 'new'
    elif value in ('二手', '几乎全新', '轻微使用痕迹', '明显使用痕迹') or value in ('99新', '95新', '9成新', '8成新'):
        row['condition'] = 'used'
    if value:
        sources['condition'] = condition
    merchant = data.get('merchant') or {}
    if merchant.get('text'):
        row['merchant'] = merchant['text']
        row['merchant_evidence'] = {**merchant, 'assessment':'visible_display_claim_not_certified_reputation'}
    row['structured_identity'] = {key:row.get(key, '') for key in ('brand','model','specification','condition','unit')}
    row['missing_identity_fields'] = [key for key in ('brand','model','specification','condition') if row.get(key) in (None,'','unknown')]
    row['evidence'] = {**(row.get('evidence') or {}), 'structured_fields':sources, 'detail_source_url':data['url'], 'detail_observed_at_utc':data.get('observed_at_utc', '')}
    row['detail_merge_status'] = 'visible_structured_claims_only'
    row['price_sku_verified'] = False
    return row
