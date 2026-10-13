import copy
import hashlib
import json
from pathlib import Path
import pytest
from engine import analyze, norm, fmt
from parsers import parse_file,local_drawing
from reports import csv_report
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def case():
    task=dict(part_no='HSG-001',old_rev='A',new_rev='B',scope=['SO-NEW-001'],scope_reason='ECN-001')
    docs=[];drawings={}
    for i,item in enumerate(json.loads((ROOT/'samples/manifest.json').read_text())):
        p=ROOT/'samples'/item['file'];parsed=parse_file(p);parsed['mapping_confirmed']=True
        d=dict(id=f'D{i}',role=item['role'],name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),parsed=parsed)
        docs.append(d)
        if d['role'] in ('old','new'): drawings[d['role']]=local_drawing(parsed['pages'])
    return task,docs,drawings

def test_main_case(case):
    r=analyze(*case)
    assert not r['issues']
    assert r['differences'][0]['delta']=='0.5'
    assert r['differences'][0]['tolerance']=='不变'
    assert r['quantities']==dict(inventory='600',wip='200')
    assert any(f['object']=='QI-001' and f['priority']=='优先处理' and len(f['evidence'])>=2 for f in r['findings'])
    assert not any(f['object'] in ('INV-B-001','INV-X-001') for f in r['findings'])
    assert next(o for o in r['orders'] if o['order_id']=='SO-OLD-001')['state']=='本次生效范围外'
    assert not any(f['priority']=='优先处理' and f['object']=='WIP-A-001' for f in r['findings'])

def setfeature(case,role,**values):
    task,docs,drawings=case
    f=drawings[role]['features'][0];f.update(values)
    q=f"FEATURE H1 diameter {f['nominal']} {f['unit']} LOW {f['lower']} HIGH {f['upper']}"
    d=next(d for d in docs if d['role']==role)
    d['parsed']['pages'][0]['text']=d['parsed']['pages'][0]['text'].replace(f['quote'],q)
    f['quote']=q

def test_changed_input_changes_result(case):
    setfeature(case,'new',nominal='5.0')
    assert analyze(*case)['differences'][0]['delta']=='1'

def test_unit_equivalence(case):
    setfeature(case,'old',nominal='0.4',unit='cm',lower='-0.01',upper='0.01')
    setfeature(case,'new',nominal='4.0')
    d=analyze(*case)['differences'][0]
    assert d['status']=='无实质变化' and d['delta']=='0'

def test_tolerance_only(case):
    setfeature(case,'new',nominal='4.0',lower='-0.05',upper='0.05')
    d=analyze(*case)['differences'][0]
    assert d['status']=='公差变化' and d['delta']=='0'

def test_missing_tolerance_not_zero(case):
    case[2]['new']['features'][0].update(lower=None,upper=None)
    r=analyze(*case)
    # The structured source contains tolerance: inconsistent extraction is blocked.
    assert r['issues']

@pytest.mark.parametrize('bad', [None,'um','degree'])
def test_missing_or_unknown_unit_blocks(case,bad):
    case[2]['new']['features'][0]['unit']=bad
    assert analyze(*case)['issues']

def test_duplicate_feature_blocks(case):
    case[2]['new']['features'].append(copy.deepcopy(case[2]['new']['features'][0]))
    assert any('重复' in x for x in analyze(*case)['issues'])

def test_version_conflict_blocks(case):
    case[2]['new']['revision']='C'
    assert any('版本' in x for x in analyze(*case)['issues'])

def test_missing_inventory_is_uncovered(case):
    task,docs,drawings=case
    r=analyze(task,[d for d in docs if d['role']!='inventory'],drawings)
    assert r['coverage']['inventory']=='未覆盖' and r['quantities']['inventory'] is None

def test_no_scope_no_order_inference(case):
    case[0]['scope']=None
    r=analyze(*case)
    assert r['coverage']['scope']=='未覆盖'
    assert all(o['state'].startswith('资料不足') for o in r['orders'])

def test_duplicate_quantity_deduplicated(case):
    d=next(d for d in case[1] if d['role']=='inventory')
    d['parsed']['rows'].append(copy.deepcopy(d['parsed']['rows'][0]))
    assert analyze(*case)['quantities']['inventory']=='600'

def test_conflicting_quantity_stops_summary(case):
    d=next(d for d in case[1] if d['role']=='inventory')
    other=copy.deepcopy(d['parsed']['rows'][0]);other['values']['quantity']='700'
    d['parsed']['rows'].append(other)
    r=analyze(*case)
    assert r['issues'] and r['quantities']['inventory'] is None

def test_unassigned_and_assigned_wip_differ(case):
    d=next(d for d in case[1] if d['role']=='wip')
    d['parsed']['rows'][0]['values']['order_id']='SO-NEW-001'
    assert any(f['object']=='WIP-A-001' and f['priority']=='优先处理' for f in analyze(*case)['findings'])

def test_forged_evidence_rejected(case):
    case[2]['new']['features'][0]['page']=999
    r=analyze(*case)
    assert any('引用页不存在' in i for i in r['issues'])
    assert not r['differences']

def test_hallucinated_number_rejected(case):
    case[2]['new']['features'][0]['nominal']='99'
    assert any('名义值与引用不一致' in i for i in analyze(*case)['issues'])

def test_tolerance_sign_invention_rejected(case):
    case[2]['new']['features'][0]['lower']='0.1'
    assert any('结构化标注不一致' in i for i in analyze(*case)['issues'])

def test_case_sensitive_and_leading_zero(case):
    case[0]['scope']=['so-new-001']
    r=analyze(*case)
    assert all(o['state']=='本次生效范围外' for o in r['orders'])
    assert r['issues']

def test_formula_safe_csv():
    r=dict(id='R1',result={'findings':[dict(id='F1',title='=1+1',department='质量',priority='常规核查')]},decisions={'F1':dict(decision='采纳',department='质量')})
    data=csv_report(r).decode('utf-8-sig')
    assert "'=1+1" in data and '质量' in data

def test_decimal_exact():
    assert fmt(norm(dict(nominal='0.1',unit='inch',lower=None,upper=None))[0])=='2.54'
    with pytest.raises(ValueError): norm(dict(nominal='NaN',unit='mm'))

def test_multiple_features_have_distinct_same_page_evidence(case):
    for role,n in [('old','8.0'),('new','8.5')]:
        f=dict(feature_id='H2',kind='length',nominal=n,lower='-0.2',upper='0.2',unit='mm',page=1,
               quote=f'FEATURE H2 length {n} mm LOW -0.2 HIGH 0.2')
        case[2][role]['features'].append(f)
        d=next(d for d in case[1] if d['role']==role)
        d['parsed']['pages'][0]['text']+='\n'+f['quote']
    r=analyze(*case)
    assert not r['issues'] and len(r['differences'])==2
    assert r['differences'][0]['evidence'][0]!=r['differences'][1]['evidence'][0]
    for d in r['differences']:
        assert all(d['feature_id'] in r['evidence'][e]['text'] for e in d['evidence'])

def test_actual_missing_tolerance_stays_unknown(case):
    for role in ('old','new'):
        f=case[2][role]['features'][0]
        d=next(d for d in case[1] if d['role']==role)
        q=f"FEATURE H1 diameter {f['nominal']} mm LOW unknown HIGH unknown"
        d['parsed']['pages'][0]['text']=d['parsed']['pages'][0]['text'].replace(f['quote'],q)
        f.update(lower=None,upper=None,quote=q)
    r=analyze(*case)
    assert r['differences'][0]['tolerance']=='未知，需确认'
    assert any(f['title']=='检验公差信息不完整' for f in r['findings'])
