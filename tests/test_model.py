import time
from pathlib import Path
import httpx
import pytest
import model

def test_auth_failure_not_retried(monkeypatch):
    calls=[]
    def post(self,*a,**kw): calls.append(1);return httpx.Response(401)
    monkeypatch.setattr(httpx.Client,'post',post)
    with pytest.raises(ValueError,match='鉴权'):
        model.extract('x.txt',[{'text':'x'}],lambda:False,lambda x:None,time.monotonic()+600,dict(key='test',base_url='https://example.test',model='fake'))
    assert len(calls)==1

def test_timeout_retries_once(monkeypatch):
    calls=[]
    def post(self,*a,**kw): calls.append(1);raise httpx.ReadTimeout('timeout')
    monkeypatch.setattr(httpx.Client,'post',post)
    with pytest.raises(ValueError,match='超时'):
        model.extract('x.txt',[{'text':'x'}],lambda:False,lambda x:None,time.monotonic()+600,dict(key='test',base_url='https://example.test',model='fake'))
    assert len(calls)==2

def test_cancelled_model_does_not_return_output(monkeypatch):
    cancelled=[False]
    def post(self,*a,**kw):
        cancelled[0]=True;return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}]})
    monkeypatch.setattr(httpx.Client,'post',post)
    with pytest.raises(InterruptedError):
        model.extract('x.txt',[{'text':'x'}],lambda:cancelled[0],lambda x:None,time.monotonic()+600,dict(key='test',base_url='https://example.test',model='fake'))
