"""Run repeatable checks and preserve immutable per-run evidence directories."""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SOURCE_FILES=['main.py','schema.sql','payment_provider.py','notification_provider.py','static/app.js','static/index.html','static/style.css','test_system.py','test_ui.js','test_regressions.py','test_visit_times.py','test_browser.py','run_checks.py','timezone_data/Europe_Vilnius','timezone_data/README.txt']

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def run(count,include_browser):
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination=ROOT/'test_runs'/stamp
    destination.mkdir(parents=True,exist_ok=False)
    hashes={name:digest(ROOT/name) for name in SOURCE_FILES}
    demo_before=digest(ROOT/'servisas.db') if (ROOT/'servisas.db').exists() else None
    node=shutil.which('node')
    if not node:raise RuntimeError('UI logikos patikroms reikalinga Node.js komanda node.')
    summary={'started_at':datetime.now(timezone.utc).isoformat(),'environment':{'python':platform.python_version(),'node':subprocess.check_output([node,'--version'],text=True).strip(),'platform':platform.platform()},'source_sha256':hashes,'demonstration_db_sha256_before':demo_before,'runs':[]}
    success=True
    for index in range(1,count+1):
        folder=destination/f'run{index}';folder.mkdir()
        commands=[('http_db',[sys.executable,'test_system.py'],'test_results.json'),('ui_logic',[node,'test_ui.js'],'test_ui_results.json'),('regression',[sys.executable,'test_regressions.py'],'test_regression_results.json'),('visit_time_regression',[sys.executable,'test_visit_times.py'],'test_visit_time_results.json')]
        if include_browser:commands.append(('browser_layout',[sys.executable,'test_browser.py','--output',str(folder/'browser')],str(folder/'browser/browser_results.json')))
        records=[]
        for group,command,result_name in commands:
            started=datetime.now(timezone.utc).isoformat()
            with (folder/(group+'.log')).open('w',encoding='utf-8') as log:
                process=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=300)
            path=Path(result_name)
            if not path.is_absolute():path=ROOT/path
            if not path.exists():
                records.append({'group':group,'passed':0,'total':0,'exit_code':process.returncode,'error':'Rezultatų failas nesukurtas.'});success=False;continue
            data=json.loads(path.read_text())
            if group!='browser_layout':shutil.copy2(path,folder/path.name)
            finished=datetime.now(timezone.utc).isoformat()
            item={'group':group,'passed':data['passed'],'total':data['total'],'exit_code':process.returncode,'started_at':started,'finished_at':finished,'duration_seconds':round((datetime.fromisoformat(finished)-datetime.fromisoformat(started)).total_seconds(),3),'result_file':str(path.relative_to(ROOT)) if group=='browser_layout' else path.name}
            records.append(item)
            success=success and process.returncode==0 and data['passed']==data['total']
            print(f'Paleidimas {index} / {group}: {data["passed"]}/{data["total"]}',flush=True)
        functional=[r for r in records if r['group']!='browser_layout']
        summary['runs'].append({'run':index,'results':records,'functional_passed':sum(r['passed'] for r in functional),'functional_total':sum(r['total'] for r in functional)})
        (folder/'source_sha256.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    summary['demonstration_db_sha256_after']=digest(ROOT/'servisas.db') if (ROOT/'servisas.db').exists() else None
    summary['demonstration_db_unchanged']=summary['demonstration_db_sha256_before']==summary['demonstration_db_sha256_after']
    summary['source_unchanged']=hashes=={name:digest(ROOT/name) for name in SOURCE_FILES}
    summary['success']=success and summary['demonstration_db_unchanged'] and summary['source_unchanged']
    summary['finished_at']=datetime.now(timezone.utc).isoformat()
    (destination/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(destination,flush=True)
    return summary['success']

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--runs',type=int,choices=range(1,4),default=2);parser.add_argument('--browser',action='store_true');args=parser.parse_args()
    raise SystemExit(0 if run(args.runs,args.browser) else 1)
