import asyncio
from multimall.evidence import enrich_offer
from multimall.orchestration import research_purchase
import multimall.server as server


def row(platform='jd', price='50'):
    return {'platform':platform,'url':'https://item.jd.com/123.html' if platform=='jd' else 'https://mobile.yangkeduo.com/goods.html?goods_id=456', 'title':'M185无线鼠标','displayed_price_yuan':price,'condition':'unknown'}


def detail(url):
    return {'status':'observed','data':{'url':url,'observed_at_utc':'2026-10-12T00:00:00Z','attributes':{'brand':{'value':'Logitech','selector':'.parameter'},'model':{'value':'M185','selector':'.parameter'},'condition':{'value':'全新','selector':'.parameter'}},'selected_specification':'灰色','sku_options':[{'text':'灰色','selected':True}]}}


def test_details_are_read_per_platform_before_identity_comparison():
    async def search(platform,query,limit):
        return {'status':'observed','products':[row(platform,'50' if platform=='jd' else '30')]}
    calls=[]
    async def fetch(url):
        calls.append(url)
        return detail(url)
    result=asyncio.run(research_purchase(search,'M185无线鼠标',['jd','pdd'],budget_yuan=100,detail_provider=fetch,inspect_details_per_platform=1))
    assert len(calls)==2
    assert len(result['detail_coverage'])==2
    assert len(result['recommendation_analysis']['identity_check']['candidate_groups'])==1
    assert all(item['structured_identity']['model']=='M185' for item in result['shortlist'])
    assert all(item['same_sku_confirmed'] is False for item in result['shortlist'])


def test_wrong_product_or_restricted_detail_cannot_fill_identity():
    for response in (detail('https://item.jd.com/999.html'), {'status':'verification_required','data':detail(row()['url'])['data']}):
        result=enrich_offer(row(),response)
        assert not result.get('brand')
        assert result['condition']=='unknown'
        assert result['detail_merge_status']=='unavailable_or_product_mismatch'


def test_research_reuses_details_in_the_same_request(monkeypatch):
    class Pool:
        calls=0
        async def search(self,platform,query,limit):
            return {'status':'observed','products':[row()]}
        async def details(self,url):
            self.calls+=1
            return detail(url)
    pool=Pool();monkeypatch.setattr(server,'browser',pool)
    result=asyncio.run(server.research_purchase('M185无线鼠标',platforms_json='["jd"]',inspect_reviews_top_k=0))
    assert pool.calls==1
    assert result['shortlist'][0]['structured_identity']['condition']=='new'


def test_explicit_detail_model_can_reject_misleading_search_title():
    async def search(platform,query,limit):
        return {'status':'observed','products':[row()]}
    async def fetch(url):
        d=detail(url);d['data']['attributes']['model']['value']='M186';return d
    result=asyncio.run(research_purchase(search,'M185无线鼠标',['jd'],detail_provider=fetch,inspect_details_per_platform=1))
    assert result['shortlist']==[]
    assert result['status']=='needs_more_evidence'
    assert result['intent_excluded'][0]['evidence_source']=='visible_product_parameter'


def test_compact_report_removes_duplicates_preserving_source_and_review_counts():
    from multimall.evidence import compact_research_report
    import json
    report={'discovery':{'per_platform':[{'platform':'jd','products':[row()]*20}]},'shortlist':[{'url':row()['url'],'detail_evidence':detail(row()['url']),'review_summary':{'sample_size':5,'quality_score':None,'review_evidence':[{'evidence_id':str(i),'text':'文本'+str(i),'source_url':row()['url'],'issue_topics':[] if i<4 else ['function_failure']} for i in range(5)]}}]}
    report['shortlist'][0]['detail_evidence']['data']['parameters']=[{'text':'重复的参数原文'*30}]*20
    result=compact_research_report(report)
    assert result['discovery']['per_platform'][0]['product_count']==20
    assert 'products' not in result['discovery']['per_platform'][0]
    assert result['shortlist'][0]['detail_evidence']['data']['attributes']['model']['value']=='M185'
    summary=result['shortlist'][0]['review_summary']
    assert summary['sample_size']==5 and summary['review_evidence_omitted']==2
    assert summary['review_evidence'][0]['evidence_id']=='4'
    assert summary['review_evidence'][0]['source_url']==row()['url']
    assert summary['quality_score'] is None
    assert len(report['discovery']['per_platform'][0]['products'])==20
    assert len(json.dumps(result))<len(json.dumps(report))


def test_compact_search_keeps_products_once_and_preserves_unknown_price():
    from multimall.evidence import compact_search_report
    unknown=row();unknown['displayed_price_yuan']=None
    report={'products':[unknown], 'products_count':1,'per_platform':[{'platform':'jd','status':'observed','products':[unknown]}]}
    result=compact_search_report(report)
    assert result['products'][0]['displayed_price_yuan'] is None
    assert result['per_platform'][0]['product_count']==1
    assert result['per_platform'][0]['priced_product_count']==0
    assert 'products' not in result['per_platform'][0]
    assert len(report['per_platform'][0]['products'])==1
