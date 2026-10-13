import csv
import io
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

FONT=Path(__file__).parent/'assets'/'LXGWWenKai-Regular.ttf'

def font():
    if 'ZBL' not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont('ZBL',str(FONT)))
    return 'ZBL'

def actions(run):
    out=[]
    for f in run.get('result',{}).get('findings',[]):
        d=run.get('decisions',{}).get(f['id'])
        if not d or d['decision']=='驳回': continue
        out.append({'id':'ACT-'+f['id'],'source':f['id'],'department':d.get('department') or f['department'],
                    'priority':f['priority'],'action':d.get('text') or f['title'],
                    'state':'待补充资料' if d['decision']=='待核查' else '待执行核查',
                    'needed':d.get('needed',''),'decision':d['decision']})
    return out

def safe_csv(v):
    s=str(v or '')
    return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r')) else s

def csv_report(run):
    out=io.StringIO(newline='')
    w=csv.writer(out)
    w.writerow(['运行编号','处理编号','来源结论','责任部门','优先级','处理建议','执行状态','待补资料','人工决定'])
    for a in actions(run): w.writerow([safe_csv(x) for x in [run['id'],*a.values()]])
    return ('\ufeff'+out.getvalue()).encode('utf-8')

def pdf_report(run,path,report_id):
    font(); styles=getSampleStyleSheet()
    for name in ('Normal','Heading1','Heading2','Title'):
        styles[name].fontName='ZBL'; styles[name].wordWrap='CJK'; styles[name].textColor=colors.HexColor('#173438')
    styles['Normal'].fontSize=10; styles['Normal'].leading=16
    styles['Heading1'].fontSize=17; styles['Heading1'].leading=24
    styles['Heading2'].fontSize=12; styles['Heading2'].leading=18
    styles['Title'].fontSize=25; styles['Title'].leading=34
    small=ParagraphStyle('small',parent=styles['Normal'],fontSize=8,leading=12)
    story=[]
    def p(text,style='Normal'): return Paragraph(escape(str(text)).replace('\n','<br/>'),styles[style])
    def add(text,style='Normal'): story.extend([p(text,style),Spacer(1,8)])
    t=run['task']; result=run.get('result',{})
    mode='DeepSeek 真实模型分析' if t['mode']=='deepseek' else '本地规则分析（未调用模型）'
    reviewed=run['state']=='已评审'; pending=[d for d in run.get('decisions',{}).values() if d['decision']=='待核查']
    add('智变链｜工程变更评审报告','Title')
    add(('已评审 · 存在未决事项' if pending else '已评审') if reviewed else '草稿 · 尚未完成评审','Heading1')
    add(t['name'],'Heading2')
    add(f"{t['part_no']}  {t['old_rev']} → {t['new_rev']}｜{mode}｜"+('模拟资料' if t.get('simulated') else '用户导入资料'))
    add(f"任务：{t['id']}\n运行：{run['id']}｜输入修订：{run['input_revision']}｜评审修订：{run['review_revision']}\n报告：{report_id}\n开始：{run['started']}\n结束：{run.get('ended','尚未完成')}")
    add('本报告整理工程评审意见，不代表生产批准或任何处置已执行。数量为关联待核查数量，不是报废或损失。')
    if run.get('error'): add('运行错误：'+run['error'])
    add('1 变更摘要','Heading1')
    for d in result.get('differences',[]):
        add(f"{d['feature_id']}：{d['old']['nominal']} {d['old']['unit']} → {d['new']['nominal']} {d['new']['unit']}；差值 {d['delta']} mm；公差{d['tolerance']}。")
    add('2 覆盖范围与未决问题','Heading1')
    labels={'bom':'BOM','inspection':'检验','inventory':'库存','wip':'在制品','orders':'订单','scope':'生效范围'}
    for k,v in result.get('coverage',{}).items(): add(f'{labels[k]}：{v}')
    for v in result.get('issues',[])+result.get('limits',[]): add(v)
    q=result.get('quantities',{})
    add(f"旧版库存：{q.get('inventory') if q.get('inventory') is not None else '未覆盖'} 件；旧版在制品：{q.get('wip') if q.get('wip') is not None else '未覆盖'} 件。分别统计。")
    for o in result.get('orders',[]): add(f"{o['order_id']}：{o['state']}；关联路径 {o['path']}；需求版本 {', '.join(o['required_revisions'])}")
    story.append(PageBreak()); add('3 结论、证据及人工评审','Heading1')
    for f in result.get('findings',[]):
        add(f"{f['id']}｜{f['title']}｜{f['priority']}",'Heading2')
        add(f"{f['kind']} / {f['rule'] or '原文比对'} / {f['department']}\n原始建议：{f['detail']}")
        d=run.get('decisions',{}).get(f['id'])
        add('人工决定：未处理' if not d else f"人工决定：{d['decision']}；责任部门：{d['department']}\n人工意见：{d.get('text') or '保留原建议'}\n理由：{d.get('reason') or '无'}；待补资料：{d.get('needed') or '无'}\n保存时间：{d['time']}")
        for eid in f['evidence']:
            e=result['evidence'][eid]
            story.append(Paragraph(escape(f"依据：{e['filename']} · {e['location']}\n{e['text']}").replace('\n','<br/>'),small));story.append(Spacer(1,7))
    add('4 部门处理清单','Heading1')
    for a in actions(run): add(f"{a['id']} / {a['department']} / {a['priority']}：{a['action']}；{a['state']}。待补资料：{a['needed'] or '无'}")
    add('5 输入快照与运行配置','Heading1')
    for d in run['docs']:
        add(f"{d['name']}｜{d['role']}\nSHA-256：{d['sha256']}")
    add(f"规则：{run['config']['rule_version']}；模型：{run['config'].get('model','无')}；提示：{run['config'].get('prompt_version','无')}\n运行时长：{run.get('seconds','未完成')} 秒；应用提取缓存：未使用。")
    for c in run.get('calls',[]): add(str(c))
    if run.get('corrections'): add('人工字段修正记录：'+str(run['corrections']))
    doc=SimpleDocTemplate(str(path),pagesize=(595.28,841.89),rightMargin=46,leftMargin=46,topMargin=46,bottomMargin=46,title='智变链工程变更评审报告',author='智变链')
    def footer(c,d):
        c.setFont('ZBL',8);c.setFillColor(colors.HexColor('#597277'));c.drawString(46,25,'智变链 / 工程评审辅助 / '+report_id);c.drawRightString(549,25,str(d.page))
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
