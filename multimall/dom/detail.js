({platform}) => {
  const visible = n => { const s=getComputedStyle(n),r=n.getBoundingClientRect(); return !n.closest('[hidden],[aria-hidden="true"]') && s.display!=='none' && s.visibility!=='hidden' && r.width>0 && r.height>0; };
  const text = n => visible(n) ? n.innerText.replace(/\s+/g,' ').trim() : '';
  // Restrict evidence to product parameter and SKU containers, never account/address blocks.
  const selectors = {
    jd: ['.attribute .list .item', '#parameter2 li', '.p-parameter li', '[class*="_gallery_"] [class*="_scoped_"]', '.choose-attr', '#choose-attrs .item'],
    taobao: ['[class*="BasicContent--"] li', '[class*="Attribute--"] li', '[class*="skuItem--"]'],
    pdd: ['[class*="goods-attribute"]', '[class*="goods-spec"]', '[class*="sku-item"]'],
    xianyu: ['[class*="item-attribute"]', '[class*="item-info"] [class*="attribute"]'],
  }[platform] || [];
  const parameters=[], seen=new Set();
  for (const selector of selectors) for (const n of document.querySelectorAll(selector)) {
    const value=text(n); if (!value || value.length>600 || seen.has(value)) continue;
    seen.add(value); parameters.push({text:value,selector}); if(parameters.length>=40)break;
  }
  const attributes={};
  const keys={brand:'品牌',model:'型号',unit:'销售单位',condition:'成色',manufacturer_part_number:'货号',product_id:'商品编号'};
  for(const [key,label] of Object.entries(keys)) for(const p of parameters) {
    const m=p.text.match(new RegExp('(?:^|\\s)'+label+'[：:\\s]+(.+?)(?=\\s+(?:品牌|型号|商品编号|店铺|货号|销售单位|成色)[：:\\s]|$)')); if(m && m[1].length<100) attributes[key]={value:m[1],selector:p.selector,text:p.text};
  }
  const options=[];
  for(const selector of ['[class*="valueItem--"]','#choose-attrs .item','.choose-attr .item','[class*="sku-item"]']) for(const n of document.querySelectorAll(selector)) {
    const value=text(n); if(value && value.length<160) options.push({text:value,selected:n.getAttribute('aria-selected')==='true' || /(?:^|\s)(?:selected|checked)(?:\s|$)/.test(n.className) || /(?:selected|checked)--/.test(n.className),selector});
  }
  return {parameters,attributes,sku_options:options.slice(0,50),selected_specification:options.filter(o=>o.selected).map(o=>o.text).join(' / '),
    missing_fields:['brand','model','unit','condition'].filter(k=>!attributes[k]),
    notice:'只有明确选中的 SKU 可用于规格对比；可选列表不代表当前价格对应的 SKU。商品标题不作为参数证据。'};
}
