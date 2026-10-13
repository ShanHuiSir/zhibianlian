import copy
import json
import threading
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app as service
import storage as db
from parsers import local_drawing

client=TestClient(service.app)
ROOT=Path(__file__).resolve().parents[1]

def call(url,body=None,method='POST',status=200):
    r=client.request(method,url,json=body)
    assert r.status_code==status,r.text
    return r.json()

def prepared():
    t=call('/api/tasks',dict(name='test',part_no='HSG-001',old_rev='A',new_rev='B',mode='local'))
    tid=t['id'];s=call(f'/api/tasks/{tid}/sample',dict(revision=t['revision']))
    for d in s['documents']:
        if d['parsed']['rows']:
            t=db.get(tid,'task')
            call(f'/api/tasks/{tid}/files/{d["id"]}/mapping',dict(revision=t['revision'],mapping=d['parsed']['mapping']),method='PATCH')
    t=db.get(tid,'task')
    return call(f'/api/tasks/{tid}',dict(revision=t['revision'],scope=['SO-NEW-001'],scope_reason='ECN-001'),method='PATCH')

def completed(t):
    r=call(f'/api/tasks/{t["id"]}/runs',dict(revision=t['revision']))
    until=time.monotonic()+5
    while r['state']=='分析中' and time.monotonic()<until:
        time.sleep(.01);r=db.get(r['id'],'run')
    assert r['state']=='待评审',r.get('error') or r.get('result',{}).get('issues')
    return r

def test_end_to_end_review_export_and_history():
    t=prepared();r=completed(t);url=f'/api/tasks/{t["id"]}/runs/{r["id"]}'
    for f in r['result']['findings']:
        r=call(url+'/decisions',dict(review_revision=r['review_revision'],finding_id=f['id'],decision='待核查' if f['kind']=='待核查' else '采纳',department=f['department'],needed='分配清单与验证依据'))
    r=call(url+'/finish',dict(review_revision=r['review_revision']))
    rep=call(url+'/export',dict(review_revision=r['review_revision']))
    assert rep==call(url+'/export',dict(review_revision=r['review_revision']))
    original=(db.DATA/'reports'/rep['id']/'report.pdf').read_bytes()
    assert original.startswith(b'%PDF')
    t2=call(f'/api/tasks/{t["id"]}',dict(revision=t['revision'],new_rev='C'),method='PATCH')
    assert t2['state']=='草稿'
    call(url+'/decisions',dict(review_revision=r['review_revision'],finding_id='F001',decision='采纳'),status=409)
    assert (db.DATA/'reports'/rep['id']/'report.pdf').read_bytes()==original

def test_review_stale_rejected_and_no_duplicate_actions():
    t=prepared();r=completed(t);url=f'/api/tasks/{t["id"]}/runs/{r["id"]}/decisions'
    b=dict(review_revision=0,finding_id='F001',decision='采纳')
    r=call(url,b);call(url,b,status=409)
    b['review_revision']=r['review_revision'];r=call(url,b)
    assert len(service.reports.actions(r))==1

def test_no_key_does_not_fallback():
    t=prepared();t=call(f'/api/tasks/{t["id"]}',dict(revision=t['revision'],mode='deepseek'),method='PATCH')
    x=call(f'/api/tasks/{t["id"]}/runs',dict(revision=t['revision'],consent=True),status=400)
    assert 'API Key' in x['detail']
    assert db.get(t['id'],'task')['run_id'] is None

def test_cross_task_file_and_run_access():
    a=prepared();b=prepared();r=completed(a)
    call(f'/api/tasks/{b["id"]}/runs/{r["id"]}',method='GET',status=404)
    did=a['documents'][0]
    response=client.get(f'/api/tasks/{b["id"]}/files/{did}/original')
    assert response.status_code==404

def test_cancel_late_response_and_duplicate_start(monkeypatch):
    t=prepared();original=service.local_drawing;entered=threading.Event();release=threading.Event()
    def delayed(pages):
        entered.set();release.wait(3);return original(pages)
    monkeypatch.setattr(service,'local_drawing',delayed)
    r=call(f'/api/tasks/{t["id"]}/runs',dict(revision=t['revision']))
    assert entered.wait(1)
    duplicate=call(f'/api/tasks/{t["id"]}/runs',dict(revision=t['revision']))
    assert duplicate['id']==r['id']
    call(f'/api/tasks/{t["id"]}/runs/{r["id"]}/cancel')
    release.set();time.sleep(.08)
    late=db.get(r['id'],'run')
    assert late['state']=='已取消' and not late.get('result')

def test_same_file_dedup_and_explicit_replacement():
    t=prepared();did=t['documents'][0];doc=db.get(did,'doc')
    same=client.post(f'/api/tasks/{t["id"]}/files',data={'revision':t['revision'],'role':'old'},files={'file':(doc['name'],Path(doc['path']).read_bytes(),'application/pdf')})
    assert same.status_code==200 and same.json()['duplicate']
    other=client.post(f'/api/tasks/{t["id"]}/files',data={'revision':t['revision'],'role':'old'},files={'file':(doc['name'],(ROOT/'samples/HSG-001_B.pdf').read_bytes(),'application/pdf')})
    assert other.status_code==400 and '同名' in other.json()['detail']

def test_mapping_requires_confirmation():
    t=call('/api/tasks',dict(name='mapping',part_no='HSG-001',old_rev='A',new_rev='B',mode='local'))
    s=call(f'/api/tasks/{t["id"]}/sample',dict(revision=t['revision']))
    call(f'/api/tasks/{t["id"]}/runs',dict(revision=s['task']['revision']),status=400)

def test_input_correction_invalidates_and_recomputes():
    t=prepared();r=completed(t);drawing=copy.deepcopy(r['result']['drawings']['new'])
    drawing['features'][0]['nominal']='5.0'
    call(f'/api/tasks/{t["id"]}/corrections',dict(revision=t['revision'],role='new',drawing=drawing,reason='人工模拟验证，不是模型识别值'))
    t=db.get(t['id'],'task');r2=completed(t)
    assert r2['result']['differences'][0]['delta']=='1'
    assert r2['raw_drawings']['new']['features'][0]['nominal']=='4.5'
    assert not r2['decisions']

def test_cross_origin_mutation_blocked():
    r=client.post('/api/tasks',json={'name':'x'},headers={'Origin':'https://evil.example'})
    assert r.status_code==403
