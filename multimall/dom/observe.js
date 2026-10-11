({platform, limit, mode}) => {
  const visible = node => {
    if (!node || node.closest('[hidden], [aria-hidden="true"]')) return false;
    const s = getComputedStyle(node), r = node.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0' && r.width > 0 && r.height > 0;
  };
  const clean = node => visible(node) ? (node.innerText || '').replace(/\s+/g, ' ').trim() : '';
  const first = (root, selectors) => {
    for (const selector of selectors) for (const node of root.querySelectorAll(selector)) {
      const text = clean(node); if (text) return {text, selector};
    }
    return {text: '', selector: null};
  };
  const configs = {
    jd: {cards: ['.plugin_goodsCardWrapper[data-sku]', '#J_goodsList .gl-item', '.gl-warp .gl-item'],
      title: ['[class*="_goods_title_container_"]', '.p-name em', '.p-name'], price: ['span[class*="_price_"]', '.p-price'], merchant: ['span[class*="_name_"]', '.p-shop'],
      links: ['.p-name a[href]', '.p-img a[href]'], reviews: ['.comment-item .comment-con', '.comment-item .comment-content']},
    taobao: {cards: ['a[class*="Card--doubleCard"]', '[class*="doubleCardWrapper"]', '.m-itemlist .item'],
      title: ['[class*="Title--title"]', '[class*="title--"]', '.title'],
      price: ['[class*="innerPriceWrapper"]', '[class*="Price--price"]', '[class*="price--"]', '.price'],
      merchant: ['[class*="shopNameText"]', '[class*="ShopInfo--shopName"]', '[class*="shopName"]', '.shop'],
      links: ['a[href*="item.taobao.com"]', 'a[href*="detail.tmall.com"]'],
      reviews: ['[class*="Comment--"] [class*="content--"]', '.rate-grid .tm-rate-fulltxt', '.rate-grid .tm-rate-content', '.rate-content', '[class*="Comment--content"]', '[class*="commentContent"]']},
    xianyu: {cards: ['a[class*="feeds-item-wrap"]', '[class*="feeds-item-wrap"]'],
      title: ['[class*="main-title"]'], price: ['[class*="price-wrap"]', '[class*="price-container"]'],
      merchant: ['[class*="nick-name"]', '[class*="user-name"]'], links: ['a[href*="/item?"]'], reviews: []},
    pdd: {cards: ['._3glhOBhU', '[data-testid="goods-card"]', '[class*="goods-card"]', '[class*="goods_item"]'],
      title: ['._3ANzdjkc', '[class*="goods-name"]', '[class*="goods_name"]'], price: ['._3_U04GgA', '[class*="goods-price"]', '[class*="goods_price"]'],
      merchant: ['[class*="shop-name"]'], links: ['a[href*="goods.html"]', 'a[href*="goods_id="]'],
      reviews: ['[class*="review-item"] [class*="content"]', '.comment-item .comment-content']},
    dewu: {cards: [], title: [], price: [], merchant: [], links: [], reviews: []},
    meituan: {cards: [], title: [], price: [], merchant: [], links: [], reviews: []}
  };
  const c = configs[platform];
  const canonical = href => {
    try {
      const u = new URL(href, location.href), h = u.hostname;
      if (u.protocol !== 'https:' || u.username || u.password) return null;
      const host = root => h === root || h.endsWith('.' + root);
      if (platform === 'jd' && ['item.jd.com', 'item.m.jd.com'].includes(h) && /^\/\d+\.html$/.test(u.pathname)) return u.origin + u.pathname;
      if (platform === 'taobao' && ['item.taobao.com', 'detail.tmall.com', 'item.m.taobao.com'].includes(h) && /^\d+$/.test(u.searchParams.get('id') || '')) return u.origin + u.pathname + '?id=' + u.searchParams.get('id');
      if (platform === 'xianyu' && host('goofish.com') && u.pathname === '/item' && /^\d+$/.test(u.searchParams.get('id') || '')) return u.origin + '/item?id=' + u.searchParams.get('id');
      if (platform === 'pdd' && (host('yangkeduo.com') || host('pinduoduo.com')) && u.pathname.endsWith('/goods.html') && /^\d+$/.test(u.searchParams.get('goods_id') || '')) return u.origin + u.pathname + '?goods_id=' + u.searchParams.get('goods_id');
    } catch (_) {}
    return null;
  };
  const bodyText = clean(document.body);
  const url = new URL(location.href);
  const loginFrame = [...document.querySelectorAll('iframe')].some(n => visible(n) && /(?:login|passport)/i.test(n.src));
  const loginForm = [...document.querySelectorAll('input[type="password"], input[placeholder*="手机号"], input[placeholder*="验证码"]')].some(visible);
  const challenge = /(?:risk_handler|captcha|verify|punish)/i.test(url.pathname) || /(?:验证|安全检查)/.test(document.title) || /请完成验证|拖动滑块|访问过于频繁|访问被拒绝/.test(bodyText);
  const login = /^(?:login|passport)\./.test(url.hostname) || /\/(?:login|signin)(?:[./]|$)/i.test(url.pathname) || loginFrame || loginForm;
  let state = challenge ? 'verification_required' : login ? 'login_required' : 'ready';
  const products = [], unlinked_products = [], reviews = [], seen = new Set();
  if (state === 'ready' && mode === 'products') {
    for (const selector of c.cards) for (const card of document.querySelectorAll(selector)) {
      if (products.length + unlinked_products.length >= limit || !visible(card)) continue;
      let href = canonical(card.matches('a[href]') ? card.href : '');
      if (!href) for (const ls of c.links) for (const a of card.querySelectorAll(ls)) { href = canonical(a.href); if (href) break; }
      if (!href && platform === 'jd' && /^\d+$/.test(card.getAttribute('data-sku') || '')) href = 'https://item.jd.com/' + card.getAttribute('data-sku') + '.html';
      if ((href && seen.has(href)) || (!href && platform !== 'pdd')) continue;
      const title = first(card, c.title); if (!title.text) continue;
      const price = first(card, c.price), merchant = first(card, c.merchant);
      // Read only a dedicated price field. Ranges/multiple amounts remain unknown.
      const priceText = price.text.replace(/^(?:券后|优惠后|到手价)\s*/, '').replace(/(\d)\s*\.\s*(\d)/g, '$1.$2');
      const prices = priceText.match(/\d+(?:[.,]\d+)*/g) || [];
      const raw = prices.length === 1 && /^(?:[￥¥]\s*)?\d+(?:\.\d{1,2})?(?:\s*元)?$/.test(priceText) ? prices[0] : null;
      if (href) seen.add(href);
      const row = {title: title.text.slice(0,240), url: href, raw_price: raw,
        raw_price_text: price.text.slice(0,120), merchant: merchant.text.slice(0,120),
        condition: 'unknown', evidence: {card_selector: selector, title_selector: title.selector, price_selector: price.selector, merchant_selector: merchant.selector}};
      if (href) products.push(row);
      else unlinked_products.push({...row, card_index: [...document.querySelectorAll(selector)].indexOf(card)});
    }
  }
  if (state === 'ready' && mode === 'reviews') {
    for (const selector of c.reviews) for (const node of document.querySelectorAll(selector)) {
      if (reviews.length >= limit) break;
      const text = clean(node).slice(0,800);
      if (text.length < 4 || seen.has(text)) continue;
      seen.add(text); reviews.push({text, selector});
    }
  }
  if (state === 'ready' && !products.length && !unlinked_products.length && mode === 'products') state = /加载中|正在加载/.test(bodyText) ? 'loading' : 'no_extractable_products';
  // Never return body excerpts or query strings from login/SSO pages.
  return {state, products, unlinked_products, reviews, page_title: document.title.slice(0,180), page_origin: url.origin,
    page_path: url.pathname, adapter: platform + '_visible_dom_v1'};
}
