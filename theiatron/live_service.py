"""Workbench owner of one isolated resident perception worker."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid


class LiveService:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.proc = None
        self.worker_state = 'not-started'
        self.warmup_s = None
        self.session = None
        self.error = None

    def busy(self):
        with self.lock:
            return self.worker_state == 'warming' or bool(self.session and self.session['state'] in {'starting','running','stopping'})

    def _launch(self):
        if self.proc and self.proc.poll() is None: return
        self.worker_state,self.error = 'warming',None
        logs=self.root/'out'/'.live-worker';logs.mkdir(parents=True,exist_ok=True)
        log=(logs/(uuid.uuid4().hex+'.log')).open('x')
        try:
            self.proc=subprocess.Popen([sys.executable,'-m','theiatron.live_worker','--ipc'],
                cwd=self.root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,bufsize=1,
                env={**os.environ,'PYTHONUNBUFFERED':'1','THEIATRON_PARENT_PID':str(os.getpid())},start_new_session=True)
        except OSError:
            self.worker_state='offline'
            self.error='Unable to launch perception worker'
            raise
        finally:log.close()
        proc=self.proc
        threading.Thread(target=self._listen,args=(proc,),daemon=True).start()
        timer=threading.Timer(60,self._deadline,args=(proc,None))
        timer.daemon=True;timer.start()

    def _deadline(self,proc,ident):
        with self.lock:
            expired=self.worker_state=='warming' if ident is None else bool(self.session and self.session['id']==ident and self.session['state']=='stopping')
            if self.proc is proc and proc.poll() is None and expired:
                self.error='Worker exceeded its startup/stop deadline; restart the session'
                os.killpg(proc.pid,signal.SIGKILL)

    def _listen(self,proc):
        try:
            for line in proc.stdout:
                if not line.startswith('THEIATRON_STREAM '): continue
                packet=json.loads(line[len('THEIATRON_STREAM '):])
                with self.lock:
                    if self.proc is not proc: return
                    event=packet['event']
                    if event=='ready':
                        self.worker_state='ready';self.warmup_s=packet['warmup_s']
                    elif event=='fatal': self.error=packet['message']
                    elif self.session and packet.get('id')==self.session['id']:
                        if event=='started' and self.session['state']!='stopping': self.session['state']='running'
                        elif event=='finished': self.session['state']=packet['state']
        except Exception:
            with self.lock:self.error='Worker IPC failed'
        finally:
            proc.wait()
            with self.lock:
                if self.proc is proc:
                    self.worker_state='offline'
                    if self.session and self.session['state'] in {'starting','running','stopping'}:
                        self.session.update(state='interrupted',error='Worker exited before session completion')

    def _send(self,packet):
        if not self.proc or self.proc.poll() is not None: raise ValueError('worker unavailable')
        self.proc.stdin.write(json.dumps(packet)+'\n');self.proc.stdin.flush()

    def start(self,source,source_run,duration=120,fps=10,loop=False):
        with self.lock:
            if self.busy(): raise ValueError('a continuous session is already active')
            self._launch()
            ident='live-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
            self.session={'id':ident,'state':'starting','source_run':source_run,'source_name':Path(source).name,
                          'duration_limit_s':duration,'target_fps':fps,'loop':loop,'source_kind':'paced-file',
                          'requested_at':time.time()}
            try:
                self._send({'action':'start',**self.session,'source':str(source),'source_kind':'paced-file',
                            'out':str(self.root/'out'/ident),'duration':duration,'fps':fps,'loop':loop})
            except Exception:
                self.session['state']='failed';raise
            return self.snapshot()

    def stop(self,ident):
        with self.lock:
            if not self.session or self.session['id']!=ident: raise ValueError('session identity changed; reload')
            if self.session['state'] not in {'starting','running','stopping'}: return self.snapshot()
            self.session['state']='stopping'
            self._send({'action':'stop','id':ident})
            timer=threading.Timer(6,self._deadline,args=(self.proc,ident));timer.daemon=True;timer.start()
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            session=dict(self.session) if self.session else None
            if session:
                path=self.root/'out'/session['id']/'latest.json'
                if path.is_file():
                    disk=json.loads(path.read_text())
                    # A stale file cannot turn a killed/cancelled worker into a live one.
                    session={**disk,**session}
                    observed=disk.get('last_observation',{}).get('completed_at')
                    session['last_observation_age_s']=max(0,time.time()-observed) if observed else None
                    if session.get('first_observation_s') is not None:
                        session['request_to_first_observation_s']=round(disk['started_at']+disk['first_observation_s']-session['requested_at'],3)
            return {'worker':{'state':self.worker_state,'pid':self.proc.pid if self.proc else None,
                              'warmup_s':self.warmup_s,'error':self.error},'session':session,'busy':self.busy()}

    def close(self):
        with self.lock:
            proc=self.proc
            if proc and proc.poll() is None:
                try:self._send({'action':'shutdown'})
                except (OSError,ValueError):pass
        if proc and proc.poll() is None:
            try:proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=3)
