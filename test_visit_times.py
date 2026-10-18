"""Visit-time regressions through the real HTTP handler and a temporary DB.

Only appointment_now is controlled. Authentication and database transactions run
normally. The production clock has no environment or HTTP testing override.
"""
import json
import platform
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import main
from test_regressions import RegressionTests, JsonResult


class VisitTimeTests(unittest.TestCase):
    setUp = RegressionTests.setUp
    tearDown = RegressionTests.tearDown
    ok = RegressionTests.ok
    sql = RegressionTests.sql

    def clock(self, stamp):
        value=datetime.fromisoformat(stamp)
        if value.tzinfo is None:value=value.replace(tzinfo=main.VISIT_TIMEZONE)
        main.appointment_now=lambda:value

    def database(self):
        with main.connect() as c:
            names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {name:[tuple(r) for r in c.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in names}

    def refused_without_changes(self,actor,action,data,status):
        before=self.database()
        actual,body=actor.request(action,data)
        self.assertEqual(actual,status,body)
        self.assertEqual(self.database(),before)
        return body

    def test_01_past_registration(self):
        """LT-01 | FR-08; VT-01 | Praeities registracija atmetama klientui ir abiem darbuotojų rolėms be DB pakeitimų."""
        self.clock('2028-02-02T09:00:01')
        data={**self.slot,'start_at':'2028-02-02T09:00','end_at':'2028-02-02T10:00'}
        for actor in (self.client,self.adviser,self.boss):
            with self.subTest(role=actor):
                body=self.refused_without_changes(actor,'appointment_save',data,400)
                self.assertIn('Vizito pradžios laikas jau praėjęs',body['error'])
                self.assertIn('Lietuvos laiku',body['error'])

    def test_02_exact_start_and_future(self):
        """LT-02 | FR-08 | Tiksliai dabartinė pradžia ir būsimas laikas leidžiami; mikrosekunde praėjęs laikas atmetamas."""
        self.clock('2028-02-02T09:00:00')
        data={**self.slot,'start_at':'2028-02-02T09:00','end_at':'2028-02-02T10:00'}
        self.ok(self.client,'appointment_save',data)
        self.clock('2028-02-02T09:00:00.000001')
        self.refused_without_changes(self.client,'appointment_save',{**data,'car_id':self.cars[1],'bay':2},400)
        for day,actor in zip((3,4,5),(self.client,self.adviser,self.boss)):
            self.ok(actor,'appointment_save',{**data,'start_at':f'2028-02-{day:02d}T09:00','end_at':f'2028-02-{day:02d}T10:00'})

    def test_03_absence_boundary(self):
        """LT-03 | FR-09 | Neatvykimas prieš pradžią atmetamas; tiksliai pradžioje ir po jos leidžiamas."""
        self.clock('2028-02-01T08:59:59.999999')
        for actor in (self.adviser,self.boss):
            body=self.refused_without_changes(actor,'appointment_status',{'id':self.visit,'status':'Neatvyko'},409)
            self.assertIn('tik atėjus numatytai vizito pradžiai',body['error'])
        later=self.ok(self.adviser,'appointment_save',{**self.slot,'start_at':'2028-02-02T09:00','end_at':'2028-02-02T10:00'})
        self.clock('2028-02-01T09:00:00')
        self.ok(self.adviser,'appointment_status',{'id':self.visit,'status':'Neatvyko'})
        self.refused_without_changes(self.boss,'appointment_status',{'id':self.visit,'status':'Neatvyko'},409)
        self.clock('2028-02-02T09:00:00.000001')
        self.ok(self.boss,'appointment_status',{'id':later,'status':'Neatvyko'})

    def test_04_other_statuses_and_roles(self):
        """LT-04 | FR-09; FR-10; NF-10 | Atšaukimas ir priėmimas išlieka veikiantys, klientas neatvykimo nežymi."""
        self.clock('2028-02-01T08:00')
        self.refused_without_changes(self.client,'appointment_status',{'id':self.visit,'status':'Neatvyko'},403)
        self.ok(self.client,'appointment_status',{'id':self.visit,'status':'Atšauktas'})
        visit=self.ok(self.adviser,'appointment_save',self.slot)
        self.ok(self.adviser,'appointment_status',{'id':visit,'status':'Atvyko','mileage':12345})
        self.assertEqual(self.sql('SELECT COUNT(*) FROM orders WHERE appointment_id=?',(visit,)),[(1,)])
        self.refused_without_changes(self.adviser,'appointment_status',{'id':visit,'status':'Atvyko','mileage':12345},409)

    def test_05_free_slots(self):
        """LT-05 | FR-07 | Laisvų laikų sąrašas nebesiūlo praėjusių pradžių, dabartinės minutės riba tiksli."""
        query=f'free_slots?car_id={self.cars[1]}&date=2028-02-01&minutes=60'
        before=self.database();self.clock('2028-02-01T09:00:00')
        status,body=self.client.request(query);self.assertEqual(status,200)
        self.assertTrue(any(s['start_at']=='2028-02-01T09:00' for s in body['slots']))
        self.clock('2028-02-01T09:00:00.000001')
        for actor in (self.client,self.adviser,self.boss):
            status,body=actor.request(query);self.assertEqual(status,200)
            self.assertTrue(body['slots'])
            self.assertTrue(all(s['start_at']>'2028-02-01T09:00' for s in body['slots']))
        self.assertEqual(self.client.request(query.replace('2028-02-01','2028-01-31'))[1]['slots'],[])
        self.assertEqual(self.database(),before)

    def test_06_lithuanian_timezone(self):
        """LT-06 | FR-07; FR-08; FR-09 | UTC palyginimas atitinka Lietuvos žiemos, vasaros ir laiko keitimo dienų laiką."""
        for month,day,offset in [(1,15,2),(7,15,3),(3,29,3),(10,25,2)]:
            with self.subTest(month=month,day=day):
                utc=datetime(2026,month,day,9-offset,tzinfo=timezone.utc)
                self.assertEqual(utc.astimezone(main.VISIT_TIMEZONE).hour,9)
                main.appointment_now=lambda:utc
                stamp=f'2026-{month:02d}-{day:02d}'
                visit=self.ok(self.client,'appointment_save',{**self.slot,'start_at':stamp+'T09:00','end_at':stamp+'T10:00'})
                self.ok(self.adviser,'appointment_status',{'id':visit,'status':'Neatvyko'})
                main.appointment_now=lambda:utc+timedelta(seconds=1)
                self.refused_without_changes(self.client,'appointment_save',{**self.slot,'start_at':stamp+'T09:00','end_at':stamp+'T10:00'},400)

    def test_07_input_time_contract(self):
        """LT-07 | FR-08 | Vizito laukai priima Lietuvos vietinį laiką minučių tikslumu, o UTC ir poslinkio įvestį atmeta."""
        self.clock('2028-02-01T08:00')
        for start,end in [('2028-02-02T09:00Z','2028-02-02T10:00Z'),('2028-02-02T09:00+02:00','2028-02-02T10:00+02:00'),('2028-02-02T09:00:01','2028-02-02T10:00:01')]:
            self.refused_without_changes(self.adviser,'appointment_save',{**self.slot,'start_at':start,'end_at':end},400)

    def test_08_conflicts_and_adjacent_slots(self):
        """LT-08 | FR-08; VT-01 | Laiko kontrolė išlaiko automobilio ir darbo vietos konfliktus bei leidžia gretimus laikus."""
        self.clock('2028-02-01T08:00')
        for data in ({**self.slot,'car_id':self.cars[1]},{**self.slot,'bay':2}):
            self.refused_without_changes(self.adviser,'appointment_save',data,409)
        self.ok(self.adviser,'appointment_save',{**self.slot,'car_id':self.cars[1],'bay':2})
        self.ok(self.adviser,'appointment_save',{**self.slot,'start_at':'2028-02-01T10:00','end_at':'2028-02-01T11:00'})

    def test_09_reschedule_and_history(self):
        """LT-09 | FR-08; FR-09; NF-16 | Perkėlimas į praeitį atmetamas, į ateitį leidžiamas, paleidimas istorijos neperrašo."""
        self.clock('2028-02-01T09:01')
        before=self.database();main.init_db(seed=False);main.init_db(seed=False)
        self.assertEqual(self.database(),before)
        self.refused_without_changes(self.client,'appointment_save',{**self.slot,'id':self.visit,'start_at':'2028-02-01T08:30','end_at':'2028-02-01T09:30'},400)
        self.ok(self.client,'appointment_save',{**self.slot,'id':self.visit,'start_at':'2028-02-02T09:00','end_at':'2028-02-02T10:00'})
        self.assertEqual(self.sql('SELECT client_id,start_at FROM appointments WHERE id=?',(self.visit,)),[(self.c1,'2028-02-02T09:00')])
        self.assertEqual(self.sql('PRAGMA foreign_key_check'),[])

    def test_10_timezone_fallback_and_clock(self):
        """LT-10 | FR-08; NF-08 | Be sistemos IANA bazės naudojami paketo duomenys, serverio laikrodis išlieka su Lietuvos zona."""
        with patch.object(main,'ZoneInfo') as factory:
            factory.side_effect=main.ZoneInfoNotFoundError('test')
            factory.from_file.side_effect=ZoneInfo.from_file
            zone=main.load_visit_timezone()
        self.assertEqual(datetime(2026,1,15,9,tzinfo=zone).utcoffset(),timedelta(hours=2))
        self.assertEqual(datetime(2026,7,15,9,tzinfo=zone).utcoffset(),timedelta(hours=3))
        utc=datetime(2026,7,15,6,tzinfo=timezone.utc)
        class FixedDatetime(datetime):
            @classmethod
            def now(cls,tz=None):return utc.astimezone(tz)
        with patch.object(main,'datetime',FixedDatetime):
            actual=self.old_clock()
        self.assertEqual(actual.hour,9)
        self.assertEqual(actual.tzinfo,main.VISIT_TIMEZONE)
        self.assertEqual(actual.astimezone(timezone.utc),utc)


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(VisitTimeTests)
    result=unittest.TextTestRunner(verbosity=2,resultclass=JsonResult).run(suite)
    report={'executed_at':datetime.now(timezone.utc).isoformat(),'environment':{'python':platform.python_version(),'platform':platform.platform(),'sqlite':sqlite3.sqlite_version},'type':'Vizitų laiko HTTP/DB regresiniai atvejai; laikina DB; valdomas dalykinis laikrodis','total':result.testsRun,'passed':sum(x['passed'] for x in result.records),'tests':result.records}
    Path(__file__).with_name('test_visit_time_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
