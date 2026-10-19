from pathlib import Path
import importlib.util
from bs4 import BeautifulSoup
spec=importlib.util.spec_from_file_location('discovery_queue',Path(__file__).with_name('discovery-queue.py'))
queue=importlib.util.module_from_spec(spec);spec.loader.exec_module(queue)
def row():return {'id':'one','name':'Cafe','address':'Main1'}
def event(provider,outcome,actual=True):return {'canonical_id':'one','provider':provider,'outcome':outcome,'actual_request':actual,'candidates':[]}
def test_404_is_incomplete_not_empty_search():
 assert queue.assess({'http_status':404})=='incomplete_source_error'
def test_captcha_with_200_is_block():
 assert queue.assess({'http_status':200,'text_excerpt':'Please complete the following challenge'})=='blocked'
def test_429_is_block():
 assert queue.assess({'http_status':429})=='blocked'
def test_three_empty_provider_searches_do_not_prove_no_information():
 s=queue.summary([row()],[event(p,'search_returned_no_candidates') for p in queue.PROVIDERS])
 assert s['records'][0]['outcome']=='candidate_review_required'
 assert not s['records'][0]['no_information_confirmed']
def test_two_successes_and_third_block_remain_incomplete():
 s=queue.summary([row()],[event('2gis','candidates_found'),event('bing','search_returned_no_candidates'),event('yandex_maps','skipped_provider_block',False)])
 assert s['records'][0]['successful_distinct_providers']==2
 assert s['records'][0]['actual_distinct_providers_attempted']==2
 assert s['records'][0]['outcome']=='incomplete_source_checks'
def test_404_cannot_become_no_information_even_with_review_flag():
 r={**row(),'source_review':{'completed':True,'outcome':'no_information','reviewed_by':'reviewer','reviewed_at':'2026-10-19','evidence_urls':['https://example.org']}}
 s=queue.summary([r],[event('2gis','incomplete_source_error'),event('bing','search_returned_no_candidates'),event('yandex_maps','search_returned_no_candidates')])
 assert not s['records'][0]['no_information_confirmed']
def test_latest_provider_attempt_supersedes_old_error():
 e=[event('bing','incomplete_source_error'),event('bing','search_returned_no_candidates')]
 assert queue.summary([row()],e)['records'][0]['successful_distinct_providers']==1
def test_only_http_links_are_candidates_and_identity_is_never_accepted():
 soup=BeautifulSoup('<li class="b_algo"><h2><a href="https://example.org/cafe">Cafe</a></h2></li>','html.parser')
 c=queue.candidates('bing',soup,'https://bing.com/search',row())
 assert len(c)==1 and c[0]['identity_status']=='unreviewed' and c[0]['accepted'] is False
