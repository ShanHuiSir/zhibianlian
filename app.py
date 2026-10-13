"""Single-user localhost application. No production-system writes."""
import copy
import hashlib
import json
import threading
import time
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
import fitz
import engine
import model
import reports
import storage as db
from parsers import parse_file, local_drawing, ROLES, REQUIRED

ROOT=Path(__file__).parent
app=FastAPI(title='智变链',version='1.0.0')
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])
db.recover()

@app.middleware('http')
async def local_only(request:Request,call_next):
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD') and origin and origin not in (f'http://{request.headers.get("host")}', f'https://{request.headers.get("host")}'):
        return JSONResponse({'detail':'拒绝跨站写入'},status_code=403)
    length=request.headers.get('content-length')
    if length and int(length)>22*1024*1024: return JSONResponse({'detail':'请求超过 22 MB'},status_code=413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(KeyError)
async def missing(req,exc): return JSONResponse({'detail':'对象不存在'},status_code=404)
@app.exception_handler(ValueError)
async def invalid(req,exc): return JSONResponse({'detail':str(exc)},status_code=400)

def owned(id,task,kind):
    x=db.get(id,kind)
    if x['task_id']!=task: raise HTTPException(404,'对象不属于当前任务')
    return x

def current_docs(t): return [db.get(i,'doc') for i in t['documents']]
def latest(t): return db.get(t['run_id'],'run') if t.get('run_id') else None
def check_edit(t,revision):
    if revision!=t['revision']: raise HTTPException(409,'输入版本已变化，请刷新页面')
    r=latest(t)
    if r and r['state']=='分析中': raise HTTPException(409,'请先取消分析再修改资料')
def bump(t):
    t['revision']+=1;t['updated']=db.now();db.put(t,'task')
def public_task(t):
    t=copy.deepcopy(t);r=latest(t)
    t['state']=r['state'] if r and r['input_revision']==t['revision'] else '草稿'
    return t

@app.get('/api/config')
def cfg(): return model.public_config()

@app.get('/api/tasks')
def tasks(): return [public_task(t) for t in db.all_of('task')]

@app.post('/api/tasks')
def create(body:dict):
    name=str(body.get('name','')).strip()
    if not 1<=len(name)<=80: raise ValueError('任务名称须为 1 至 80 字')
    mode=body.get('mode','local')
    if mode not in ('deepseek','local'): raise ValueError('分析模式无效')
    t={'id':db.uid('T'),'name':name,'part_no':str(body.get('part_no','')).strip(),'old_rev':str(body.get('old_rev','')).strip(),
       'new_rev':str(body.get('new_rev','')).strip(),'mode':mode,'simulated':bool(body.get('simulated',False)),
       'scope':None,'scope_reason':'','documents':[],'revision':1,'run_id':None,'corrections':{},'updated':db.now()}
    if t['old_rev'] and t['old_rev']==t['new_rev']: raise ValueError('新旧版本不能相同')
    db.put(t,'task');db.event(t['id'],'创建任务');return t

@app.get('/api/tasks/{tid}')
def detail(tid):
    t=db.get(tid,'task')
    return {'task':public_task(t),'documents':current_docs(t),'run':latest(t),
            'history':[{'id':r['id'],'input_revision':r['input_revision'],'state':r['state'],'started':r['started']} for r in db.all_of('run') if r['task_id']==tid],
            'reports':[r for r in db.all_of('report') if r['task_id']==tid]}

@app.patch('/api/tasks/{tid}')
def edit(tid,body:dict):
    with db.LOCK:
        t=db.get(tid,'task');check_edit(t,body.get('revision'))
        for k in ('name','part_no','old_rev','new_rev','scope_reason'):
            if k in body: t[k]=str(body[k]).strip()
        if 'scope' in body:
            if body['scope'] is not None and not isinstance(body['scope'],list): raise ValueError('生效范围须为精确订单清单')
            t['scope']=None if body['scope'] is None else list(dict.fromkeys(str(x).strip() for x in body['scope'] if str(x).strip()))
            if t['scope'] is not None and not t['scope_reason']: raise ValueError('确认生效范围必须填写依据')
        if 'mode' in body:
            if body['mode'] not in ('local','deepseek'): raise ValueError('模式无效')
            t['mode']=body['mode']
        if not 1<=len(t['name'])<=80 or not t['old_rev'] or t['old_rev']==t['new_rev']: raise ValueError('任务名称或版本无效')
        bump(t);db.event(tid,'修正任务输入',revision=t['revision']);return public_task(t)

def import_bytes(t,name,role,raw,replace=None):
    if role not in ROLES: raise ValueError('资料角色无效')
    if not raw or len(raw)>20*1024*1024: raise ValueError('空文件或单文件超过 20 MB')
    docs=current_docs(t);sha=hashlib.sha256(raw).hexdigest()
    same=next((d for d in docs if d['role']==role and d['sha256']==sha),None)
    if same: return same,False
    if replace and replace not in t['documents']: raise ValueError('待替换文件不在当前输入')
    remaining=[d for d in docs if d['id']!=replace]
    if any(d['name']==name for d in remaining): raise ValueError('同名不同内容，请明确选择替换文件')
    if role in ('old','new') and any(d['role']==role for d in remaining): raise ValueError('同版图纸已存在，请明确替换')
    if len(remaining)>=10 or sum(d['size'] for d in remaining)+len(raw)>100*1024*1024: raise ValueError('任务资料超过 10 份或 100 MB')
    id=db.uid('D');directory=db.DATA/'files'/t['id'];directory.mkdir(parents=True,exist_ok=True)
    path=directory/(id+Path(name).suffix.lower());path.write_bytes(raw)
    try: parsed=parse_file(path)
    except Exception as e:
        path.unlink(missing_ok=True)
        raise ValueError('文件解析失败：'+str(e)) from e
    pdfpages=sum(len(d['parsed']['pages']) for d in remaining if d['name'].lower().endswith('.pdf'))+(len(parsed['pages']) if path.suffix=='.pdf' else 0)
    if pdfpages>30 or sum(len(d['parsed']['rows']) for d in remaining)+len(parsed['rows'])>1000:
        path.unlink();raise ValueError('任务超过 30 页 PDF 或 1000 条表格记录')
    if role in REQUIRED and not parsed['rows']: path.unlink();raise ValueError('业务表格请使用 CSV 或 XLSX')
    d={'id':id,'task_id':t['id'],'name':name,'role':role,'size':len(raw),'sha256':sha,'path':str(path),'parsed':parsed,'created':db.now()}
    db.put(d,'doc');t['documents']=[d['id'] for d in remaining]+[id];bump(t)
    db.event(t['id'],'导入资料',doc_id=id,sha256=sha,replace=replace);return d,True

@app.post('/api/tasks/{tid}/files')
async def upload(tid,role:str=Form(...),revision:int=Form(...),replace:str=Form(''),file:UploadFile=File(...)):
    raw=await file.read(20*1024*1024+1)
    with db.LOCK:
        t=db.get(tid,'task');check_edit(t,revision)
        d,changed=import_bytes(t,Path(file.filename.replace('\\','/')).name,role,raw,replace or None)
        return {'document':d,'duplicate':not changed,'revision':t['revision']}

@app.post('/api/tasks/{tid}/sample')
def sample(tid,body:dict):
    with db.LOCK:
        t=db.get(tid,'task');check_edit(t,body.get('revision'))
        if t['documents']: raise ValueError('请在空任务载入样例，避免混合资料')
        t.update(part_no='HSG-001',old_rev='A',new_rev='B',simulated=True)
        for item in json.loads((ROOT/'samples'/'manifest.json').read_text()):
            import_bytes(t,item['file'],item['role'],(ROOT/'samples'/item['file']).read_bytes())
        db.put(t,'task');return detail(tid)

@app.delete('/api/tasks/{tid}/files/{did}')
def remove(tid,did,revision:int):
    with db.LOCK:
        t=db.get(tid,'task');check_edit(t,revision);owned(did,tid,'doc')
        if did not in t['documents']: raise ValueError('文件不是当前输入')
        t['documents'].remove(did);bump(t);db.event(tid,'移出资料',doc_id=did);return {'ok':True}

@app.patch('/api/tasks/{tid}/files/{did}/mapping')
def mapping(tid,did,body:dict):
    with db.LOCK:
        t=db.get(tid,'task');check_edit(t,body.get('revision'));d=owned(did,tid,'doc')
        if did not in t['documents']: raise ValueError('历史文件不能修改')
        mp=body.get('mapping')
        if not isinstance(mp,dict) or set(mp)!=set(d['parsed']['headers']): raise ValueError('映射必须涵盖全部表头')
        if len(set(mp.values()))!=len(mp): raise ValueError('多个列不能映射到同一字段')
        if any(k not in mp.values() for k in REQUIRED.get(d['role'],[])): raise ValueError('缺少必需字段映射')
        d['parsed']['mapping']=mp;d['parsed']['mapping_confirmed']=True;db.put(d,'doc');bump(t)
        db.event(tid,'确认字段映射',doc_id=did,revision=t['revision']);return {'ok':True}

@app.post('/api/tasks/{tid}/corrections')
def correct(tid,body:dict):
    with db.LOCK:
        t=db.get(tid,'task');check_edit(t,body.get('revision'));role=body.get('role');r=latest(t)
        if role not in ('old','new') or not r or not r.get('result'): raise ValueError('请先完成一次提取')
        if not str(body.get('reason','')).strip(): raise ValueError('请填写人工修正依据')
        drawing=body.get('drawing');doc=next(d for d in current_docs(t) if d['role']==role)
        if not isinstance(drawing,dict) or not isinstance(drawing.get('features'),list): raise ValueError('提取字段格式错误')
        for f in drawing['features']: engine.norm(f);f['human_confirmed']=True
        t['corrections'][role]={'sha256':doc['sha256'],'original':r['result']['drawings'].get(role),'value':drawing,'reason':body['reason'],'time':db.now()}
        bump(t);db.event(tid,'人工修正提取字段',role=role,reason=body['reason']);return {'ok':True}

def worker(rid,cfg=None):
    start=time.monotonic();deadline=start+600
    r=db.get(rid,'run');drawings={};raw_drawings={};calls=[];cfg=cfg or model.config()
    def cancelled(): return db.get(rid,'run')['state']!='分析中'
    def progress(stage):
        with db.LOCK:
            rr=db.get(rid,'run')
            if rr['state']!='分析中': raise InterruptedError('已取消')
            if time.monotonic()>deadline: raise TimeoutError('整轮分析超过 10 分钟')
            rr['stage']=stage;rr['stages'].append({'stage':stage,'time':db.now()});db.put(rr,'run')
    try:
        for idx,role in enumerate(('old','new')):
            d=next(d for d in r['docs'] if d['role']==role)
            progress(f"{'DeepSeek 识图' if r['task']['mode']=='deepseek' else '本地结构化解析'} · {idx+1}/2 · {d['name']}")
            if r['task']['mode']=='deepseek':
                drawings[role],stats=model.extract(d['path'],d['parsed']['pages'],cancelled,progress,deadline,cfg)
                calls.extend([{'document':d['name'],**c} for c in stats])
            else: drawings[role]=local_drawing(d['parsed']['pages'])
            raw_drawings[role]=copy.deepcopy(drawings[role])
            correction=r['corrections'].get(role)
            if correction and correction['sha256']==d['sha256']:
                drawings[role]=copy.deepcopy(correction['value'])
        progress('十进制尺寸比对与业务关联')
        result=engine.analyze(r['task'],r['docs'],drawings)
        progress('核验来源与生成结果')
        with db.LOCK:
            rr=db.get(rid,'run')
            if rr['state']!='分析中': return
            rr.update(result=result,raw_drawings=raw_drawings,calls=calls,state='待补充' if result['issues'] else '待评审',ended=db.now(),seconds=round(time.monotonic()-start,3),stage='分析完成')
            db.put(rr,'run');db.event(rr['task_id'],'分析完成',run_id=rid)
    except InterruptedError: return
    except Exception as e:
        with db.LOCK:
            rr=db.get(rid,'run')
            if rr['state']!='分析中': return
            msg=str(e) if isinstance(e,(ValueError,TimeoutError)) else f'分析失败（{type(e).__name__}），请检查资料格式并重试。'
            rr.update(state='失败',error=msg,ended=db.now(),seconds=round(time.monotonic()-start,3),calls=calls)
            db.put(rr,'run');db.event(rr['task_id'],'分析失败',run_id=rid,error=msg)

@app.post('/api/tasks/{tid}/runs')
def start_run(tid,body:dict):
    with db.LOCK:
        t=db.get(tid,'task');r=latest(t)
        if r and r['state']=='分析中': return r
        check_edit(t,body.get('revision'))
        for rr in db.all_of('run'):
            if rr['state']=='分析中': raise HTTPException(409,'已有其他任务正在分析')
        if not t['part_no'] or not t['old_rev'] or not t['new_rev']: raise ValueError('请补全料号和版本')
        docs=current_docs(t)
        if any(not any(d['role']==role for d in docs) for role in ('old','new')): raise ValueError('请导入新旧两份图纸')
        if any(not d['parsed']['mapping_confirmed'] for d in docs): raise ValueError('请先确认所有业务表格字段映射')
        c=model.public_config()
        if t['mode']=='deepseek' and not c['configured']: raise ValueError('未配置 DeepSeek API Key，不会回退为预设结果。')
        if t['mode']=='deepseek' and not body.get('consent'): raise ValueError('需确认将当前两份图纸图片及文本发送给 DeepSeek')
        r={'id':db.uid('R'),'task_id':tid,'input_revision':t['revision'],'task':copy.deepcopy(t),'docs':docs,'corrections':copy.deepcopy(t['corrections']),
           'state':'分析中','stage':'准备输入快照','stages':[],'started':db.now(),'review_revision':0,'decisions':{},'review_history':[],
           'config':{'model':c['model'] if t['mode']=='deepseek' else '未调用模型','base_url':c['base_url'] if t['mode']=='deepseek' else None,
                     'prompt_version':model.PROMPT_VERSION,'rule_version':engine.RULE_VERSION,'cache':'none'}}
        db.put(r,'run');t['run_id']=r['id'];db.put(t,'task');db.event(tid,'开始分析',run_id=r['id'])
        threading.Thread(target=worker,args=(r['id'],model.config()),daemon=True).start();return r

@app.get('/api/tasks/{tid}/runs/{rid}')
def run(tid,rid): return owned(rid,tid,'run')

@app.post('/api/tasks/{tid}/runs/{rid}/cancel')
def cancel(tid,rid):
    with db.LOCK:
        r=owned(rid,tid,'run')
        if r['state']=='分析中': r.update(state='已取消',ended=db.now(),stage='用户取消');db.put(r,'run');db.event(tid,'取消分析',run_id=rid)
        return r

def reviewable(t,r,body):
    if t['run_id']!=r['id'] or t['revision']!=r['input_revision']: raise HTTPException(409,'这是历史分析，请对最新输入重新分析')
    if r['review_revision']!=body.get('review_revision'): raise HTTPException(409,'评审版本已变化，请刷新页面')
    if r['state'] not in ('待评审','已评审'): raise ValueError('请先解决待补充问题并重新分析')

@app.post('/api/tasks/{tid}/runs/{rid}/decisions')
def decision(tid,rid,body:dict):
    with db.LOCK:
        t=db.get(tid,'task');r=owned(rid,tid,'run');reviewable(t,r,body)
        f=next((f for f in r['result']['findings'] if f['id']==body.get('finding_id')),None)
        if not f: raise ValueError('结论不存在')
        if any(e not in r['result']['evidence'] for e in f['evidence']): raise ValueError('证据无效')
        action=body.get('decision')
        if action not in ('采纳','修改','驳回','待核查'): raise ValueError('评审决定无效')
        if action in ('修改','驳回') and not body.get('reason','').strip(): raise ValueError('修改或驳回须填写理由')
        if action=='修改' and not body.get('text','').strip(): raise ValueError('请填写人工意见')
        if action=='待核查' and (not body.get('needed','').strip() or not body.get('department','').strip()): raise ValueError('待核查须填写责任部门和待补资料')
        d={k:str(body.get(k,'')).strip() for k in ('decision','text','reason','department','needed')}
        d.update(time=db.now(),finding_id=f['id']);d['department']=d['department'] or f['department']
        r['decisions'][f['id']]=d;r['review_history'].append(d);r['review_revision']+=1;r['state']='待评审'
        db.put(r,'run');db.event(tid,'保存人工评审',run_id=rid,finding_id=f['id']);return r

@app.post('/api/tasks/{tid}/runs/{rid}/finish')
def finish(tid,rid,body:dict):
    with db.LOCK:
        t=db.get(tid,'task');r=owned(rid,tid,'run');reviewable(t,r,body)
        if r['result']['issues'] or any(f['id'] not in r['decisions'] for f in r['result']['findings']): raise ValueError('仍有待补问题或未处理结论')
        r['state']='已评审';r['review_revision']+=1;db.put(r,'run');db.event(tid,'完成本轮评审',run_id=rid);return r

@app.get('/api/tasks/{tid}/runs/{rid}/actions')
def action_list(tid,rid): return reports.actions(owned(rid,tid,'run'))

@app.post('/api/tasks/{tid}/runs/{rid}/export')
def export(tid,rid,body:dict):
    with db.LOCK:
        r=owned(rid,tid,'run');t=db.get(tid,'task')
        if r['state']=='分析中': raise ValueError('请等待分析结束或取消')
        if r['review_revision']!=body.get('review_revision'): raise HTTPException(409,'评审发生变化，请刷新后导出')
        historical=t['revision']!=r['input_revision'] or t['run_id']!=rid
        existing=next((x for x in db.all_of('report') if x['run_id']==rid and x['review_revision']==r['review_revision']),None)
        if existing: return existing
        id=db.uid('REP');directory=db.DATA/'reports'/id;directory.mkdir(parents=True)
        pdf=directory/'report.pdf';csv=directory/'actions.csv'
        reports.pdf_report(r,pdf,id);csv.write_bytes(reports.csv_report(r))
        (directory/'snapshot.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
        obj={'id':id,'task_id':tid,'run_id':rid,'review_revision':r['review_revision'],'created':db.now(),'historical':historical,
             'status':r['state'],'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest()}
        db.put(obj,'report');db.event(tid,'导出报告',report_id=id);return obj

@app.get('/api/tasks/{tid}/reports/{repid}/{fmt}')
def download(tid,repid,fmt):
    r=owned(repid,tid,'report')
    if fmt not in ('pdf','csv'): raise HTTPException(404)
    path=db.DATA/'reports'/repid/('report.pdf' if fmt=='pdf' else 'actions.csv')
    return FileResponse(path,filename=f'智变链_{r["run_id"]}_{r["status"]}.{fmt}',media_type='application/pdf' if fmt=='pdf' else 'text/csv; charset=utf-8')

@app.get('/api/tasks/{tid}/report-preview/{repid}/{page_number}')
def report_preview(tid,repid,page_number:int):
    owned(repid,tid,'report')
    with fitz.open(db.DATA/'reports'/repid/'report.pdf') as doc:
        if not 1<=page_number<=len(doc): raise HTTPException(404)
        return Response(doc[page_number-1].get_pixmap(matrix=fitz.Matrix(1.7,1.7),alpha=False).tobytes('png'),media_type='image/png')

@app.get('/api/tasks/{tid}/files/{did}/page/{page}')
def page(tid,did,page:int):
    d=owned(did,tid,'doc')
    if Path(d['path']).suffix!='.pdf': raise ValueError('仅 PDF 有页面预览')
    with fitz.open(d['path']) as pdf:
        if not 1<=page<=len(pdf): raise HTTPException(404)
        return Response(pdf[page-1].get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False).tobytes('png'),media_type='image/png')

@app.get('/api/tasks/{tid}/files/{did}/original')
def original(tid,did):
    d=owned(did,tid,'doc');return FileResponse(d['path'],filename=d['name'])

@app.get('/')
def index(): return FileResponse(ROOT/'static'/'index.html')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

if __name__=='__main__':
    import os,uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('ZBL_PORT','8765')),log_level='warning')
