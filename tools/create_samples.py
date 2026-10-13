"""Regenerate transparent, synthetic input fixtures. No expected answers in inference data."""
import csv
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reports import font

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'samples'

def drawing(path,rev,nominal,unit='mm',lo='-0.1',hi='+0.1'):
    font();c=canvas.Canvas(str(path),pagesize=(842,595));c.setTitle(f'HSG-001 Revision {rev} simulated drawing')
    c.setFillColor(colors.HexColor('#f9fbfa'));c.rect(0,0,842,595,fill=1,stroke=0)
    c.setStrokeColor(colors.HexColor('#36565b'));c.setLineWidth(.8);c.rect(25,25,792,545)
    c.setFont('ZBL',17);c.setFillColor(colors.HexColor('#153d3d'));c.drawString(45,539,'控制器外壳 / 安装孔尺寸图')
    c.setFont('Helvetica',10);c.drawRightString(796,542,'ENGINEERING DRAWING / SIMULATED')
    c.line(25,520,817,520)
    c.setFont('Helvetica',11);c.drawString(45,494,'PART: HSG-001');c.drawString(237,494,'REV: '+rev);c.drawString(355,494,'UNIT: '+unit)
    c.setFont('ZBL',10);c.drawString(570,494,'模拟案例 · 非生产图纸')
    c.setLineWidth(1.8);c.roundRect(144,170,350,257,17)
    c.setLineWidth(.7);c.roundRect(169,195,300,207,8)
    for x,y in ((160,186),(478,186),(160,411),(478,411)):
        c.setLineWidth(1.2);c.circle(x,y,8)
        c.setLineWidth(.4);c.setDash(3,3);c.line(x-17,y,x+17,y);c.line(x,y-17,x,y+17);c.setDash()
    c.setLineWidth(.7);c.line(484,416,560,447);c.line(560,447,771,447)
    c.setFont('Helvetica-Bold',14);c.drawString(569,456,f'H1: DIA {nominal} +/- {hi.lstrip("+")} {unit}')
    c.setFont('ZBL',10);c.drawString(570,429,'四处安装孔 · 相同尺寸要求')
    c.setFillColor(colors.HexColor('#e8f1ec'));c.rect(568,265,211,98,fill=1,stroke=0)
    c.setFillColor(colors.HexColor('#42635d'));c.setFont('ZBL',11);c.drawString(584,340,'评审说明')
    c.setFont('ZBL',10);c.drawString(584,316,'本图仅说明已编号特征 H1。');c.drawString(584,296,'其他几何不纳入本次尺寸比对。')
    c.setFont('Helvetica',10);c.drawString(242,290,'TOP VIEW / NTS')
    c.setLineWidth(.7);c.line(25,130,817,130)
    c.setFont('ZBL',10);c.drawString(45,109,'机器可读标注（与图面尺寸一致）：')
    c.setFont('Helvetica',11);c.drawString(45,85,f'FEATURE H1 diameter {nominal} {unit} LOW {lo} HIGH {hi}')
    c.setFont('Helvetica',8);c.drawString(45,44,'SIMULATED COMPETITION DATA / NOT FOR PRODUCTION / SCALE: NOT TO SCALE');c.drawRightString(796,44,'PAGE 1 / 1')
    c.save()

def write_csv(name,fields,rows):
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)

def main():
    OUT.mkdir(exist_ok=True)
    drawing(OUT/'HSG-001_A.pdf','A','4.0')
    drawing(OUT/'HSG-001_B.pdf','B','4.5')
    alt=OUT/'variants';alt.mkdir(exist_ok=True)
    drawing(alt/'HSG-001_B_5mm.pdf','B','5.0')
    (OUT/'ECN-001.txt').write_text('模拟工程变更通知 ECN-001\n零件 HSG-001，由 A 版变更为 B 版，特征 H1 安装孔直径由 4.0 mm 调整至 4.5 mm，上下偏差仍为 -0.1/+0.1 mm。\n本次明确生效订单仅为 SO-NEW-001，要求使用 B 版。SO-OLD-001 仍按 A 版执行，不在本次生效范围。\n旧版库存及未分配在制品需核查用途，不能据此直接认定报废。\n模拟数据，不代表任何企业真实订单或生产要求。\n',encoding='utf-8')
    write_csv('BOM.csv',['record_id','product_no','product_rev','part_no','revision','quantity'],[
        dict(record_id='BOM-001',product_no='CTRL-100',product_rev='A',part_no='HSG-001',revision='A',quantity='1'),
        dict(record_id='BOM-002',product_no='CTRL-100',product_rev='B',part_no='HSG-001',revision='B',quantity='1')])
    write_csv('检验标准.csv',['item_id','part_no','feature_id','revision','nominal','lower','upper','unit','order_id'],[
        dict(item_id='QI-001',part_no='HSG-001',feature_id='H1',revision='A',nominal='4.0',lower='-0.1',upper='+0.1',unit='mm',order_id='SO-NEW-001')])
    write_csv('库存.csv',['record_id','batch','part_no','revision','quantity','order_id'],[
        dict(record_id='INV-A-001',batch='LOT-A-01',part_no='HSG-001',revision='A',quantity='600',order_id=''),
        dict(record_id='INV-B-001',batch='LOT-B-01',part_no='HSG-001',revision='B',quantity='100',order_id=''),
        dict(record_id='INV-X-001',batch='LOT-X-01',part_no='BRK-999',revision='A',quantity='800',order_id='')])
    write_csv('在制品.csv',['record_id','work_order','part_no','revision','quantity','order_id'],[
        dict(record_id='WIP-A-001',work_order='WO-A-01',part_no='HSG-001',revision='A',quantity='200',order_id='')])
    write_csv('订单.csv',['record_id','order_id','part_no','revision','quantity'],[
        dict(record_id='ORD-001',order_id='SO-NEW-001',part_no='CTRL-100',revision='B',quantity='300'),
        dict(record_id='ORD-002',order_id='SO-OLD-001',part_no='CTRL-100',revision='A',quantity='500')])
    items=[('old','HSG-001_A.pdf'),('new','HSG-001_B.pdf'),('ecn','ECN-001.txt'),('bom','BOM.csv'),('inspection','检验标准.csv'),('inventory','库存.csv'),('wip','在制品.csv'),('orders','订单.csv')]
    (OUT/'manifest.json').write_text(json.dumps([dict(role=r,file=f) for r,f in items],ensure_ascii=False,indent=2),encoding='utf-8')
    print('Generated 8 main-case inputs and 1 changed-input PDF.')

if __name__=='__main__':main()
