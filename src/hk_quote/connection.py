"""Durable health independent of the web transport and market activity."""
import json
import random
import socket
import threading
import time
from pathlib import Path


def retry_delay(attempt):
    base=[1,2,4,8,15,30][min(attempt,5)]
    return min(30,max(1,base*random.uniform(.9,1.1)))


def read_health(path='data/connection.json', now=None):
    now=time.time() if now is None else now
    try:
        state=json.loads(Path(path).read_text())
    except (OSError,ValueError):
        return dict(state='stopped',message='监听未运行／没有心跳')
    if now-state.get('heartbeat',0)>10:
        state.update(state='stopped',message='监听未运行／心跳超时')
    elif state.get('state') in ('connected','warming') and now-state.get('checked_at',0)>15:
        state.update(state='checking',message='行情检查超时，连接状态待确认')
    elif state.get('state')=='warming' and now>=state.get('warmup_until',float('inf')):
        state.update(state='connected',message='行情已连接；各股票仍需满足采样要求')
    return state


class ConnectionHealth:
    def __init__(self,host,port,publish,notify=None,path='data/connection.json',initial_state='connecting',market='HK'):
        self.host,self.port,self.publish,self.notify=host,port,publish,notify
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.Lock();self.quit=threading.Event();self.failed=threading.Event()
        self.data=dict(state=initial_state,message='正在检查运行时段',checked_at=0,market=market)
        self.outage=False
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def set(self,state,message,**fields):
        with self.lock:self.data.update(state=state,message=message,**fields)

    def disconnected(self,reason):
        self.failed.set()
        with self.lock:
            self.data.update(state='disconnected',message=reason,checked_at=time.time())
            first=not self.outage;self.outage=True
        if first and self.notify:self.notify('OpenD 行情已断开，异动分析暂停。'+reason)

    def recovered(self,symbols,warmup):
        with self.lock:
            restored=self.outage;self.outage=False
            self.data.update(state='warming',message='行情订阅成功，正在重新预热',checked_at=time.time(),
                             warmup_until=time.time()+warmup,symbols=symbols,next_retry=None)
        self.failed.clear()
        if self.notify:self.notify(('OpenD 已恢复' if restored else '行情监听已启动')+'，股票已重新订阅，正在预热后恢复异动分析。')

    def run(self):
        probe=0
        while not self.quit.is_set():
            now=time.time()
            if now>=probe and self.data.get('state') not in ('idle','paused'):
                probe=now+3
                try:
                    with socket.create_connection((self.host,self.port),timeout=1):pass
                except OSError:
                    if self.data.get('state') not in ('idle','paused'):
                        self.disconnected('无法连接本机行情端口')
            with self.lock:state=dict(self.data,heartbeat=now)
            temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(state,ensure_ascii=False));temporary.replace(self.path)
            self.publish(dict(kind='connection_status',ts=now,**read_health(self.path,now)))
            self.quit.wait(1)

    def close(self):
        self.quit.set();self.thread.join(timeout=2)
        self.path.write_text(json.dumps(dict(self.data,state='stopped',message='监听已停止',heartbeat=time.time()),ensure_ascii=False))
