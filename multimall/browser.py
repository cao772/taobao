"""Conservative visible-browser reader for human-owned shopping sessions.

No form submission, payment, cart mutation, captcha bypass or cookie extraction.
Only supported shopping domains can be navigated to. Real-page extraction is
best effort: an empty result is not evidence that no product exists.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .core import PLATFORMS, allowlisted_url, make_offer, platform_from_url, search_url

_DOM_EXTRACT = r"""
({platform, limit}) => {
  const prefixes = {
    jd: ['item.jd.com/', 'item.m.jd.com/'],
    taobao: ['item.taobao.com/', 'detail.tmall.com/', 'item.m.taobao.com/'],
    pdd: ['goods.html', 'goods_id=', '/goods/'],
    dewu: ['/product-detail', '/product/'],
    xianyu: ['/item', 'item2.', '/detail'],
    meituan: ['/deal/', '/product/', '/poi/']
  };
  const seen = new Set(), goods = [];
  const allowed = prefixes[platform] || [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href || '';
    if (!href.startsWith('https://') || !allowed.some(p => href.includes(p))) continue;
    if (seen.has(href)) continue;
    const container = a.closest('[class*="item"], [class*="goods"], [class*="product"], li') || a.parentElement;
    const text = ((container && container.innerText) || a.innerText || '').replace(/\s+/g,' ').trim();
    const title = (a.getAttribute('title') || a.innerText || text).replace(/\s+/g,' ').trim().slice(0,180);
    if (!title || title.length < 3) continue;
    const matches = text.match(/[￥¥]\s*\d{1,8}(?:\.\d{1,2})?/g) || [];
    goods.push({ title, url: href, raw_price: matches.length ? matches[0] : null, preview: text.slice(0,250) });
    seen.add(href);
    if (goods.length >= limit) break;
  }
  const body = document.body ? document.body.innerText : '';
  return { title: document.title, url: location.href, items: goods,
    page_excerpt: body.replace(/\s+/g,' ').slice(0,1500) };
}
"""

_DETAIL_EXTRACT = r"""
() => {
  const meta = (key) => document.querySelector('meta[property="' + key + '"], meta[name="' + key + '"]')?.content || '';
  const body = document.body ? document.body.innerText.replace(/\s+/g,' ').slice(0,4000) : '';
  const prices = (body.match(/[￥¥]\s*\d{1,8}(?:\.\d{1,2})?/g) || []).slice(0,8);
  return {
    title: meta('og:title') || document.title,
    url: location.href,
    meta_description: meta('description').slice(0,500),
    meta_price: meta('product:price:amount'),
    meta_image: meta('og:image'),
    candidate_price_texts: prices,
    page_excerpt: body,
  };
}
"""


_REVIEW_EXTRACT = r"""
({limit}) => {
  // Conservative selectors: only visibly rendered elements that appear to be reviews.
  // A page may expose no supported selectors (login, application-only, or lazy loading).
  const selectors = [
    '[data-testid="review-item"]',
    '[data-testid="review-card"]',
    '[class~="comment-item"]',
    '[class~="review-item"]',
    '[class~="rate-content"]',
    '[class~="comment-content"]',
    '[class~="rate-grid"]'
  ];
  const seen = new Set(), rows = [];
  for (const selector of selectors) {
    for (const node of document.querySelectorAll(selector)) {
      if (rows.length >= limit) break;
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      if (style.display === 'none' || style.visibility === 'hidden' || !rect.width || !rect.height) continue;
      const text = (node.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 800);
      if (text.length < 12 || seen.has(text)) continue;
      seen.add(text);
      rows.push({ text, selector });
    }
    if (rows.length >= limit) break;
  }
  return {rows, page_title: document.title, page_url: location.href};
}
"""

class ReadOnlyBrowser:
    def __init__(self, profile_dir: str | None = None) -> None:
        self._profile_dir = profile_dir
        self._lock = asyncio.Lock()
        self._playwright = None
        self._context = None
        self._page = None

    async def _ensure(self) -> None:
        if self._page is not None and not self._page.is_closed():
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError("缺少 playwright，执行 pip install -e . 和 python -m playwright install chromium") from e
        self._playwright = await async_playwright().start()
        profile_dir = Path(self._profile_dir or os.environ.get("MULTIMALL_PROFILE_DIR", str(Path.home() / ".multimall-mcp" / "browser-profile"))).expanduser()
        profile_dir.mkdir(parents=True, exist_ok=True)
        headless = os.environ.get("MULTIMALL_HEADLESS", "false").lower() == "true"
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(profile_dir), headless=headless, accept_downloads=False,
            viewport={"width": 1440, "height": 900},
        )
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

    async def _visit(self, url: str) -> dict[str, Any] | None:
        if not allowlisted_url(url):
            raise ValueError("拒绝访问非电商允许域名或非 HTTPS 地址")
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await self._page.wait_for_timeout(1300)
        except Exception as e:
            return {"status": "navigation_error", "reason": str(e)[:220], "requested_url": url}
        # Also validate the target after redirects. Never read information from an unexpected origin.
        if not allowlisted_url(self._page.url):
            redirected = self._page.url
            await self._page.goto("about:blank")
            return {"status": "unexpected_redirect", "reason": "跳转到非允许域名，已停止读取", "redirect_host": urlparse(redirected).hostname}
        return None

    async def search(self, platform: str, query: str, limit: int = 10) -> dict[str, Any]:
        if platform not in PLATFORMS:
            return {"status": "invalid_platform", "allowed": list(PLATFORMS)}
        limit = min(max(int(limit), 1), 20)
        async with self._lock:
            await self._ensure()
            url = search_url(platform, query)
            error = await self._visit(url)
            if error:
                return error
            result: dict[str, Any] = await self._page.evaluate(_DOM_EXTRACT, {"platform": platform, "limit": limit})
            offers = []
            for obj in result["items"]:
                try:
                    offers.append(make_offer(platform, obj["title"], obj["url"], obj["raw_price"]).to_dict())
                except (ValueError, KeyError):
                    continue
            if platform in ("dewu", "meituan"):
                status = "manual_search_required"
            else:
                status = "observed" if offers else "no_extractable_products"
            return {
                "status": status,
                "platform": platform,
                "query": query,
                "opened_url": self._page.url,
                "products": offers,
                "page_title": result["title"],
                "page_excerpt": result["page_excerpt"] if not offers else "",
                "data_source": "live_visible_browser_not_checkout_verified",
                "notice": "结果取自当前浏览器可见 DOM。为空可能是登录、风控、动态页面或选择器失效，不代表商品不存在。得物/美团需在打开的页面中手动完成检索。",
            }

    async def details(self, url: str) -> dict[str, Any]:
        async with self._lock:
            if not allowlisted_url(url):
                return {"status": "blocked_url", "reason": "非允许 HTTPS 电商域名"}
            await self._ensure()
            error = await self._visit(url)
            if error:
                return error
            detail = await self._page.evaluate(_DETAIL_EXTRACT)
            return {
                "status": "observed",
                "platform": platform_from_url(self._page.url),
                "data_source": "live_visible_browser_not_checkout_verified",
                "data": detail,
                "notice": "candidate_price_texts 为正文中出现的候选价格，不一定是 SKU 实际售价；请复核规格、库存、地区与结算页。",
            }


    async def visible_reviews(self, url: str, limit: int = 20) -> dict[str, Any]:
        """Return ONLY visibly rendered review-like DOM snippets; not independently verified."""
        if not allowlisted_url(url):
            return {"status": "blocked_url", "reviews": [], "reason": "URL 不在允许列表"}
        if not 1 <= limit <= 50:
            return {"status": "invalid_input", "reviews": [], "reason": "limit 必须是 1-50"}
        async with self._lock:
            await self._ensure()
            error = await self._visit(url)
            if error:
                return {**error, "reviews": []}
            found = await self._page.evaluate(_REVIEW_EXTRACT, {"limit": limit})
            rows = [{"text": r["text"], "source_url": found["page_url"],
                     "extraction_selector": r["selector"], "verified_purchase": None}
                    for r in found["rows"]]
            return {
                "status": "observed" if rows else "no_visible_reviews",
                "platform": platform_from_url(found["page_url"]),
                "reviews": rows,
                "review_count": len(rows),
                "page_url": found["page_url"],
                "provenance": "visible_dom_only_not_independently_verified",
                "caveat": "只能提取当前页面已渲染的疑似评论，可能遗漏分页/折叠差评，也无法核实真实购买；缺失不代表没有差评。",
            }

    async def close(self) -> dict[str, str]:
        async with self._lock:
            if self._context is not None:
                await self._context.close()
            if self._playwright is not None:
                await self._playwright.stop()
            self._context = self._page = self._playwright = None
            return {"status": "closed"}


class PlatformBrowserPool:
    """Separate persistent user-controlled sessions for independently browsed sites.

    One profile per platform prevents Chromium profile locks during concurrent
    discovery. No background scraping or stealth/browser fingerprint evasion.
    """

    def __init__(self) -> None:
        self._browsers: dict[str, ReadOnlyBrowser] = {}
        self._mutex = asyncio.Lock()
        root = os.environ.get("MULTIMALL_PROFILE_DIR", str(Path.home() / ".multimall-mcp" / "browser-profiles"))
        self._root = Path(root).expanduser()

    async def _browser(self, platform: str) -> ReadOnlyBrowser:
        if platform not in PLATFORMS:
            raise ValueError("未支持的平台")
        async with self._mutex:
            if platform not in self._browsers:
                self._browsers[platform] = ReadOnlyBrowser(profile_dir=str(self._root / platform))
            return self._browsers[platform]

    async def search(self, platform: str, query: str, limit: int = 10) -> dict[str, Any]:
        return await (await self._browser(platform)).search(platform, query, limit)

    async def details(self, url: str) -> dict[str, Any]:
        p = platform_from_url(url)
        if p is None or not allowlisted_url(url):
            return {"status": "blocked_url", "reason": "不在电商站点允许列表中"}
        return await (await self._browser(p)).details(url)


    async def visible_reviews(self, url: str, limit: int = 20) -> dict[str, Any]:
        p = platform_from_url(url)
        if p is None or not allowlisted_url(url):
            return {"status": "blocked_url", "reviews": [], "reason": "URL 不在允许列表"}
        return await (await self._browser(p)).visible_reviews(url, limit)

    async def close(self) -> dict[str, Any]:
        async with self._mutex:
            browsers = list(self._browsers.values())
            self._browsers.clear()
        results = await asyncio.gather(*(browser.close() for browser in browsers), return_exceptions=True)
        return {"status": "closed" if all(isinstance(r, dict) for r in results) else "partial",
                "browsers_closed": sum(isinstance(r, dict) for r in results)}
