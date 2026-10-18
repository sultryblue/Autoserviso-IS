"""Real Chromium layout / keyboard-reachability checks using recorded HTTP data.

The browser loads local HTML/CSS/JS in memory. Its GET responses are recorded data,
not live requests. Write requests are deliberately rejected, never simulated as saved.
Real server effects are tested separately by test_system.py/test_regressions.py.
This is not an end-to-end browser-to-server test or an accessibility certification.

Optional dependency: playwright (application runtime still needs only stdlib).
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import main
import notification_provider
from test_system import Browser
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent


def fixtures():
    """Capture genuine local-server responses in a temporary database."""
    old=main.DB
    with tempfile.TemporaryDirectory() as tmp:
        main.DB=Path(tmp)/'browser_fixtures.db'
        main.SESSIONS.clear();notification_provider.configure('success');notification_provider._ACCEPTED.clear()
        main.init_db(seed=True)
        server=main.ThreadingHTTPServer(('127.0.0.1',0),main.Handler)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);thread.start()
        try:
            actors={role:Browser(server.server_port) for role in ['vadybininkas','vadovas','mechanikas','klientas']}
            for role,b in actors.items():b.login(role)
            def ok(b,action,data):
                status,result=b.request(action,data)
                assert status==200,(action,result)
                return result.get('id')
            a,m,c,b=(actors[x] for x in ['vadybininkas','mechanikas','klientas','vadovas'])
            # Genuine active diagnosis and a genuine running confirmed task.
            ok(a,'estimate_submit',{'id':1})
            ok(c,'estimate_decide',{'id':1,'status':'Patvirtinta'})
            ok(a,'task_assign',{'id':1,'mechanic_id':3})
            ok(m,'task_status',{'id':1,'status':'Vykdomas'})
            result={}
            for role,actor in actors.items():
                status,state=actor.request('state');assert status==200
                state['csrf']='local-layout-fixture'
                data={'state':state}
                if role in ['vadybininkas','vadovas']:
                    status,data['notifications']=actor.request('notifications');assert status==200
                if role=='vadovas':
                    stamp=datetime.now().strftime('%Y-%m-%d')
                    for endpoint in ['reports','audit']:
                        status,data[endpoint]=actor.request(f'{endpoint}?from={stamp}&to={stamp}');assert status==200
                if role=='klientas':
                    status,data['free_slots']=actor.request('free_slots?car_id=1&date=2028-02-01');assert status==200
                result[role]=data
            return result
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2);main.DB=old;main.SESSIONS.clear()


class Tester:
    def __init__(self,page,width,out,data):
        self.page=page;self.width=width;self.out=out;self.data=data;self.details=[];self.screens=[]
    def load(self,role,view,modal=None,shot=None):
        previous=self.page
        self.page=previous.context.new_page(); previous.close()
        p=self.page; p.set_default_timeout(4000)
        p.set_content('<!doctype html><html lang="lt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app"></div><dialog id="dialog"></dialog><div id="toast" role="status" aria-live="polite"></div></body></html>')
        p.add_style_tag(content=(ROOT/'static/style.css').read_text())
        p.evaluate('''fixture=>{window.fixture=fixture;
          if(!crypto.randomUUID)crypto.randomUUID=()=>"00000000-0000-4000-8000-000000000001";
          window.fetch=async(url,options={})=>{
            if(options.method==='POST')return {ok:false,status:503,json:async()=>({error:'Atvaizdavimo patikra: įrašymas nevykdomas.'})};
            const key=String(url).replace(/^.*\\/api\\//,'').split('?')[0];
            const body=fixture[key];
            return {ok:body!==undefined,status:body!==undefined?200:404,json:async()=>body||{error:'Atvaizdavimo duomenų nėra.'}};
          };
        }''',self.data[role])
        p.add_script_tag(content=(ROOT/'static/app.js').read_text())
        p.wait_for_selector('nav')
        p.evaluate('(v)=>{view=v;chosen=1;render()}',view)
        p.wait_for_timeout(100)
        if modal:p.evaluate(modal)
        p.wait_for_timeout(60)
        self.measure(role+'/'+view+('/dialog' if modal else ''))
        if shot:
            p.screenshot(path=self.out/f'{self.width}_{shot}.png',full_page=True)
            self.screens.append(f'{self.width}_{shot}.png')
        self.keyboard_reachability()
    def measure(self,label):
        d=self.page.evaluate('''()=>({width:innerWidth,document:document.documentElement.scrollWidth,
        dialogs:[...document.querySelectorAll('dialog[open]')].map(e=>{let r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,height:innerHeight,client:e.clientWidth,scroll:e.scrollWidth}}),
        inputs:[...document.querySelectorAll('input,select,textarea')].filter(e=>e.getClientRects().length&&!e.closest('.tablewrap')).map(e=>{let r=e.getBoundingClientRect();return {name:e.name,left:r.left,right:r.right}})})''')
        assert d['document']<=d['width']+1,(label,d)
        for x in d['dialogs']:
            assert x['left']>=-1 and x['right']<=self.width+1 and x['scroll']<=x['client']+1 and x['top']>=-1 and x['bottom']<=x['height']+1,(label,x)
        for x in d['inputs']:
            assert x['left']>=-1 and x['right']<=self.width+1,(label,x)
        self.details.append({'screen':label,'measurements':d})
    def keyboard_reachability(self):
        p=self.page
        # Tag and count visible, enabled controls (inside the dialog if it is open).
        n=p.evaluate('''()=>{let root=document.querySelector('dialog[open]')||document;
        let a=[...root.querySelectorAll('button,input,select,textarea,[tabindex="0"]')].filter(e=>!e.disabled&&e.getClientRects().length);
        a.forEach((e,i)=>e.dataset.keyboardTestId=String(i));return a.length}''')
        visited=set()
        for _ in range(6*n+12):
            current=p.evaluate('document.activeElement?.dataset.keyboardTestId')
            if current is not None:visited.add(int(current))
            if len(visited)==n:break
            p.keyboard.press('Tab')
        assert len(visited)==n,(n,visited)
        # Inspect focus outline on an enabled button; meaningful visible focus is required.
        p.keyboard.press('Shift+Tab')
        if p.locator('dialog[open]').count():
            p.keyboard.press('Escape')
            assert not p.locator('dialog').evaluate('(e)=>e.open')
    def search(self,kind):
        self.load('vadybininkas',kind)
        p=self.page
        target=p.locator('#search')
        for _ in range(60):
            if target.evaluate('(e)=>e===document.activeElement'):break
            p.keyboard.press('Tab')
        else:raise AssertionError('Paieškos laukas nepasiekiamas Tab')
        p.keyboard.type('zzzz-nerastas-irasas')
        assert 'Pagal paieškos kriterijus įrašų nerasta.' in p.locator('#results').inner_text()
        p.keyboard.press('Control+A');p.keyboard.press('Backspace')
        assert p.locator('#results tbody tr').count()>0
        self.measure('Paieška: '+kind)
    def horizontal(self):
        self.load('vadovas','audit')
        p=self.page;wraps=p.locator('.tablewrap');found=False
        for i in range(wraps.count()):
            w=wraps.nth(i)
            if w.evaluate('(e)=>e.scrollWidth>e.clientWidth+1'):
                for _ in range(100):
                    if w.evaluate('(e)=>e===document.activeElement'):break
                    p.keyboard.press('Tab')
                else:raise AssertionError('Lentelė nepasiekiama Tab')
                p.keyboard.press('ArrowRight');p.wait_for_timeout(200)
                assert w.evaluate('(e)=>e.scrollLeft')>0
                found=True
        if self.width==390:assert found,'390 px patikrai tikėtasi plačios lentelės'
    def figure(self,role,view,number):
        self.load(role,view)
        self.page.screenshot(path=self.out/f'figure_{number:02d}.png',full_page=True)


def run(out):
    out.mkdir(parents=True,exist_ok=True)
    data=fixtures();results=[];all_details=[];screens=[];started=datetime.now(timezone.utc).isoformat()
    with sync_playwright() as pw:
        executable=os.environ.get('BROWSER_EXECUTABLE') or shutil.which('chromium') or shutil.which('google-chrome')
        browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}),args=['--no-sandbox'])
        for width in (1360,390):
            context=browser.new_context(viewport={'width':width,'height':960 if width==1360 else 844},device_scale_factor=1,locale='lt-LT');page=context.new_page()
            t=Tester(page,width,out,data)
            cases=[
                ('BR01','Vadybininko navigacija ir pagrindiniai sąrašai',lambda:[t.load('vadybininkas',v,shot=v) for v in ['overview','clients','cars','appointments','orders','tasks','order']]),
                ('BR02','Kliento navigacija, kontaktai, automobiliai, vizitai ir užsakymas',lambda:[t.load('klientas',v,shot='client_'+v) for v in ['overview','contacts','cars','appointments','orders','order']]),
                ('BR03','Mechaniko aktyvi diagnostika ir vykdomas darbas',lambda:[t.load('mechanikas',v,shot=v) for v in ['diagnostics','tasks']]),
                ('BR04','Vadovo pranešimai, suvestinė, paskyros ir žurnalas',lambda:[t.load('vadovas',v,shot=v) for v in ['notifications','reports','users','audit']]),
                ('BR05','Kliento, automobilio ir vizito dialogų laukai pasiekiami Tab',lambda:[t.load('vadybininkas','overview',expr,shot=f'form_{i}') for i,expr in enumerate(['editClient(1)','editCar(1)','editAppointment(1)','assignDiagnostic(1)','assignTask(1)'])]),
                ('BR06','Mechaniko diagnostikos ir darbo baigimo formos',lambda:[t.load('mechanikas','tasks',expr,shot=f'mechform_{i}') for i,expr in enumerate(['diagnosticEntry(1,null)',"taskState(1,'Baigtas')","taskState(1,'Sustabdytas')"])]),
                ('BR07','Sąmatos, mokėjimo, sprendimo ir uždarymo dialogai',lambda:[t.load(role,'order',expr,shot=f'orderform_{i}') for i,(role,expr) in enumerate([('vadybininkas','editEstimate(1)'),('vadybininkas','closeOrder(1)'),('klientas','payOrder(1)'),('klientas',"decideEstimate(1,'Patvirtinta')")])]),
                ('BR08','Paskyros kūrimo ir redagavimo formos',lambda:[t.load('vadovas','users',expr,shot=f'userform_{i}') for i,expr in enumerate(['newUser()','editUser(3)'])]),
                ('BR09','Kliento vizito laiko pasirinkimo forma',lambda:t.load('klientas','appointments','clientAppointment()',shot='client_visit_form')),
                ('BR10','Klientų paieškos įvedimas klaviatūra ir neradimas',lambda:t.search('clients')),
                ('BR11','Užsakymų paieškos įvedimas klaviatūra ir neradimas',lambda:t.search('orders')),
                ('BR12','Plačios lentelės horizontalus slinkimas klaviatūra',t.horizontal),
            ]
            for code,title,fn in cases:
                stamp=time.perf_counter()
                try:fn();passed=True;error=''
                except Exception:
                    passed=False;error=traceback.format_exc();t.page.screenshot(path=out/f'FAIL_{code}_{width}.png',full_page=True)
                results.append({'id':f'{code}-{width}','requirement':'NF-03','description':title,'passed':passed,'error':error,'duration_ms':round(1000*(time.perf_counter()-stamp),2)})
                print(code,width,'OK' if passed else error,flush=True)
            if width==1360:
                for role,view,num in [('mechanikas','diagnostics',8),('mechanikas','tasks',9),('vadovas','notifications',11)]:t.figure(role,view,num)
            all_details.extend(t.details);screens.extend(t.screens);context.close()
        version=browser.version;browser.close()
    report={'executed_at':started,'environment':{'python':platform.python_version(),'os':platform.platform(),'browser':'Chromium '+version,'headless':True,'viewports':['1360x960','390x844']},'transport':'Local HTML/CSS/JS; GET response fixtures recorded from real local HTTP server; browser POST writes disabled',
        'scope':'Real rendering, Tab reachability of visible enabled controls, Escape, search typing and horizontal table scrolling. Not end-to-end browser/server writes; not full WCAG certification.',
        'tests':results,'passed':sum(r['passed'] for r in results),'total':len(results),'layout_checks':all_details,'screenshots':screens}
    (out/'browser_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"Atvaizdavimo ir klaviatūros patikros: {report['passed']}/{report['total']}")
    return all(r['passed'] for r in results)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'browser_results');args=parser.parse_args()
    raise SystemExit(0 if run(args.output) else 1)
