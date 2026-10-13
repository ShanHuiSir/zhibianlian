"""Local SQLite JSON store. Mutations run under application RLock transactions."""
import json
import os
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

ROOT=Path(__file__).parent
DATA=Path(os.environ.get('ZBL_DATA_DIR',ROOT/'data')).resolve()
DATA.mkdir(parents=True,exist_ok=True)
LOCK=threading.RLock()

def now(): return datetime.now(timezone.utc).isoformat()
def uid(prefix): return prefix+'-'+uuid4().hex[:12]
def connect():
    c=sqlite3.connect(DATA/'app.sqlite3',timeout=10)
    c.execute('PRAGMA journal_mode=WAL')
    return c

with connect() as c:
    c.execute('CREATE TABLE IF NOT EXISTS objects (id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL)')

def put(obj,kind):
    with connect() as c:
        c.execute('INSERT OR REPLACE INTO objects VALUES (?,?,?)',(obj['id'],kind,json.dumps(obj,ensure_ascii=False)))
    return obj

def get(id,kind=None):
    with connect() as c: row=c.execute('SELECT kind,body FROM objects WHERE id=?',(id,)).fetchone()
    if row is None or (kind and row[0]!=kind): raise KeyError('对象不存在')
    return json.loads(row[1])

def all_of(kind):
    with connect() as c: rows=c.execute('SELECT body FROM objects WHERE kind=? ORDER BY rowid DESC',(kind,)).fetchall()
    return [json.loads(r[0]) for r in rows]

def event(task,action,**fields):
    put({'id':uid('E'),'task_id':task,'action':action,'time':now(),**fields},'event')

def recover():
    for r in all_of('run'):
        if r['state']=='分析中':
            r.update(state='失败',error='服务重启，中断的运行未完成；请重新分析。',ended=now())
            put(r,'run')
