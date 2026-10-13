"""Decimal engineering checks with explicit evidence and scope. No LLM arithmetic."""
from decimal import Decimal, InvalidOperation
import re
import hashlib

RULE_VERSION = 'engineering-v1.0'
UNITS = {'mm':Decimal('1'),'cm':Decimal('10'),'m':Decimal('1000'),'inch':Decimal('25.4')}

def dec(v):
    try:
        d=Decimal(str(v))
        if not d.is_finite(): raise ValueError('数值必须有限')
        return d
    except (InvalidOperation, TypeError): raise ValueError(f'非法十进制值：{v}')

def fmt(d):
    return format(d.normalize(),'f') if d else '0'

def norm(f):
    if f.get('unit') not in UNITS: raise ValueError('单位缺失或不支持，请确认 mm/cm/m/inch')
    k=UNITS[f['unit']]
    n=dec(f.get('nominal'))*k
    lo=None if f.get('lower') in ('',None) else dec(f['lower'])*k
    hi=None if f.get('upper') in ('',None) else dec(f['upper'])*k
    if n<0 or (lo is not None and hi is not None and lo>hi): raise ValueError('尺寸或公差区间非法')
    return n,lo,hi

def normalized(f):
    return [None if x is None else fmt(x) for x in norm(f)]

def analyze(task, docs, drawings):
    evidence={}; issues=[]; differences=[]; findings=[]; records={}; coverage={}
    def ev(doc, loc, text, page=None):
        key=f"{doc['id']}:{loc}:{hashlib.sha256(text.encode()).hexdigest()[:10]}"
        evidence[key]={'id':key,'doc_id':doc['id'],'filename':doc['name'],'location':loc,'text':text,'page':page,'sha256':doc['sha256']}
        return key
    def add(obj,kind,department,title,detail,refs,rule='',priority='常规核查',quantity=None):
        if not refs or any(x not in evidence for x in refs): raise ValueError('无效证据，不允许生成结论')
        f={'id':f'F{len(findings)+1:03}','object':obj,'kind':kind,'department':department,'title':title,'detail':detail,
           'evidence':list(dict.fromkeys(refs)),'rule':rule,'priority':priority,'quantity':quantity}
        findings.append(f)
        return f
    prepared={}
    for role in ('old','new'):
        d=next((d for d in docs if d['role']==role),None)
        if d is None or role not in drawings:
            issues.append(f'缺少{role}图纸或提取结果'); continue
        raw=drawings[role]
        expected=task['old_rev' if role=='old' else 'new_rev']
        if raw.get('part_no')!=task['part_no'] or raw.get('revision')!=expected:
            issues.append(f"{d['name']} 的料号/版本与任务不一致"); continue
        feats={}
        for i,f0 in enumerate(raw.get('features',[])):
            f=dict(f0); fid=f.get('feature_id')
            if not isinstance(fid,str) or not fid or f.get('kind') not in ('diameter','length'):
                issues.append(f"{d['name']} 特征标识缺失或尺寸类型不支持"); continue
            key=(fid,f['kind'])
            if key in feats:
                issues.append(f'{role} 特征 {fid} 重复或一对多，须确认'); continue
            try: norm(f)
            except ValueError as e: issues.append(f"{d['name']} {fid}：{e}"); continue
            page=f.get('page')
            source=next((p for p in d['parsed']['pages'] if p.get('page',1)==page),None)
            if source is None: issues.append(f"{fid} 引用页不存在"); continue
            quote=f.get('quote') or ''
            compact=lambda s: re.sub(r'\s+','',s)
            supported=bool(quote) and compact(quote) in compact(source['text'])
            if not supported and not f.get('human_confirmed'):
                issues.append(f'{role} {fid} 原文无法自动核验，请对照页面人工确认提取字段'); continue
            if not f.get('human_confirmed'):
                numbers=re.findall(r'[+\-]?\d+(?:\.\d+)?',quote)
                if dec(f['nominal']) not in [dec(n) for n in numbers]:
                    issues.append(f'{role} {fid} 名义值与引用不一致'); continue
                if f['unit'] not in quote or any(abs(dec(f[x])) not in [abs(dec(n)) for n in numbers] for x in ('lower','upper') if f.get(x) not in ('',None)):
                    issues.append(f'{role} {fid} 单位或公差与引用不一致'); continue
                if quote.startswith('FEATURE '):
                    from parsers import local_drawing
                    exact=local_drawing([{'text':f"PART: {raw['part_no']}\nREV: {raw['revision']}\n{quote}", 'page':page}])['features'][0]
                    if norm(f)!=norm(exact) or f['feature_id']!=exact['feature_id'] or f['kind']!=exact['kind']:
                        issues.append(f'{role} {fid} 提取字段与结构化标注不一致'); continue
            f['evidence']=ev(d,source['location'],quote or source['text'],page)
            f['normalized']=normalized(f)
            feats[key]=f
        prepared[role]=feats
    old,new=prepared.get('old',{}),prepared.get('new',{})
    if not old or not new: issues.append('没有可比较的有效特征')
    for key in sorted(set(old)|set(new)):
        if key not in old or key not in new:
            issues.append(f'特征 {key[0]} 未匹配，不能推断几何新增或删除'); continue
        a,b=old[key],new[key]; an,bn=norm(a),norm(b)
        delta=bn[0]-an[0]
        tol_unknown=any(x is None for x in (*an[1:],*bn[1:]))
        tol_change=not tol_unknown and an[1:]!=bn[1:]
        status='名义值与公差变化' if delta and tol_change else '名义值变化' if delta else '公差变化' if tol_change else '公差待核查' if tol_unknown else '无实质变化'
        refs=[a['evidence'],b['evidence']]
        differences.append({'feature_id':key[0],'kind':key[1],'old':a,'new':b,'delta':fmt(delta),'status':status,
                            'tolerance':'未知，需确认' if tol_unknown else '已变化' if tol_change else '不变','evidence':refs})
        add(key[0],'事实','工程',f"{key[0]} · {status}",f"名义值 {fmt(an[0])} → {fmt(bn[0])} mm，差值 {fmt(delta)} mm；公差"+('未知' if tol_unknown else '变化' if tol_change else '不变'),refs)
        if delta or tol_change or tol_unknown:
            add(key[0],'待核查','工程','核查装配与工艺适用性','需提供配合件、工艺及验证依据；当前不能认定必须换模、调参或报废。',refs,'BR06')
    for role in ('bom','inspection','inventory','wip','orders'):
        ds=[d for d in docs if d['role']==role]
        coverage[role]='已覆盖' if ds else '未覆盖'
        recs=[]; seen={}; invalid=False
        for d in ds:
            parsed=d['parsed']
            if not parsed['mapping_confirmed']:
                issues.append(f"{d['name']} 字段映射尚未确认"); invalid=True; continue
            for row in parsed['rows']:
                vals={parsed['mapping'].get(k,k):v for k,v in row['values'].items()}
                rid=vals.get('item_id' if role=='inspection' else 'record_id')
                try:
                    from parsers import REQUIRED
                    if any(not vals.get(k) for k in REQUIRED[role]): raise ValueError('必需字段缺失')
                    if role!='inspection' and dec(vals['quantity'])<0: raise ValueError('数量为负')
                    if role=='inspection': norm(vals)
                    if vals.get('part_no')==task['part_no'] and vals.get('revision') not in (task['old_rev'],task['new_rev']): raise ValueError('目标零件版本未知')
                    if rid in seen:
                        if vals!=seen[rid]: raise ValueError('相同编号内容冲突，该类汇总已停止')
                        continue
                    seen[rid]=dict(vals)
                    vals['evidence']=ev(d,row['location'],' | '.join(f'{k}={v}' for k,v in row['values'].items()))
                    recs.append(vals)
                except ValueError as e:
                    issues.append(f"{d['name']} {row['location']}：{e}"); invalid=True
        records[role]=[] if invalid else recs
        if invalid: coverage[role]='资料异常，未完成'
    scope=task.get('scope')
    scope_refs=[]
    for d in docs:
        if d['role'] in ('ecn','process'):
            for p in d['parsed']['pages']:
                eid=ev(d,p['location'],p['text'],p.get('page'))
                if d['role']=='ecn': scope_refs.append(eid)
    # User confirmation is itself an auditable input, never an inferred order range.
    coverage['scope']='已确认精确订单清单' if scope is not None else '未覆盖'
    scope_ev='manual:scope'
    if scope is not None:
        evidence[scope_ev]={'id':scope_ev,'doc_id':None,'filename':'人工确认生效范围','location':'任务输入',
                            'text':f"订单清单：{', '.join(scope) or '空清单'}；依据：{task.get('scope_reason','')}", 'page':None,'sha256':None}
        scope_refs=[scope_ev]+scope_refs
    for r in records['inspection']:
        if r['part_no']!=task['part_no']: continue
        b=next((f for (fid,_),f in new.items() if fid==r['feature_id']),None)
        if b is None: continue
        in_scope=r.get('order_id') in (scope or [])
        applies=r['revision']==task['new_rev'] or in_scope
        if applies:
            if any(x is None for x in (*norm(r)[1:],*norm(b)[1:])):
                add(r['item_id'],'待核查','质量','检验公差信息不完整','缺少公差，不能断言检验要求一致。',[r['evidence'],b['evidence']],'BR05')
            elif norm(r)!=norm(b):
                refs=[r['evidence'],b['evidence']]+(scope_refs if in_scope else [])
                add(r['item_id'],'规则推导','质量','检验要求不一致',f"检验 {r['nominal']} {r['unit']} 与新版 {b['nominal']} {b['unit']} 的要求不同。建议质量部门更新评审，尚未发布新标准。",refs,'BR01','优先处理')
    quantities={}
    for role,label in [('inventory','库存'),('wip','在制品')]:
        total=Decimal(0)
        for r in records[role]:
            if r['part_no']!=task['part_no'] or r['revision']!=task['old_rev']: continue
            total+=dec(r['quantity'])
            assigned=r.get('order_id')
            conflict=scope is not None and assigned in scope
            refs=[r['evidence']]+[f['evidence'] for f in new.values()]
            if conflict: refs+=scope_refs
            add(r['record_id'],'规则推导' if conflict else '待核查','生产' if role=='wip' else '物料管理',
                f"旧版{label}与订单版本冲突" if conflict else f"旧版{label}用途待核查",
                f"{r['revision']} 版 {r['quantity']} 件；"+(f'已分配至生效订单 {assigned}，请核查换版安排。' if conflict else f"分配订单：{assigned or '未分配'}。须核查用途及处置方案，不能认定报废。"),
                refs,'BR03' if conflict else 'BR02' if role=='inventory' else 'BR05', '优先处理' if conflict else '常规核查',r['quantity'])
        quantities[role]=fmt(total) if coverage[role]=='已覆盖' else None
    order_views=[]
    for r in records['orders']:
        direct=r['part_no']==task['part_no']
        paths=[b for b in records['bom'] if b['product_no']==r['part_no'] and b['product_rev']==r['revision'] and b['part_no']==task['part_no']]
        if not direct and not paths: continue
        refs=[r['evidence']]+[b['evidence'] for b in paths]+scope_refs
        state='资料不足：未确认生效范围' if scope is None else '生效范围内' if r['order_id'] in scope else '本次生效范围外'
        target_revs=[r['revision']] if direct else [b['revision'] for b in paths]
        order_views.append({'order_id':r['order_id'],'state':state,'required_revisions':target_revs,
                            'path':r['part_no']+(' → '+task['part_no'] if paths else ''),'evidence':refs})
        if state=='生效范围内' and any(x!=task['new_rev'] for x in target_revs):
            add(r['record_id'],'规则推导','生产','订单需求版本与变更范围冲突',f"订单 {r['order_id']} 要求版本 {', '.join(target_revs)}，确认范围要求 {task['new_rev']}。",refs,'BR03','优先处理')
    if scope is not None:
        missing=set(scope)-{r['order_id'] for r in order_views}
        if missing: issues.append('生效订单缺少可关联需求行：'+', '.join(sorted(missing)))
    return {'differences':differences,'findings':findings,'evidence':evidence,'issues':issues,
            'coverage':coverage,'quantities':quantities,'orders':order_views,'drawings':drawings,
            'limits':['仅沿显式字段关联；BOM 当前支持单层展开。','缺失资料表示未覆盖；所有数量为待核查数量，不是损失。','完成评审不代表变更获批或生产动作已执行。']}
