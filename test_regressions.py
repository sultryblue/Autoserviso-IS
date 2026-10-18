"""Targeted D3/D4 regression cases; real HTTP and a temporary SQLite database.

Each named case counts as one test, even when it checks several related assertions.
The bundled demonstration database is never opened by this module.
"""
import hashlib
import json
import platform
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

import main
import notification_provider
from test_system import Browser


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = main.DB
        main.DB = Path(self.tmp.name) / 'regression.db'
        main.SESSIONS.clear()
        notification_provider.configure('success')
        notification_provider._ACCEPTED.clear()
        main.init_db(seed=False)
        self.server = main.ThreadingHTTPServer(('127.0.0.1', 0), main.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        self.thread.start()
        self.boss = Browser(self.server.server_port); self.boss.login('vadovas')
        self.adviser = Browser(self.server.server_port); self.adviser.login('vadybininkas')
        self.mechanic = Browser(self.server.server_port); self.mechanic.login('mechanikas')
        self.c1 = self.ok(self.boss, 'client_save', {'name':'Bandymų klientas A','phone':'+37060011111','email':'a@example.com'})
        self.c2 = self.ok(self.boss, 'client_save', {'name':'Bandymų klientas B','phone':'+37060022222','email':'b@example.com'})
        self.ok(self.boss, 'user_save', {'username':'reg_client','name':'Bandymų klientas A','role':'klientas','client_id':self.c1,'password':'Demo2026!!'})
        self.client = Browser(self.server.server_port); self.client.login('reg_client','Demo2026!!')
        self.cars = [self.ok(self.adviser, 'car_save', {'client_id':cid,'plate':plate,'make':'Toyota','model':'Yaris','year':2020})
                     for cid,plate in [(self.c1,'REG01'),(self.c1,'REG02'),(self.c2,'REG03')]]
        self.slot = {'car_id':self.cars[0],'start_at':'2028-02-01T09:00','end_at':'2028-02-01T10:00','bay':1,'problem':'Bandymo gedimas'}
        self.visit = self.ok(self.adviser, 'appointment_save', self.slot)
        self.line = {'kind':'Darbas','title':'Regresinis remonto darbas','quantity_1000':1000,'unit_cents':2500}

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        main.DB = self.old_db
        main.SESSIONS.clear()
        self.tmp.cleanup()

    def ok(self, actor, action, data):
        status, body = actor.request(action, data)
        self.assertEqual(status, 200, (action,body))
        return body.get('id')

    def sql(self, text, args=()):
        with main.connect() as c:
            return [tuple(r) for r in c.execute(text,args)]

    def snapshot(self):
        return (self.sql('SELECT * FROM appointments'), self.sql('SELECT * FROM notifications'),
                self.sql('SELECT * FROM notification_attempts'))

    def order(self):
        self.ok(self.adviser,'appointment_status',{'id':self.visit,'status':'Atvyko','mileage':100000})
        oid = self.sql('SELECT id FROM orders WHERE appointment_id=?',(self.visit,))[0][0]
        aid = self.ok(self.adviser,'diagnostic_assign',{'order_id':oid,'mechanic_id':3})
        self.ok(self.mechanic,'diagnostic_add',{'assignment_id':aid,'result':'Nustatytas gedimas','proposed_works':'Regresinis remonto darbas'})
        return oid

    def proposal(self,oid):
        return self.ok(self.adviser,'estimate_save',{'order_id':oid,'lines':[self.line]})

    def rejected(self):
        oid=self.order(); eid=self.proposal(oid)
        self.ok(self.adviser,'estimate_submit',{'id':eid})
        self.ok(self.client,'estimate_decide',{'id':eid,'status':'Atmesta'})
        return oid,eid

    def status(self,oid):
        return self.sql('SELECT status FROM orders WHERE id=?',(oid,))[0][0]

    def test_01_same_client_vehicle(self):
        """RG-01 | FR-09 | To paties kliento automobilis pakeičiamas, pranešimų istorija išlieka."""
        before=self.snapshot()
        self.ok(self.adviser,'appointment_save',{**self.slot,'id':self.visit,'car_id':self.cars[1]})
        self.assertEqual(self.sql('SELECT car_id,client_id FROM appointments WHERE id=?',(self.visit,)),[(self.cars[1],self.c1)])
        self.assertEqual(before[1:],self.snapshot()[1:])

    def test_02_other_client_vehicle(self):
        """RG-02 | FR-09; NF-16 | Darbuotojo HTTP bandymas perkelti vizitą kitam klientui atmetamas."""
        before=self.snapshot()
        for actor in (self.adviser,self.boss):
            self.assertEqual(actor.request('appointment_save',{**self.slot,'id':self.visit,'car_id':self.cars[2]})[0],409)
            self.assertEqual(before,self.snapshot())
        self.assertEqual(self.sql('PRAGMA foreign_key_check'),[])

    def test_03_client_scope(self):
        """RG-03 | FR-09; NF-11 | Klientas keičia savo automobilį, svetimo negali pasirinkti."""
        self.ok(self.client,'appointment_save',{**self.slot,'id':self.visit,'car_id':self.cars[1]})
        before=self.snapshot()
        self.assertEqual(self.client.request('appointment_save',{**self.slot,'id':self.visit,'car_id':self.cars[2]})[0],404)
        self.assertEqual(before,self.snapshot())

    def test_04_database_identity(self):
        """RG-04 | NF-05; NF-16 | Tiesioginis vizito client_id pakeitimas arba NULL DB atmetamas."""
        before=self.snapshot()
        for query,args in [
            ('UPDATE appointments SET client_id=? WHERE id=?',(self.c2,self.visit)),
            ('UPDATE appointments SET client_id=?,car_id=? WHERE id=?',(self.c2,self.cars[2],self.visit)),
            ('UPDATE appointments SET client_id=NULL WHERE id=?',(self.visit,))]:
            with self.assertRaises(sqlite3.IntegrityError):
                with main.connect() as c: c.execute(query,args)
        self.assertEqual(before,self.snapshot())

    def test_05_existing_database_startup(self):
        """RG-05 | NF-05; NF-16 | Apsauga įdiegiama esamai DB; pakartotinis paleidimas nekeičia įrašų."""
        with main.connect() as c: c.execute('DROP TRIGGER appointment_client_identity_guard')
        before=self.snapshot()
        main.init_db(seed=False); main.init_db(seed=False)
        self.assertEqual(before,self.snapshot())
        self.assertTrue(self.sql("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='appointment_client_identity_guard'"))
        with self.assertRaises(sqlite3.IntegrityError):
            with main.connect() as c: c.execute('UPDATE appointments SET client_id=?,car_id=? WHERE id=?',(self.c2,self.cars[2],self.visit))

    def test_06_free_slots_identity(self):
        """RG-06 | FR-07; FR-09 | Keičiant vizitą laisvo laiko užklausa negali naudoti kito kliento automobilio."""
        q=f'free_slots?id={self.visit}&date=2028-02-01&car_id='
        self.assertEqual(self.adviser.request(q+str(self.cars[1]))[0],200)
        self.assertEqual(self.adviser.request(q+str(self.cars[2]))[0],409)

    def test_07_first_draft(self):
        """RG-07 | FR-14; FR-15 | Pirmas juodraštis palieka Naujas, pateikimas nustato Derinamas."""
        oid=self.order(); eid=self.proposal(oid)
        self.assertEqual(self.status(oid),'Naujas')
        self.ok(self.adviser,'estimate_save',{'id':eid,'order_id':oid,'lines':[self.line]})
        self.assertEqual(self.status(oid),'Naujas')
        self.ok(self.adviser,'estimate_submit',{'id':eid})
        self.assertEqual(self.status(oid),'Derinamas')

    def test_08_rejected_new_draft(self):
        """RG-08 | FR-14; FR-16 | Po atmetimo naujo juodraščio sukūrimas ir redagavimas palieka Derinamas."""
        oid,eid=self.rejected()
        self.assertEqual(self.status(oid),'Derinamas')
        new=self.proposal(oid)
        self.assertEqual(self.status(oid),'Derinamas')
        self.ok(self.adviser,'estimate_save',{'id':new,'order_id':oid,'lines':[{**self.line,'unit_cents':2200}]})
        self.assertEqual(self.status(oid),'Derinamas')
        self.assertEqual(self.sql('SELECT status FROM estimates WHERE id=?',(eid,)),[('Atmesta',)])
        self.assertEqual(self.sql('SELECT id FROM tasks'),[])

    def test_09_repeated_rejection(self):
        """RG-09 | FR-14; FR-16 | Pakartotinai atmetus pasiūlymą išlieka Derinamas ir galima paruošti grąžinimui."""
        oid,_=self.rejected(); eid=self.proposal(oid)
        self.ok(self.adviser,'estimate_submit',{'id':eid})
        self.ok(self.client,'estimate_decide',{'id':eid,'status':'Atmesta'})
        self.assertEqual(self.status(oid),'Derinamas')
        self.ok(self.adviser,'order_ready',{'id':oid})
        self.assertEqual(self.status(oid),'Paruoštas')

    def test_10_estimate_input(self):
        """RG-10 | FR-14 | Tuščia versija ir detalė be ankstesnės patvirtintos apimties atmetamos be dalinių pakeitimų."""
        oid,_=self.rejected(); before=self.sql('SELECT * FROM estimates')
        for lines in ([],[{**self.line,'kind':'Detalė'}]):
            self.assertEqual(self.adviser.request('estimate_save',{'order_id':oid,'lines':lines})[0],400)
            self.assertEqual(self.status(oid),'Derinamas')
            self.assertEqual(self.sql('SELECT * FROM estimates'),before)

    def test_11_approved_and_running(self):
        """RG-11 | FR-17; FR-19; FR-21 | Papildymas nedubliuoja užduočių ir nekeičia vykdomo užsakymo būsenos."""
        oid=self.order(); eid=self.proposal(oid)
        self.ok(self.adviser,'estimate_submit',{'id':eid})
        self.ok(self.client,'estimate_decide',{'id':eid,'status':'Patvirtinta'})
        tid=self.sql('SELECT id FROM tasks')[0][0]
        self.ok(self.adviser,'task_assign',{'id':tid,'mechanic_id':3})
        extra=self.ok(self.adviser,'estimate_save',{'order_id':oid,'lines':[{**self.line,'kind':'Detalė','title':'Papildoma detalė'}]})
        self.assertEqual(self.status(oid),'Patvirtintas')
        self.ok(self.adviser,'estimate_submit',{'id':extra})
        self.assertEqual(self.status(oid),'Derinamas')
        self.ok(self.mechanic,'task_status',{'id':tid,'status':'Vykdomas'})
        self.ok(self.client,'estimate_decide',{'id':extra,'status':'Atmesta'})
        self.assertEqual(self.status(oid),'Vykdomas')
        self.assertEqual(len(self.sql('SELECT * FROM tasks')),1)

    def test_12_closing_note(self):
        """RG-12 | FR-13 | Faktinis perdavimas nepakeičia privalomos netuščios užbaigimo pastabos."""
        oid,_=self.rejected()
        self.ok(self.adviser,'order_ready',{'id':oid})
        self.ok(self.adviser,'order_handover',{'id':oid})
        for data in ({'id':oid},{'id':oid,'note':'   '}):
            self.assertEqual(self.adviser.request('order_close',data)[0],400)
            self.assertEqual(self.status(oid),'Paruoštas')
        self.ok(self.adviser,'order_close',{'id':oid,'note':'Automobilis grąžintas neatlikus remonto.'})
        self.assertEqual(self.sql('SELECT status,closing_note,closed_by FROM orders WHERE id=?',(oid,)),[('Uždarytas','Automobilis grąžintas neatlikus remonto.',2)])

    def test_13_login_roles(self):
        """RG-13 | FR-01; NF-10 | Atskirai patikrinti visų keturių rolių prisijungimo ir sesijos rezultatai."""
        for login,pwd,role in [('vadovas','Demo2026!','vadovas'),('vadybininkas','Demo2026!','vadybininkas'),('mechanikas','Demo2026!','mechanikas'),('reg_client','Demo2026!!','klientas')]:
            b=Browser(self.server.server_port)
            self.assertEqual(b.request('login',{'username':login,'password':pwd})[0],200)
            status,body=b.request('state')
            self.assertEqual(status,200); self.assertEqual(body['user']['role'],role)
            self.assertTrue(body.get('csrf'))

    def test_14_recorded_by(self):
        """RG-14 | FR-25; FR-28 | Internetu registruojamas klientas, Vietoje – mokėjimą įrašęs darbuotojas."""
        oid=self.order(); eid=self.proposal(oid)
        self.ok(self.adviser,'estimate_submit',{'id':eid})
        self.ok(self.client,'estimate_decide',{'id':eid,'status':'Patvirtinta'})
        online=self.ok(self.client,'payment_start',{'order_id':oid,'amount_cents':500,'request_key':'reg-online-payment'})
        local=self.ok(self.adviser,'payment_local',{'order_id':oid,'amount_cents':1000,'request_key':'reg-local-payment'})
        self.assertEqual(self.sql('SELECT p.method,u.role FROM payments p JOIN users u ON u.id=p.recorded_by WHERE p.id IN (?,?) ORDER BY p.id',(online,local)),[('Internetu','klientas'),('Vietoje','vadybininkas')])


class JsonResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.records=[]
    def startTest(self,test):
        super().startTest(test); self.started=time.perf_counter()
    def addSuccess(self,test):
        super().addSuccess(test); self.record(test,True,'')
    def addFailure(self,test,err):
        super().addFailure(test,err); self.record(test,False,self._exc_info_to_string(err,test))
    def addError(self,test,err):
        super().addError(test,err); self.record(test,False,self._exc_info_to_string(err,test))
    def record(self,test,passed,error):
        code,req,description=test.shortDescription().split(' | ',2)
        self.records.append({'id':code,'requirement':req,'description':description,'passed':passed,'error':error,'duration_ms':round(1000*(time.perf_counter()-self.started),2)})

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(RegressionTests)
    result=unittest.TextTestRunner(verbosity=2,resultclass=JsonResult).run(suite)
    report={'executed_at':datetime.now(timezone.utc).isoformat(),'environment':{'python':platform.python_version(),'platform':platform.platform(),'sqlite':sqlite3.sqlite_version},'type':'Papildomi HTTP/DB regresiniai testavimo atvejai; laikina DB','total':result.testsRun,'passed':sum(x['passed'] for x in result.records),'tests':result.records}
    Path(__file__).with_name('test_regression_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
