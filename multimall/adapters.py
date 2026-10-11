"""Platform-specific visible DOM adapters; no hidden payload or credential reading."""
import re
from importlib.resources import files
from urllib.parse import urlparse, parse_qs, urlencode
from .core import allowlisted_url, platform_from_url

OBSERVE_JS = files('multimall').joinpath('dom/observe.js').read_text(encoding='utf-8')


def safe_page_url(url: str) -> str:
    """Only retain public product IDs / search terms, never SSO return URLs/tokens."""
    p = urlparse(url)
    keep = {}
    for key in ('id', 'goods_id', 'q', 'keyword', 'search_key'):
        value = parse_qs(p.query).get(key, [''])[0]
        if value:
            keep[key] = value[:120]
    return f'{p.scheme}://{p.netloc}{p.path}' + ('?' + urlencode(keep) if keep else '')


def product_url(platform: str, url: str) -> bool:
    if not allowlisted_url(url) or platform_from_url(url) != platform:
        return False
    p = urlparse(url)
    q = parse_qs(p.query)
    if platform == 'jd':
        return p.hostname in ('item.jd.com', 'item.m.jd.com') and bool(re.fullmatch(r'/\d+\.html', p.path))
    if platform in ('taobao', 'xianyu', 'pdd'):
        key = 'goods_id' if platform == 'pdd' else 'id'
        identity = q.get(key, [''])[0]
        if not identity.isdigit():
            return False
        if platform == 'taobao':
            return p.hostname in ('item.taobao.com', 'item.m.taobao.com', 'detail.tmall.com') and p.path in ('/item.htm', '/item.html')
        return p.path == '/item' if platform == 'xianyu' else p.path.endswith('/goods.html')
    if platform == 'dewu':
        return bool(re.match(r'^/(?:product-detail|product)/?[A-Za-z0-9_-]+', p.path))
    if platform == 'meituan':
        return bool(re.match(r'^/(?:deal|product|poi)/[A-Za-z0-9_-]+', p.path))
    return False
