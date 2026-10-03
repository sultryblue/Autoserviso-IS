"""Pakartojami sistemos testai per HTTP. Nenaudoja ir nekeičia servisas.db."""
import http.client
import json
import sqlite3
import tempfile
import threading
import time
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import main

RESULTS=[]
class Browser:
    def __init__(self, port): self.port,self.cookie,self.csrf=port,'',''
    def request(self,action,data=None,csrf=True):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        headers={'Content-Type':'application/json','Cookie':self.cookie}
        if csrf: headers['X-CSRF-Token']=self.csrf
        conn.request('POST' if data is not None else 'GET','/api/'+action,
                     json.dumps(data) if data is not None else None,headers)
        r=conn.getresponse();body=json.loads(r.read())
        if r.getheader('Set-Cookie'): self.cookie=r.getheader('Set-Cookie').split(';')[0]
        status=r.status;conn.close()
        if status==200 and action=='state': self.csrf=body['csrf']
        return status,body
    def login(self,username,password='Demo2026!'):
        status,_=self.request('login',{'username':username,'password':password})
        assert status==200
        self.request('state')

def check(number,scenario,req,description,steps,fn,expected):
    started=time.perf_counter()
    try:
        value=fn()
        assert value==expected,f'Laukta {expected!r}, gauta {value!r}'
        passed=True;result=f'Gauta: {value}. Atitiko tikėtiną rezultatą.'
    except Exception as e:
        passed=False;result=str(e)
    RESULTS.append({'id':f'TA-{number:02d}','scenario':scenario,'requirement':req,'description':description,
       'steps':steps,'expected':str(expected),'result':result,'passed':passed,
       'duration_ms':round((time.perf_counter()-started)*1000,2)})
    print(f"{'OK' if passed else 'KLAIDA'} TA-{number:02d} {description}")

def run():
    RESULTS.clear()
    old=main.DB
    with tempfile.TemporaryDirectory() as tmp:
        main.DB=Path(tmp)/'test.db';main.init_db(seed=False)
        server=main.ThreadingHTTPServer(('127.0.0.1',0),main.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        port=server.server_port;anon=Browser(port);a=Browser(port);m=Browser(port);m2=Browser(port);boss=Browser(port)
        check(1,'TS-01','FR-01','Duomenys be prisijungimo nepasiekiami','GET /api/state be sesijos.',lambda:anon.request('state')[0],401)
        check(2,'TS-01','FR-01','Neteisingas slaptažodis','Prisijungti vadybininku su neteisingu slaptažodžiu.',lambda:a.request('login',{'username':'vadybininkas','password':'blogas'})[0],401)
        check(3,'TS-01','FR-01','Teisingas prisijungimas','Prisijungti vadybininku su demonstraciniu slaptažodžiu.',lambda:a.request('login',{'username':'vadybininkas','password':'Demo2026!'})[0],200)
        a.request('state');m.login('mechanikas');m2.login('mechanikas2');boss.login('vadovas')
        check(4,'TS-02','FR-04','Privalomi kliento duomenys','Kurti klientą tuščiu vardu.',lambda:a.request('client_save',{'name':'','phone':'+37060000000'})[0],400)
        check(5,'TS-02','FR-04','Kliento registravimas','Įrašyti vardą, telefoną ir el. paštą.',lambda:a.request('client_save',{'name':'Testo klientas','phone':'+37060000000','email':'test@example.com'})[0],200)
        check(6,'TS-03','FR-05','Automobilio registravimas','Sukurti automobilį TEST01 ir susieti su klientu 1.',lambda:a.request('car_save',{'client_id':1,'plate':'TEST01','make':'Toyota','model':'Corolla','year':2018})[0],200)
        check(7,'TS-03','FR-05','Automobilio numerio unikalumas','Pakartoti automobilio TEST01 registravimą.',lambda:a.request('car_save',{'client_id':1,'plate':'test01','make':'Toyota','model':'Corolla','year':2018})[0],409)
        slot={'car_id':1,'start_at':'2026-10-01T09:00','end_at':'2026-10-01T10:00','bay':1,'problem':'Periodinė priežiūra'}
        check(8,'TS-04','FR-08','Vizito registravimas','Registruoti 09:00–10:00 pirmoje darbo vietoje.',lambda:a.request('appointment_save',slot)[0],200)
        check(9,'TS-05','FR-08','Persidengiančio laiko blokavimas','Registruoti tą patį automobilį 09:30–10:30.',lambda:a.request('appointment_save',{**slot,'start_at':'2026-10-01T09:30','end_at':'2026-10-01T10:30'})[0],409)
        check(10,'TS-05','FR-08','Gretimi laikai leidžiami','Registruoti naują vizitą 10:00–11:00.',lambda:a.request('appointment_save',{**slot,'start_at':'2026-10-01T10:00','end_at':'2026-10-01T11:00'})[0],200)
        check(11,'TS-06','FR-09','Vizito atšaukimas','Atšaukti antrą vizitą.',lambda:a.request('appointment_status',{'id':2,'status':'Atšauktas'})[0],200)
        check(12,'TS-07','FR-10','Priėmimas sukuria užsakymą','Vizitui 1 pažymėti Atvyko ir 120000 km ridą.',lambda:a.request('appointment_status',{'id':1,'status':'Atvyko','mileage':120000})[0],200)
        check(13,'TS-07','FR-10','Pakartotinis priėmimas nesukuria antro užsakymo','Pakartoti Atvyko tam pačiam vizitui.',lambda:a.request('appointment_status',{'id':1,'status':'Atvyko','mileage':120000})[0],409)
        check(14,'TS-15','FR-13','Nebaigto užsakymo uždarymas blokuojamas','Uždaryti ką tik sukurtą užsakymą.',lambda:a.request('order_close',{'id':1,'note':'Atiduota'})[0],409)
        a.request('diagnostic_assign',{'order_id':1,'mechanic_id':3})
        m.request('diagnostic_add',{'assignment_id':1,'result':'Reikia priežiūros','proposed_works':'Alyvos keitimas'})
        boss.request('user_save',{'username':'remontas','name':'Remonto klientas','role':'klientas','client_id':1,'password':'Demo2026!!'})
        customer=Browser(port);customer.login('remontas','Demo2026!!')
        estimate={'order_id':1,'lines':[{'kind':'Darbas','title':'Alyvos keitimas','quantity_1000':1000,'unit_cents':3500},{'kind':'Detalė','title':'Alyva, 1 l','quantity_1000':5000,'unit_cents':1000}]}
        check(15,'TS-08','FR-14','Sąmatos parengimas','Įrašyti 35 Eur darbą ir 5 vnt. po 10 Eur.',lambda:a.request('estimate_save',estimate)[0],200)
        check(16,'TS-09','NF-06','Tiksli sąmatos suma','Perskaityti išsaugotą sąmatą: 35 + 5 × 10.',lambda:a.request('state')[1]['estimates'][-1]['total_cents'],8500)
        check(17,'TS-08','FR-14','Neigiamas kiekis atmetamas','Keisti rengiamą versiją nurodant kiekį -1.',lambda:a.request('estimate_save',{'order_id':1,'id':1,'lines':[{'kind':'Darbas','title':'Bloga eilutė','quantity_1000':-1,'unit_cents':3000}]})[0],400)
        check(18,'TS-18','NF-05','Atmetus įvestį išsaugoma ankstesnė būsena','Patikrinti sąmatų skaičių po TA-17.',lambda:len(a.request('state')[1]['estimates']),1)
        check(19,'TS-10','FR-15','Sąmatos pateikimas klientui','Sąmatą 1 pažymėti Pateikta.',lambda:a.request('estimate_submit',{'id':1})[0],200)
        check(20,'TS-10','FR-16','Darbuotojas nepriima kliento sprendimo','Vadybininkui mėginti patvirtinti sąmatą.',lambda:a.request('estimate_decide',{'id':1,'status':'Patvirtinta','decision_note':''})[0],403)
        check(21,'TS-10','FR-16','Klientas patvirtina sąmatą be neprivalomos pastabos','Klientui priimti sprendimą savitarnoje.',lambda:customer.request('estimate_decide',{'id':1,'status':'Patvirtinta','decision_note':''})[0],200)
        check(22,'TS-11','FR-17','Nauja versija išlaiko ankstesnį patvirtinimą','Papildyti sąmatą detale iki darbų pradžios.',lambda:(a.request('estimate_save',{'order_id':1,'lines':[{'kind':'Detalė','title':'Tarpinė','quantity_1000':1000,'unit_cents':500}]})[0],a.request('state')[1]['estimates'][0]['status']),(200,'Patvirtinta'))
        check(23,'TS-11','FR-16','Sena versija nebegali būti patvirtinta','Mėginti patvirtinti sąmatą 1 po versijos 2 sukūrimo.',lambda:customer.request('estimate_decide',{'id':1,'status':'Patvirtinta','decision_note':'Senas sprendimas'})[0],409)
        a.request('estimate_submit',{'id':2});customer.request('estimate_decide',{'id':2,'status':'Patvirtinta','decision_note':'Patvirtinta antroji versija.'})
        check(24,'TS-12','FR-20','Darbo paskyrimas','Darbą 1 paskirti mechanikui 3.',lambda:a.request('task_assign',{'id':1,'mechanic_id':3})[0],200)
        check(25,'TS-19','NF-12','Kitas mechanikas negali vykdyti darbo','Mechanikui 4 bandyti pradėti darbą 1.',lambda:m2.request('task_status',{'id':1,'status':'Vykdomas'})[0],403)
        check(26,'TS-19','NF-12','Mechanikui neperduodami klientų kontaktai ir kainos','Prisijungus mechaniku patikrinti atsakymo objektus.',lambda:any(k in m.request('state')[1] for k in ('clients','lines','estimates')),False)
        check(27,'TS-13','FR-21','Mechanikas pradeda savo darbą','Mechanikui 3 pradėti darbą 1.',lambda:m.request('task_status',{'id':1,'status':'Vykdomas'})[0],200)
        check(28,'TS-11','FR-17','Pradėjus darbus galima siūlyti papildymą','Kurti trečią versiją tame pačiame užsakyme.',lambda:a.request('estimate_save',{'order_id':1,'lines':[{'kind':'Detalė','title':'Papildoma detalė','quantity_1000':1000,'unit_cents':2000}]})[0],200)
        a.request('estimate_submit',{'id':3});customer.request('estimate_decide',{'id':3,'status':'Atmesta'})
        check(29,'TS-14','FR-13','Automobilis neparuošiamas esant nebaigtam darbui','Vykdomą užsakymą pažymėti Paruoštas.',lambda:a.request('order_ready',{'id':1})[0],409)
        check(30,'TS-13','FR-22','Darbo sustabdymas','Sustabdyti darbą su priežastimi ir 10 min trukme.',lambda:m.request('task_status',{'id':1,'status':'Sustabdytas','note':'Laukiama filtro.','minutes':10})[0],200)
        check(31,'TS-13','FR-22','Darbo tęsimas','Tęsti sustabdytą darbą.',lambda:m.request('task_status',{'id':1,'status':'Vykdomas'})[0],200)
        check(32,'TS-13','FR-22','Darbo užbaigimas','Baigti darbą su 35 min trukme ir pastaba.',lambda:m.request('task_status',{'id':1,'status':'Baigtas','note':'Alyva ir filtras pakeisti.','minutes':35})[0],200)
        check(33,'TS-14','FR-13','Paruošimas atidavimui','Po visų darbų užbaigimo pažymėti Paruoštas.',lambda:a.request('order_ready',{'id':1})[0],200)
        settle_and_handover(a,1,'regression-close-01')
        check(34,'TS-15','FR-13','Užsakymo uždarymas','Po atsiskaitymo ir perdavimo įrašyti pastabą ir uždaryti.',lambda:a.request('order_close',{'id':1,'note':'Automobilis atiduotas klientui.'})[0],200)
        check(35,'TS-02','FR-04','Kliento archyvavimas išsaugo istoriją','Archyvuoti klientą be aktyvių vizitų ir darbų.',lambda:a.request('client_archive',{'id':1})[0],200)
        check(36,'TS-17','FR-03','Vadybininkas negali kurti paskyrų','Vadybininkui mėginti sukurti mechaniko paskyrą.',lambda:a.request('user_save',{'username':'testas','name':'Testas','role':'mechanikas','password':'Slaptazodis1!'})[0],403)
        check(37,'TS-17','FR-03','Vadovas sukuria paskyrą','Vadovui sukurti naują mechaniką.',lambda:boss.request('user_save',{'username':'testas','name':'Testinis mechanikas','role':'mechanikas','password':'Slaptazodis1!'})[0],200)
        check(38,'TS-20','NF-13','Keitimas be CSRF kodo atmetamas','Pateikti galiojančią sesiją be X-CSRF-Token.',lambda:a.request('client_save',{'name':'Kitas','phone':'+37060000003'},csrf=False)[0],403)
        check(39,'TS-21','PF-02','Veiksmų atsekamumas','Patikrinti, kad žurnale yra užsakymo uždarymas.',lambda:any(x['entity']=='Užsakymas' and x['action']=='Uždarytas' for x in boss.request('state')[1]['audit']),True)
        check(40,'TS-01','PF-01','Atsijungimas panaikina prieigą','Atsijungti ir vėl kreiptis į /api/state.',lambda:(a.request('logout',{}),a.request('state')[0])[1],401)
        check(41,'TS-18','NF-05','Duomenys išlieka naujame DB prisijungime','Uždaryti HTTP sesiją ir perskaityti būseną per naują SQLite ryšį.',lambda:main.connect().execute('SELECT status FROM orders WHERE id=1').fetchone()[0],'Uždarytas')
        stage1_checks(port,a,boss,m)
        stage2_checks(port,a,boss,m,m2)
        stage3_checks(port,a,boss,m)
        stage4_checks(port,a,boss,m)
        stage5a_checks(port,a,boss)
        server.shutdown();server.server_close()
        stage1_migration(Path(tmp))
        stage2_migration(Path(tmp))
        stage3_migration(Path(tmp))
        stage4_migration(Path(tmp))
        stage5a_migration(Path(tmp))
        main.DB=old
    report={'executed_at':datetime.now().isoformat(timespec='seconds'),'environment':'Python '+__import__('sys').version.split()[0],
            'type':'HTTP ir duomenų vientisumo testai vietinėje laikinoje SQLite bazėje','tests':RESULTS,
            'passed':sum(t['passed'] for t in RESULTS),'total':len(RESULTS)}
    path=Path(__file__).with_name('test_results.json');path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"Rezultatas: {report['passed']}/{report['total']}; {path.name}")
    return report['passed']==report['total']

def stage1_checks(port, adviser, boss, mechanic):
    """Stage 1 checks; the earlier employee flow remains unchanged until stage 2."""
    adviser.login('vadybininkas')
    def setup(action,data):
        status,body=boss.request(action,data)
        assert status==200,body
        return body['id']
    def test(title,fn,expected,req='NF-10'):
        check(len(RESULTS)+1,'TS-22',req,title,title,fn,expected)
    own=setup('client_save',{'name':'Savitarnos klientas','phone':'+37060000010','email':'own@example.com'})
    other=setup('client_save',{'name':'Kitas klientas','phone':'+37060000011','email':'other@example.com'})
    account=setup('user_save',{'name':'Savitarnos klientas','username':'klientas_test','role':'klientas','client_id':own,'password':'Demo2026!!'})
    other_account=setup('user_save',{'name':'Kitas klientas','username':'klientas_kitas','role':'klientas','client_id':other,'password':'Demo2026!!'})
    car_data={'plate':'OWN01','make':'Toyota','model':'Yaris','year':2020}
    car=setup('car_save',{**car_data,'client_id':own})
    foreign_car=setup('car_save',{**car_data,'client_id':other,'plate':'OTHER01'})
    visit={'car_id':car,'start_at':'2026-11-02T09:00','end_at':'2026-11-02T10:00','bay':1,'problem':'Patikra'}
    foreign_visit=setup('appointment_save',{**visit,'car_id':foreign_car})
    setup('appointment_status',{'id':foreign_visit,'status':'Atvyko','mileage':12345})
    foreign_order=next(o['id'] for o in boss.request('state')[1]['orders'] if o['appointment_id']==foreign_visit)
    client=Browser(port); stranger=Browser(port)
    test('Klientas prisijungia',lambda:client.request('login',{'username':'klientas_test','password':'Demo2026!!'})[0],200,'FR-01')
    client.request('state');stranger.login('klientas_kitas','Demo2026!!')
    test('Klientas mato savo kontaktus',lambda:client.request('state')[1]['client']['id'],own,'FR-04')
    test('Klientas mato tik savo automobilius',lambda:[x['id'] for x in client.request('state')[1]['cars']],[car],'FR-06')
    test('Kliento atsakyme tik leistini savitarnos objektai',lambda:sorted(client.request('state')[1]),sorted(['user','client','cars','appointments','orders','csrf','estimates','lines','decisions','tasks','payments']),'NF-11')
    test('Kitas klientas gauna savo, ne pirmojo kliento automobilį',lambda:[x['id'] for x in stranger.request('state')[1]['cars']],[foreign_car],'NF-11')
    test('Svetimas automobilis pagal ID neperskaitomas',lambda:client.request(f'client/car?id={foreign_car}')[0],404,'FR-06')
    test('Svetimas vizitas pagal ID neperskaitomas',lambda:client.request(f'client/appointment?id={foreign_visit}')[0],404,'FR-09')
    test('Svetimas užsakymas pagal ID neperskaitomas',lambda:client.request(f'client/order?id={foreign_order}')[0],404,'FR-12')
    test('Savo automobilis pagal ID perskaitomas',lambda:client.request(f'client/car?id={car}')[1]['plate'],'OWN01','FR-05')
    contacts={'id':own,'name':'Atnaujintas klientas','phone':'+37060000012','email':'new@example.com'}
    test('Savo kontaktai redaguojami',lambda:client.request('client_save',contacts)[0],200,'FR-04')
    test('Kontaktų pakeitimas išsaugotas',lambda:client.request('state')[1]['client']['email'],'new@example.com','FR-04')
    test('Svetimi kontaktai neredaguojami',lambda:client.request('client_save',{**contacts,'id':other})[0],404,'NF-11')
    test('Svetimas automobilis neredaguojamas',lambda:client.request('car_save',{**car_data,'id':foreign_car,'client_id':own})[0],404,'NF-11')
    test('Savas automobilis redaguojamas ir numeris normalizuojamas',lambda:client.request('car_save',{**car_data,'id':car,'plate':' own 01 '})[0],200,'FR-05')
    test('Normalizuotas numeris išsaugotas',lambda:client.request(f'client/car?id={car}')[1]['plate'],'OWN01','FR-05')
    def add_car():
        status,body=client.request('car_save',{**car_data,'plate':' own 02 ','client_id':other})
        with main.connect() as c:
            record=c.execute('SELECT client_id,plate FROM cars WHERE id=?',(body.get('id'),)).fetchone()
        return status,tuple(record)
    test('Kuriant automobilį savininkas imamas iš sesijos, ne iš pateikto ID',add_car,(200,(own,'OWN02')),'FR-05')
    test('Pasikartojantis automobilio numeris atmetamas',lambda:client.request('car_save',{**car_data,'plate':'own01'})[0],409,'FR-05')
    test('Svetimam automobiliui vizitas neregistruojamas',lambda:client.request('appointment_save',{**visit,'car_id':foreign_car})[0],404,'FR-08')
    test('Svetimas vizitas neredaguojamas',lambda:client.request('appointment_save',{**visit,'id':foreign_visit})[0],404,'FR-09')
    test('Svetimas vizitas neatšaukiamas',lambda:client.request('appointment_status',{'id':foreign_visit,'status':'Atšauktas'})[0],404,'FR-09')
    query=f'free_slots?car_id={car}&date=2026-11-02&minutes=60'
    test('Užimta darbo vieta nerodoma tarp laisvų laikų',lambda:any(s['start_at']==visit['start_at'] and s['bay']==1 for s in client.request(query)[1]['slots']),False,'FR-07')
    test('Laisva kita darbo vieta rodoma',lambda:any(s['start_at']==visit['start_at'] and s['bay']==2 for s in client.request(query)[1]['slots']),True,'FR-07')
    test('Laisvų laikų paieška svetimam automobiliui draudžiama',lambda:client.request(f'free_slots?car_id={foreign_car}&date=2026-11-02')[0],404,'NF-11')
    test('Paieškoje negalima išskirti svetimo vizito ID',lambda:client.request(query+f'&id={foreign_visit}')[0],404,'NF-11')
    ids={}
    def book():
        status,body=client.request('appointment_save',{**visit,'bay':2})
        ids['visit']=body.get('id');return status
    test('Laisvas laikas priimamas savo automobiliui',book,200,'FR-08')
    test('Vizito būsena Patvirtintas',lambda:client.request(f"client/appointment?id={ids['visit']}")[1]['status'],'Patvirtintas','FR-08')
    test('Klientas mato tik savo vizitus',lambda:[x['id'] for x in client.request('state')[1]['appointments']],[ids['visit']],'NF-11')
    test('Persidengiantis vizitas atmetamas',lambda:client.request('appointment_save',{**visit,'bay':2,'start_at':'2026-11-02T09:30','end_at':'2026-11-02T10:30'})[0],409,'FR-08')
    test('To paties automobilio konfliktas tikrinamas ir kitoje vietoje',lambda:client.request('appointment_save',{**visit,'bay':1,'start_at':'2026-11-02T09:30','end_at':'2026-11-02T10:30'})[0],409,'FR-08')
    test('Gretimi nepersidengiantys intervalai leidžiami',lambda:client.request('appointment_save',{**visit,'bay':2,'start_at':'2026-11-02T10:00','end_at':'2026-11-02T11:00'})[0],200,'FR-08')
    test('Patvirtintą savo vizitą galima keisti',lambda:client.request('appointment_save',{**visit,'id':ids['visit'],'bay':2,'problem':'Pakeista problema'})[0],200,'FR-09')
    test('Keičiant vizitą jo paties intervalas laikomas laisvu',lambda:any(s['start_at']==visit['start_at'] and s['bay']==2 for s in client.request(query+f"&id={ids['visit']}")[1]['slots']),True,'FR-07')
    test('Klientas negali pats priimti automobilio',lambda:client.request('appointment_status',{'id':ids['visit'],'status':'Atvyko','mileage':1})[0],403,'NF-10')
    test('Klientas gali atšaukti savo Patvirtintą vizitą',lambda:client.request('appointment_status',{'id':ids['visit'],'status':'Atšauktas'})[0],200,'FR-09')
    test('Atšaukto vizito keisti negalima',lambda:client.request('appointment_save',{**visit,'id':ids['visit'],'bay':2})[0],409,'FR-09')
    # UI-laisvumas nėra rezervacija: darbuotojas užima anksčiau klientui rodytą laiką.
    race={**visit,'start_at':'2026-11-02T12:00','end_at':'2026-11-02T13:00'}
    client.request(query)
    setup('appointment_save',{**race,'car_id':foreign_car})
    test('Po laisvų laikų peržiūros užimtas laikas atmetamas registruojant',lambda:client.request('appointment_save',race)[0],409,'FR-08')
    accepted=setup('appointment_save',{**race,'bay':2})
    test('Vadybininkas ir toliau priima automobilį',lambda:adviser.request('appointment_status',{'id':accepted,'status':'Atvyko','mileage':15000})[0],200,'FR-10')
    oid=next(o['id'] for o in boss.request('state')[1]['orders'] if o['appointment_id']==accepted)
    with main.connect() as c:
        c.execute('UPDATE orders SET closing_note=? WHERE id=?',('VIDINĖ PASTABA',oid))
    test('Savo užsakymo būsena perskaitoma',lambda:client.request(f'client/order?id={oid}')[1]['status'],'Naujas','FR-12')
    test('Klientas mato tik savo užsakymus',lambda:[x['id'] for x in client.request('state')[1]['orders']],[oid],'NF-11')
    test('Vidinė užsakymo pastaba neperduodama',lambda:'closing_note' in client.request(f'client/order?id={oid}')[1],False,'FR-12')
    test('Priimto savo vizito keisti negalima',lambda:client.request('appointment_save',{**race,'id':accepted,'bay':2})[0],409,'FR-09')
    test('Priimto savo vizito atšaukti negalima',lambda:client.request('appointment_status',{'id':accepted,'status':'Atšauktas'})[0],409,'FR-09')
    for action in ('user_save','user_disable','client_archive','estimate_save','estimate_submit','estimate_decide','task_assign','task_status','order_ready','order_close','order_cancel'):
        test('Klientui neprieinamas svetimas arba darbuotojo veiksmas '+action,lambda action=action:client.request(action,{'id':oid})[0],404 if action=='estimate_decide' else 403)
    test('Kliento keitimas be CSRF atmetamas',lambda:client.request('client_save',contacts,csrf=False)[0],403,'NF-13')
    test('Mechanikas negali redaguoti kliento kontaktų',lambda:mechanic.request('client_save',contacts)[0],403,'NF-12')
    test('Mechanikas negauna klientų paskyrų sąrašo',lambda:any(x['role']=='klientas' for x in mechanic.request('state')[1]['users']),False,'NF-12')
    test('Vadovas negali sukurti antros to paties kliento paskyros',lambda:boss.request('user_save',{'username':'dubliuota','name':'Dubliuota','role':'klientas','client_id':own,'password':'Demo2026!!'})[0],409,'FR-02')
    test('Vadovas išjungia kliento paskyrą',lambda:boss.request('user_disable',{'id':account})[0],200,'FR-03')
    test('Išjungta paskyra netęsia jau sukurtos sesijos',lambda:client.request('state')[0],401,'NF-09')
    test('Neaktyvus klientas negali prisijungti',lambda:Browser(port).request('login',{'username':'klientas_test','password':'Demo2026!!'})[0],401,'NF-09')
    def constraint(sql,args):
        with main.connect() as c:
            try: c.execute(sql,args)
            except sqlite3.IntegrityError: return True
            c.rollback();return False
    test('DB draudžia kliento rolę be kliento ryšio',lambda:constraint("UPDATE users SET client_id=NULL WHERE id=?",(account,)),True,'FR-02')
    unlinked=setup('client_save',{'name':'Be paskyros','phone':'+37060000013'})
    test('DB draudžia darbuotojui kliento ryšį',lambda:constraint("UPDATE users SET client_id=? WHERE username='mechanikas'",(unlinked,)),True,'FR-02')
    test('DB draudžia dvi paskyras vienam klientui',lambda:constraint('UPDATE users SET client_id=? WHERE id=?',(other,account)),True,'FR-02')
    test('Atmestos svetimų duomenų užklausos jų nepakeitė',lambda:stranger.request(f'client/car?id={foreign_car}')[1]['plate'],'OTHER01','NF-11')

def stage1_migration(folder):
    """A real old-schema DB is upgraded without losing its IDs or history."""
    old=main.DB
    legacy=folder/'legacy.db'
    schema=(main.ROOT/'testdata/schema_stage3.sql').read_text(encoding='utf-8')
    schema=schema.split('CREATE UNIQUE INDEX IF NOT EXISTS idx_active_diagnostic')[0]
    schema=schema.replace("'klientas',",'').replace(",\n client_id INTEGER UNIQUE REFERENCES clients(id),\n CHECK((role='klientas' AND client_id IS NOT NULL) OR (role<>'klientas' AND client_id IS NULL))",'')
    schema=schema.replace('Patvirtintas', 'Suplanuotas',2)
    with sqlite3.connect(legacy) as c:
        c.executescript(schema)
        c.execute("INSERT INTO users VALUES(7,'senas','Senas darbuotojas','vadybininkas','saugoma-maisa',1)")
        c.execute("INSERT INTO clients VALUES(9,'Senas klientas','1234567','',1)")
        c.execute("INSERT INTO cars VALUES(11,9,'OLD01','Toyota','Yaris',2018)")
        c.execute("INSERT INTO appointments VALUES(13,11,'2026-11-01T08:00','2026-11-01T09:00',1,'Istorija','Suplanuotas',7)")
        c.execute("INSERT INTO orders(id,appointment_id,mileage,created_at) VALUES(15,13,123,'2026-11-01')")
        c.execute("INSERT INTO audit(id,user_id,entity,entity_id,action,happened_at) VALUES(17,7,'Vizitas',13,'Sukurtas','2026-11-01')")
    main.DB=legacy
    def migrate():
        main.init_db(seed=False)
        with main.connect() as c:
            return (c.execute('SELECT id,password_hash,client_id FROM users').fetchone()[:],
                    c.execute('SELECT id,status FROM appointments').fetchone()[:],
                    c.execute('SELECT id,appointment_id FROM orders').fetchone()[:],
                    c.execute('SELECT id FROM audit').fetchone()[0],c.execute('PRAGMA foreign_key_check').fetchall())
    expected=((7,'saugoma-maisa',None),(13,'Patvirtintas'),(15,13),17,[])
    check(len(RESULTS)+1,'TS-23','NF-05','Sena DB migruoja išlaikydama paskyras ir istoriją','Atnaujinti senos schemos DB.',migrate,expected)
    check(len(RESULTS)+1,'TS-23','NF-05','Pakartotinis paleidimas nekeičia migracijos duomenų','Antrą kartą inicializuoti tą pačią DB.',migrate,expected)
    main.DB=old

def stage2_checks(port, adviser, boss, mechanic, other_mechanic):
    adviser.login('vadybininkas')
    def test(title,fn,expected,req='FR-17'):
        check(len(RESULTS)+1,'TS-24',req,title,title,fn,expected)
    def ok(browser,action,data):
        code,body=browser.request(action,data)
        assert code==200,(action,body)
        return body['id']
    def state(): return boss.request('state')[1]
    def sql(query,args=()):
        with main.connect() as c: return [tuple(x) for x in c.execute(query,args)]
    def rejected(query,args=()):
        with main.connect() as c:
            try: c.execute(query,args)
            except sqlite3.IntegrityError: return True
            c.rollback();return False
    cid=ok(adviser,'client_save',{'name':'Versijų klientas','phone':'+37060000999'})
    ok(boss,'user_save',{'username':'versijos','name':'Versijų klientas','role':'klientas','client_id':cid,'password':'Demo2026!!'})
    client=Browser(port);client.login('versijos','Demo2026!!')
    foreign=Browser(port);foreign.login('klientas_kitas','Demo2026!!')
    car=ok(client,'car_save',{'plate':'VERS01','make':'Toyota','model':'Yaris','year':2020})
    visit=ok(client,'appointment_save',{'car_id':car,'start_at':'2026-12-01T09:00','end_at':'2026-12-01T10:00','bay':1,'problem':'Gedimas'})
    ok(adviser,'appointment_status',{'id':visit,'status':'Atvyko','mileage':140000})
    oid=next(o['id'] for o in state()['orders'] if o['appointment_id']==visit)
    line={'kind':'Darbas','title':'Pagrindinis remontas','quantity_1000':1000,'unit_cents':10000}
    payload={'order_id':oid,'lines':[line]}
    test('Be diagnostikos sąmata nerengiama',lambda:adviser.request('estimate_save',payload)[0],409,'FR-14')
    test('Mechanikas negali sau paskirti diagnostikos',lambda:mechanic.request('diagnostic_assign',{'order_id':oid,'mechanic_id':3})[0],403,'FR-10A')
    test('Vadybininkas paskiria aktyvų mechaniką',lambda:adviser.request('diagnostic_assign',{'order_id':oid,'mechanic_id':3})[0],200,'FR-10A')
    aid=sql('SELECT id FROM diagnostic_assignments WHERE order_id=? AND ended_at IS NULL',(oid,))[0][0]
    d={'assignment_id':aid,'result':'Nustatytas gedimas','proposed_works':'Pagrindinis remontas'}
    test('Kitas mechanikas diagnostikos neįrašo',lambda:other_mechanic.request('diagnostic_add',d)[0],403,'FR-11')
    test('Paskirtas mechanikas įrašo diagnostiką',lambda:mechanic.request('diagnostic_add',d)[0],200,'FR-11')
    test('Diagnostikoje kainos laukas nepriimamas',lambda:mechanic.request('diagnostic_add',{**d,'unit_cents':100})[0],400,'FR-11')
    test('Vadovas perleidžia diagnostiką',lambda:boss.request('diagnostic_assign',{'order_id':oid,'mechanic_id':4})[0],200,'FR-10A')
    aid2=sql('SELECT id FROM diagnostic_assignments WHERE order_id=? AND ended_at IS NULL',(oid,))[0][0]
    test('Vienas aktyvus paskyrimas ir išlikusi ankstesnė istorija',lambda:sql('SELECT COUNT(*),SUM(ended_at IS NULL) FROM diagnostic_assignments WHERE order_id=?',(oid,)),[(2,1)],'FR-10A')
    test('Ankstesnio paskyrimo diagnostikos įrašas išliko',lambda:len(sql('SELECT id FROM diagnostic_entries WHERE assignment_id=?',(aid,))),1,'NF-16')
    test('Buvęs vykdytojas neberašo į pasibaigusį paskyrimą',lambda:mechanic.request('diagnostic_add',d)[0],403,'FR-11')
    test('Buvęs vykdytojas nebemato perleistos aktyvios diagnostikos',lambda:any(x['order_id']==oid for x in mechanic.request('state')[1]['diagnostic_assignments']),False,'NF-12')
    test('Naujasis vykdytojas įrašo diagnostiką',lambda:other_mechanic.request('diagnostic_add',{**d,'assignment_id':aid2})[0],200,'FR-11')
    test('DB draudžia antrą aktyvų paskyrimą',lambda:rejected('INSERT INTO diagnostic_assignments(order_id,mechanic_id,assigned_by,assigned_at) VALUES(?,3,2,?)',(oid,main.now())),True,'NF-05')
    disabled=ok(boss,'user_save',{'username':'neaktyvus_mech','name':'Neaktyvus mechanikas','role':'mechanikas','password':'Demo2026!!'})
    ok(boss,'user_disable',{'id':disabled})
    test('Neaktyvus mechanikas nepaskiriamas',lambda:adviser.request('diagnostic_assign',{'order_id':oid,'mechanic_id':disabled})[0],409,'FR-10A')
    test('Klientui diagnostikos duomenys neperduodami',lambda:any(k.startswith('diagnostic') for k in client.request('state')[1]),False,'NF-12')
    v1=ok(adviser,'estimate_save',payload)
    test('Sukurta pirmoji versija',lambda:sql('SELECT version,status,total_cents FROM estimates WHERE id=?',(v1,)),[(1,'Rengiama',10000)],'FR-14')
    test('Rengiama versija redaguojama',lambda:adviser.request('estimate_save',{**payload,'id':v1,'lines':[{**line,'unit_cents':11000}]})[0],200,'FR-14')
    ok(adviser,'estimate_save',{**payload,'id':v1})
    test('Antros neišspręstos versijos kurti negalima',lambda:adviser.request('estimate_save',payload)[0],409,'FR-17')
    test('Juodraštis savitarnoje nerodomas',lambda:client.request(f'client/estimate?id={v1}')[0],404,'FR-15')
    test('Mechanikas negali rengti sąmatos',lambda:mechanic.request('estimate_save',payload)[0],403,'NF-12')
    test('Pateikiama konkreti versija',lambda:adviser.request('estimate_submit',{'id':v1})[0],200,'FR-15')
    first_line=sql('SELECT id FROM estimate_lines WHERE estimate_id=?',(v1,))[0][0]
    test('Pateikta versija neredaguojama per HTTP',lambda:adviser.request('estimate_save',{**payload,'id':v1})[0],409,'FR-15')
    test('DB draudžia pateiktos eilutės pakeitimą',lambda:rejected('UPDATE estimate_lines SET title=? WHERE id=?',('Pakeista',first_line)),True,'NF-16')
    test('DB draudžia pateiktos eilutės ištrynimą',lambda:rejected('DELETE FROM estimate_lines WHERE id=?',(first_line,)),True,'NF-16')
    test('DB draudžia naują eilutę pateiktoje versijoje',lambda:rejected("INSERT INTO estimate_lines(estimate_id,kind,title,quantity_1000,unit_cents,line_total_cents) VALUES(?,'Darbas','Įterpta',1000,1,1)",(v1,)),True,'NF-16')
    test('DB draudžia pateiktos sumos pakeitimą',lambda:rejected('UPDATE estimates SET total_cents=1 WHERE id=?',(v1,)),True,'NF-16')
    test('DB draudžia grąžinti pateiktą versiją į juodraštį',lambda:rejected("UPDATE estimates SET status='Rengiama' WHERE id=?",(v1,)),True,'NF-16')
    test('Klientas peržiūri savo pateiktą versiją',lambda:client.request(f'client/estimate?id={v1}')[1]['estimate']['total_cents'],10000,'FR-16')
    test('Svetimas klientas negali peržiūrėti versijos pakeitęs ID',lambda:foreign.request(f'client/estimate?id={v1}')[0],404,'NF-11')
    test('Svetimas klientas negali patvirtinti versijos',lambda:foreign.request('estimate_decide',{'id':v1,'status':'Patvirtinta'})[0],404,'NF-11')
    test('Vadovas negali priimti kliento sprendimo',lambda:boss.request('estimate_decide',{'id':v1,'status':'Patvirtinta'})[0],403,'FR-16')
    test('Kliento sprendimas be CSRF atmetamas',lambda:client.request('estimate_decide',{'id':v1,'status':'Patvirtinta'},csrf=False)[0],403,'NF-13')
    test('Klientas patvirtina v1',lambda:client.request('estimate_decide',{'id':v1,'status':'Patvirtinta'})[0],200,'FR-16')
    test('Antras prieštaraujantis sprendimas atmetamas',lambda:client.request('estimate_decide',{'id':v1,'status':'Atmesta'})[0],409,'FR-16')
    test('DB neleidžia perrašyti sprendimo',lambda:rejected("UPDATE estimate_decisions SET decision='Atmesta' WHERE estimate_id=?",(v1,)),True,'NF-16')
    test('DB neleidžia ištrinti sprendimo',lambda:rejected('DELETE FROM estimate_decisions WHERE estimate_id=?',(v1,)),True,'NF-16')
    t1=sql('SELECT id FROM tasks WHERE line_id=?',(first_line,))[0][0]
    test('Pirminė eilutė sukūrė vieną užduotį',lambda:len(sql('SELECT id FROM tasks WHERE line_id=?',(first_line,))),1,'FR-19')
    ok(adviser,'task_assign',{'id':t1,'mechanic_id':3})
    addition={'kind':'Darbas','title':'Papildomas remontas','quantity_1000':1000,'unit_cents':5000}
    test('Patvirtintos eilutės negalima pateikti kaip naujos',lambda:adviser.request('estimate_save',payload)[0],409,'FR-17')
    test('Negalima pakeisti perkeliamų kainų',lambda:adviser.request('estimate_save',{'order_id':oid,'lines':[{'origin_line_id':first_line,'unit_cents':1},addition]})[0],409,'FR-17')
    v2=ok(adviser,'estimate_save',{'order_id':oid,'lines':[addition]})
    test('V2 automatiškai perkelia ankstesnę origin eilutę',lambda:sql('SELECT origin_line_id FROM estimate_lines WHERE estimate_id=? AND origin_line_id IS NOT NULL',(v2,)),[(first_line,)],'FR-17')
    new_line=sql('SELECT id FROM estimate_lines WHERE estimate_id=? AND origin_line_id IS NULL',(v2,))[0][0]
    test('Nauja papildoma eilutė yra pirminė',lambda:sql('SELECT origin_line_id FROM estimate_lines WHERE id=?',(new_line,)),[(None,)],'FR-17')
    test('V2 rodoma suma 15000 centų',lambda:sql('SELECT total_cents FROM estimates WHERE id=?',(v2,)),[(15000,)],'NF-06')
    test('DB draudžia nepatvirtintos naujos eilutės užduotį',lambda:rejected('INSERT INTO tasks(line_id) VALUES(?)',(new_line,)),True,'FR-19')
    ok(adviser,'estimate_submit',{'id':v2})
    test('Iki darbo pradžios papildymas derinamas',lambda:sql('SELECT status FROM orders WHERE id=?',(oid,)),[('Derinamas',)],'FR-17')
    test('Derinant papildymą ankstesnį patvirtintą darbą pradėti galima',lambda:mechanic.request('task_status',{'id':t1,'status':'Vykdomas'})[0],200,'FR-21')
    test('Patvirtinus v2 sukuriama tik nauja užduotis',lambda:client.request('estimate_decide',{'id':v2,'status':'Patvirtinta'})[0],200,'FR-19')
    test('Unikali patvirtinta apimtis yra 15000, ne 25000',lambda:next(o['confirmed_total_cents'] for o in client.request('state')[1]['orders'] if o['id']==oid),15000,'FR-24')
    test('Pirminei eilutei neatsirado antro darbo',lambda:len(sql('SELECT id FROM tasks WHERE line_id=?',(first_line,))),1,'FR-19')
    t2=sql('SELECT id FROM tasks WHERE line_id=?',(new_line,))[0][0]
    test('Naujas darbas yra Suplanuotas',lambda:sql('SELECT status FROM tasks WHERE id=?',(t2,)),[('Suplanuotas',)],'FR-19')
    copied=sql('SELECT id FROM estimate_lines WHERE estimate_id=? AND origin_line_id=?',(v2,first_line))[0][0]
    test('DB neleidžia kurti darbo iš eilutės kopijos',lambda:rejected('INSERT INTO tasks(line_id) VALUES(?)',(copied,)),True,'FR-19')
    extra={'task_id':t1,'result':'Rastas papildomas gedimas','proposed_works':'Dar vienas remontas'}
    test('Savo darbo metu registruojamas papildomas gedimas',lambda:mechanic.request('diagnostic_add',extra)[0],200,'FR-23')
    test('Kito darbo vykdytojas papildomo gedimo neįrašo',lambda:other_mechanic.request('diagnostic_add',extra)[0],403,'FR-23')
    test('Papildomo gedimo pasiūlymas naujos užduoties nesukuria',lambda:len([t for t in state()['tasks'] if t['order_id']==oid]),2,'FR-23')
    v3=ok(adviser,'estimate_save',{'order_id':oid,'lines':[{**addition,'title':'Trečias siūlymas','unit_cents':700}]})
    ok(adviser,'estimate_submit',{'id':v3})
    test('Vykdomo užsakymo papildymas jo nesustabdo',lambda:sql('SELECT status FROM orders WHERE id=?',(oid,)),[('Vykdomas',)],'FR-17')
    test('Klientas atmeta papildymą',lambda:client.request('estimate_decide',{'id':v3,'status':'Atmesta','decision_note':'Papildymo nereikia'})[0],200,'FR-18')
    test('Atmetimas išlaiko 15000 centų apimtį',lambda:next(o['confirmed_total_cents'] for o in state()['orders'] if o['id']==oid),15000,'FR-18')
    test('Atmetimas neatšaukia vykdomos užduoties',lambda:sql('SELECT status FROM tasks WHERE id=?',(t1,)),[('Vykdomas',)],'FR-18')
    test('Atmesta nauja eilutė nesukūrė darbo',lambda:len([t for t in state()['tasks'] if t['order_id']==oid]),2,'FR-18')
    test('Visų versijų sprendimai lieka istorijoje',lambda:len([e for e in client.request('state')[1]['estimates'] if e['order_id']==oid]),3,'NF-16')
    # Integer arithmetic: 1.5 * 101 ct = 152 ct, and 0.001 * 500 ct = 1 ct.
    v4=ok(adviser,'estimate_save',{'order_id':oid,'lines':[{'kind':'Detalė','title':'Dalinė medžiaga','quantity_1000':1500,'unit_cents':101},{'kind':'Detalė','title':'Pusės cento riba','quantity_1000':1,'unit_cents':500}]})
    test('Daliniai kiekiai apvalinami deterministiškai centais',lambda:sql('SELECT line_total_cents FROM estimate_lines WHERE estimate_id=? AND origin_line_id IS NULL ORDER BY id',(v4,)),[(152,),(1,)],'NF-06')
    test('Visos pinigų ir kiekių reikšmės saugomos kaip integer',lambda:sql("SELECT DISTINCT typeof(quantity_1000),typeof(unit_cents),typeof(line_total_cents) FROM estimate_lines WHERE estimate_id=?",(v4,)),[('integer','integer','integer')],'NF-06')
    test('Float pinigų įvestis atmetama',lambda:adviser.request('estimate_save',{'order_id':oid,'id':v4,'lines':[{**addition,'unit_cents':1.1}]})[0],400,'NF-06')
    test('Pasikartojanti origin įvestis atmetama',lambda:adviser.request('estimate_save',{'order_id':oid,'id':v4,'lines':[{'origin_line_id':first_line},{'origin_line_id':first_line},addition]})[0],409,'FR-17')
    test('Svetimo užsakymo origin atmetamas',lambda:adviser.request('estimate_save',{'order_id':oid,'id':v4,'lines':[{'origin_line_id':1},addition]})[0],409,'FR-17')
    ok(adviser,'task_assign',{'id':t2,'mechanic_id':3})
    test('Kitas mechanikas nepradeda svetimos naujos užduoties',lambda:other_mechanic.request('task_status',{'id':t2,'status':'Vykdomas'})[0],403,'FR-21')
    ok(mechanic,'task_status',{'id':t2,'status':'Vykdomas'})
    ok(mechanic,'task_status',{'id':t1,'status':'Baigtas','minutes':30,'note':'Baigta'})
    test('Nulinė faktinė trukmė leidžiama pagal neneigiamumo taisyklę',lambda:mechanic.request('task_status',{'id':t2,'status':'Baigtas','minutes':0,'note':'Baigta'})[0],200,'FR-22')
    test('Darbo paskyrimo, pradžios ir baigimo laikai išsaugoti',lambda:all(all(x) for x in sql('SELECT assigned_at,started_at,finished_at FROM tasks WHERE id IN (?,?)',(t1,t2))),True,'FR-22')
    test('Rengiama versija blokuoja paruošimą',lambda:adviser.request('order_ready',{'id':oid})[0],409,'FR-13')
    ok(adviser,'estimate_submit',{'id':v4})
    test('Pateikta versija blokuoja paruošimą',lambda:adviser.request('order_ready',{'id':oid})[0],409,'FR-13')
    ok(client,'estimate_decide',{'id':v4,'status':'Atmesta'})
    ok(adviser,'order_ready',{'id':oid})
    test('Paruoštame automobilyje naujas gedimas grąžina į vykdymą',lambda:(mechanic.request('diagnostic_add',extra)[0],sql('SELECT status FROM orders WHERE id=?',(oid,))[0][0]),(200,'Vykdomas'),'FR-23')
    v5=ok(adviser,'estimate_save',{'order_id':oid,'lines':[{**addition,'title':'Paskutinis siūlymas','unit_cents':1}]})
    ok(adviser,'estimate_submit',{'id':v5});ok(client,'estimate_decide',{'id':v5,'status':'Atmesta'})
    ok(adviser,'order_ready',{'id':oid});settle_and_handover(adviser,oid,'regression-close-02')
    ok(adviser,'order_close',{'id':oid,'note':'Apmokėta, automobilis perduotas'})
    test('Uždarytam užsakymui sąmatos papildymas draudžiamas',lambda:adviser.request('estimate_save',payload)[0],409,'FR-17')
    test('Uždarytam užsakymui papildomas gedimas neregistruojamas',lambda:mechanic.request('diagnostic_add',extra)[0],409,'FR-23')
    test('Uždarytam užsakymui diagnostika nepaskiriama',lambda:adviser.request('diagnostic_assign',{'order_id':oid,'mechanic_id':3})[0],409,'FR-10A')
    test('Mechanikui neperduodamos kainų ir sprendimų lentelės',lambda:any(k in mechanic.request('state')[1] for k in ('estimates','lines','decisions','clients')),False,'NF-12')
    # A separate order: the complete initial proposal is rejected, without any billable work.
    visit2=ok(client,'appointment_save',{'car_id':car,'start_at':'2026-12-02T09:00','end_at':'2026-12-02T10:00','bay':1,'problem':'Kitas gedimas'})
    ok(adviser,'appointment_status',{'id':visit2,'status':'Atvyko','mileage':140001})
    oid2=next(o['id'] for o in state()['orders'] if o['appointment_id']==visit2)
    assignment=ok(adviser,'diagnostic_assign',{'order_id':oid2,'mechanic_id':3})
    ok(mechanic,'diagnostic_add',{'assignment_id':assignment,'result':'Siūlomas remontas','proposed_works':'Remontuoti'})
    version=ok(adviser,'estimate_save',{'order_id':oid2,'lines':[line]});ok(adviser,'estimate_submit',{'id':version})
    test('Klientas atmeta visą pradinę sąmatą',lambda:client.request('estimate_decide',{'id':version,'status':'Atmesta'})[0],200,'FR-16')
    test('Atmetus pradinę sąmatą užduočių nėra',lambda:len([t for t in state()['tasks'] if t['order_id']==oid2]),0,'FR-19')
    test('Visą remontą atmetus automobilis gali būti paruoštas',lambda:adviser.request('order_ready',{'id':oid2})[0],200,'FR-13')
    # Explicit v1=10000 / v2=15000 rejected case from the approved design.
    visit3=ok(client,'appointment_save',{'car_id':car,'start_at':'2026-12-03T09:00','end_at':'2026-12-03T10:00','bay':1,'problem':'Pakartotinė patikra'})
    ok(adviser,'appointment_status',{'id':visit3,'status':'Atvyko','mileage':140002})
    oid3=next(o['id'] for o in state()['orders'] if o['appointment_id']==visit3)
    assignment=ok(adviser,'diagnostic_assign',{'order_id':oid3,'mechanic_id':3})
    ok(mechanic,'diagnostic_add',{'assignment_id':assignment,'result':'Gedimas','proposed_works':'Pagrindinis remontas'})
    version1=ok(adviser,'estimate_save',{'order_id':oid3,'lines':[line]})
    ok(adviser,'estimate_submit',{'id':version1});ok(client,'estimate_decide',{'id':version1,'status':'Patvirtinta'})
    task=next(t['id'] for t in state()['tasks'] if t['order_id']==oid3)
    ok(adviser,'task_assign',{'id':task,'mechanic_id':3});ok(mechanic,'task_status',{'id':task,'status':'Vykdomas'})
    ok(mechanic,'diagnostic_add',{'task_id':task,'result':'Papildomas gedimas','proposed_works':'Papildomas remontas'})
    version2=ok(adviser,'estimate_save',{'order_id':oid3,'lines':[addition]})
    ok(adviser,'estimate_submit',{'id':version2});ok(client,'estimate_decide',{'id':version2,'status':'Atmesta'})
    test('Atmetus v2=15000, v1=10000 lieka patvirtinta',lambda:(sql('SELECT status FROM estimates WHERE id=?',(version1,))[0][0],next(o['confirmed_total_cents'] for o in state()['orders'] if o['id']==oid3)),('Patvirtinta',10000),'FR-18')
    test('V1 užduotis išlieka vykdoma atmetus v2',lambda:sql('SELECT status FROM tasks WHERE id=?',(task,)),[('Vykdomas',)],'FR-18')
    test('V2 atmetimas naujų užduočių nesukuria',lambda:len([t for t in state()['tasks'] if t['order_id']==oid3]),1,'FR-18')
    test('Ankstesnis darbas sėkmingai baigiamas atmetus papildymą',lambda:mechanic.request('task_status',{'id':task,'status':'Baigtas','minutes':40,'note':'Atlikta sutarta apimtis'})[0],200,'FR-22')

def stage2_migration(folder):
    old=main.DB; legacy=folder/'stage1_source.db';blocked=folder/'stage1_approved.db'
    schema=(main.ROOT/'testdata'/'schema_stage1.sql').read_text(encoding='utf-8')
    with sqlite3.connect(legacy) as c:
        c.executescript(schema)
        c.execute("INSERT INTO users(id,username,name,role,password_hash) VALUES(7,'old','Darbuotojas','vadybininkas','original-hash')")
        c.execute("INSERT INTO clients(id,name,phone) VALUES(9,'Klientas','1234567')")
        c.execute("INSERT INTO cars VALUES(11,9,'OLD02','Toyota','Yaris',2018)")
        c.execute("INSERT INTO appointments VALUES(13,11,'2026-12-01T08:00','2026-12-01T09:00',1,'Gedimas','Atvyko',7)")
        c.execute("INSERT INTO orders(id,appointment_id,mileage,created_at) VALUES(15,13,100,'2026-12-01')")
        c.execute("INSERT INTO estimates(id,order_id,version,total_cents,created_at) VALUES(17,15,1,10000,'2026-12-01')")
        c.execute("INSERT INTO estimate_lines VALUES(19,17,'Darbas','Remontas',1,10000)")
        c.commit()
        with sqlite3.connect(blocked) as target: c.backup(target)
    with sqlite3.connect(blocked) as c:
        c.execute("UPDATE estimates SET status='Patvirtinta',decided_by=7,decision_note='Senas darbuotojo įrašas' WHERE id=17")
    def migrate():
        main.DB=legacy;main.init_db(seed=False)
        with main.connect() as c:
            return (tuple(c.execute('SELECT id,order_id,status,total_cents,created_by FROM estimates').fetchone()),
                    tuple(c.execute('SELECT id,quantity_1000,line_total_cents FROM estimate_lines').fetchone()),
                    c.execute('PRAGMA foreign_key_check').fetchall())
    expected=((17,15,'Rengiama',10000,7),(19,1000,10000),[])
    check(len(RESULTS)+1,'TS-25','NF-05','1 etapo DB juodraštis migruoja neprarasdamas duomenų','Migruoti tikrą ankstesnę schemą.',migrate,expected)
    check(len(RESULTS)+1,'TS-25','NF-05','2 etapo migracija pakartojama saugiai','Pakartotinai inicializuoti DB.',migrate,expected)
    def refuse_fabricated_consent():
        main.DB=blocked;before=blocked.read_bytes()
        try: main.init_db(seed=False)
        except RuntimeError:
            return blocked.read_bytes()==before and blocked.with_name(blocked.name+'.pre_stage2.bak').exists()
        return False
    check(len(RESULTS)+1,'TS-25','NF-16','Senas darbuotojo sprendimas neverčiamas fiktyviu kliento sutikimu','Nesaugią migraciją sustabdyti ir išlaikyti DB kopiją.',refuse_fabricated_consent,True)
    main.DB=old

def stage3_checks(port,adviser,boss,mechanic):
    def test(title,fn,expected,req='FR-24'):
        check(len(RESULTS)+1,'TS-26',req,title,title,fn,expected)
    def ok(browser,action,data):
        status,body=browser.request(action,data)
        assert status==200,(action,body)
        return body['id']
    def sql(query,args=()):
        with main.connect() as c:return [tuple(x) for x in c.execute(query,args)]
    def rejected(query,args=()):
        with main.connect() as c:
            try:c.execute(query,args)
            except sqlite3.IntegrityError:return True
            c.rollback();return False
    def data(oid,amount,key=None):
        return {'order_id':oid,'amount_cents':amount,'request_key':key or secrets.token_hex(16)}
    def summary(oid,browser=None):return (browser or client).request(f'payments?order_id={oid}')[1]
    def totals(oid):
        s=summary(oid)
        return tuple(s[k] for k in ('confirmed_total_cents','paid_cents','balance_cents','reserved_cents','available_cents'))
    def event(pid,status):
        with main.connect() as c:p=main.one(c,'payments',pid)
        return main.payment_provider.result(p,status)
    def signed(payload,**changes):
        payload={k:v for k,v in {**payload,**changes}.items() if k!='signature'}
        return {**payload,'signature':main.payment_provider._signature(payload)}
    def resolve(pid,status):return client.request('payment_mock_result',{'id':pid,'status':status})
    cid=ok(adviser,'client_save',{'name':'Mokėjimų klientas','phone':'+37060000888'})
    ok(boss,'user_save',{'username':'mokejimai','name':'Mokėjimų klientas','role':'klientas','client_id':cid,'password':'Demo2026!!'})
    client=Browser(port);client.login('mokejimai','Demo2026!!')
    foreign=Browser(port);foreign.login('klientas_kitas','Demo2026!!')
    anonymous=Browser(port)
    car=ok(client,'car_save',{'plate':'PAY001','make':'Toyota','model':'Yaris','year':2020})
    day=0
    def order(amount=10000,decision='Patvirtinta',kind='Darbas'):
        nonlocal day
        day+=1
        date=f'2027-03-{day:02d}'
        visit=ok(client,'appointment_save',{'car_id':car,'start_at':date+'T09:00','end_at':date+'T10:00','bay':1,'problem':'Mokėjimų patikra'})
        ok(adviser,'appointment_status',{'id':visit,'status':'Atvyko','mileage':150000})
        oid=next(o['id'] for o in client.request('state')[1]['orders'] if o['appointment_id']==visit)
        assignment=ok(adviser,'diagnostic_assign',{'order_id':oid,'mechanic_id':3})
        ok(mechanic,'diagnostic_add',{'assignment_id':assignment,'result':'Mokomasis gedimas','proposed_works':'Patikrinti ir remontuoti'})
        version=ok(adviser,'estimate_save',{'order_id':oid,'lines':[{'kind':kind,'title':'Pagrindinis remontas','quantity_1000':1000,'unit_cents':amount}]})
        ok(adviser,'estimate_submit',{'id':version});ok(client,'estimate_decide',{'id':version,'status':decision})
        return oid,version
    def tasks(oid):return [t for t in boss.request('state')[1]['tasks'] if t['order_id']==oid]
    def finish(oid):
        for t in tasks(oid):
            if t['status']=='Suplanuotas':
                ok(adviser,'task_assign',{'id':t['id'],'mechanic_id':3});ok(mechanic,'task_status',{'id':t['id'],'status':'Vykdomas'})
            if t['status']!='Baigtas':ok(mechanic,'task_status',{'id':t['id'],'status':'Baigtas','minutes':20,'note':'Atlikta'})
    oid,v1=order()
    task=tasks(oid)[0]['id'];ok(adviser,'task_assign',{'id':task,'mechanic_id':3})
    test('Remontas prasideda be jokio mokėjimo',lambda:mechanic.request('task_status',{'id':task,'status':'Vykdomas'})[0],200,'FR-21')
    v2=ok(adviser,'estimate_save',{'order_id':oid,'lines':[{'kind':'Darbas','title':'Papildomas remontas','quantity_1000':1000,'unit_cents':5000}]})
    ok(adviser,'estimate_submit',{'id':v2});ok(client,'estimate_decide',{'id':v2,'status':'Patvirtinta'})
    test('Mokėjimams v1 ir v2 origin apimtis 15000, ne 25000',lambda:totals(oid),(15000,0,15000,0,15000))
    test('Svetimo užsakymo finansai pagal ID neprieinami',lambda:foreign.request(f'payments?order_id={oid}')[0],404,'NF-11')
    test('Svetimo užsakymo mokėjimas nepradedamas',lambda:foreign.request('payment_start',data(oid,100))[0],404,'NF-11')
    test('Mechanikas negauna finansų per endpointą',lambda:mechanic.request(f'payments?order_id={oid}')[0],403,'NF-12')
    test('Mechaniko snapshot neturi mokėjimų',lambda:'payments' in mechanic.request('state')[1],False,'NF-12')
    test('Klientas neregistruoja vietinio atsiskaitymo',lambda:client.request('payment_local',data(oid,100))[0],403,'NF-10')
    test('Vadybininkas negali veikti kaip internetu mokantis klientas',lambda:adviser.request('payment_start',data(oid,100))[0],403,'NF-10')
    for action in ('payment_start','payment_local','payment_mock_result'):
        test('Mechanikui uždrausta '+action,lambda action=action:mechanic.request(action,{'id':1,**data(oid,100),'status':'Sėkmingas'})[0],403,'NF-12')
    test('Anonimas finansų neskaito',lambda:anonymous.request(f'payments?order_id={oid}')[0],401,'NF-10')
    test('Mokėjimo inicijavimas be CSRF atmetamas',lambda:client.request('payment_start',data(oid,100),csrf=False)[0],403,'NF-13')
    for amount in (0,-1,1.5,1.0,True,'1.00'):
        test('Neleistina centų įvestis '+repr(amount),lambda amount=amount:client.request('payment_start',data(oid,amount))[0],400,'NF-06')
    test('Mokėjimas virš realaus likučio atmetamas',lambda:client.request('payment_start',data(oid,15001))[0],409)
    test('Per trumpas request_key atmetamas',lambda:client.request('payment_start',data(oid,100,'x'))[0],400)
    request=data(oid,8000);pid=ok(client,'payment_start',request)
    test('Avansas laukia ir rezervuoja 8000 ct',lambda:totals(oid),(15000,0,15000,8000,7000))
    test('Tas pats request_key grąžina tą patį mokėjimą',lambda:client.request('payment_start',request)[1]['id'],pid)
    test('Pakartota inicijavimo užklausa nurodo pakartojimą',lambda:client.request('payment_start',request)[1]['duplicate'],True)
    test('Pakartojimas nekuria antros rezervacijos',lambda:totals(oid),(15000,0,15000,8000,7000))
    test('Tas pats raktas su kita suma atmetamas',lambda:client.request('payment_start',{**request,'amount_cents':8001})[0],409)
    test('Antras avansas neviršija laisvo likučio',lambda:client.request('payment_start',data(oid,8000))[0],409)
    test('Vietinis mokėjimas taip pat įvertina rezervą',lambda:adviser.request('payment_local',data(oid,7001))[0],409)
    test('Klientas negali imituoti svetimo mokėjimo rezultato',lambda:foreign.request('payment_mock_result',{'id':pid,'status':'Sėkmingas'})[0],404,'NF-11')
    test('Imitacijos rezultatas be CSRF atmetamas',lambda:client.request('payment_mock_result',{'id':pid,'status':'Sėkmingas'},csrf=False)[0],403,'NF-13')
    test('Suklastotas techninis rezultatas nepriimamas',lambda:anonymous.request('payment_result',{**event(pid,'Sėkmingas'),'signature':'forged'})[0],403,'NF-10')
    test('Naršyklės pakeista suma negaliojančiame paraše atmetama',lambda:anonymous.request('payment_result',{**event(pid,'Sėkmingas'),'amount_cents':1})[0],403,'NF-10')
    for changes in ({'order_id':oid+1000},{'amount_cents':8001},{'currency':'USD'},{'status':'Unknown'}):
        test('Pasirašytas, bet neatitinkantis rezultatas '+str(changes),lambda changes=changes:anonymous.request('payment_result',signed(event(pid,'Sėkmingas'),**changes))[0],409,'NF-16')
    test('Nežinoma tiekėjo operacija atmetama',lambda:anonymous.request('payment_result',signed(event(pid,'Sėkmingas'),operation_id='mock_unknown'))[0],404,'NF-16')
    test('Kortelės laukų turintis rezultatas atmetamas, jo turinys nesaugomas',lambda:anonymous.request('payment_result',{**event(pid,'Sėkmingas'),'card_number':'NOT_A_CARD'})[0],403,'NF-15')
    test('Po neteisingų rezultatų balansas ir rezervas nepakeisti',lambda:totals(oid),(15000,0,15000,8000,7000))
    test('Laukimo scenarijus galioja',lambda:resolve(pid,'Laukia')[0],200)
    test('Vėlavimas neatlaisvina rezervacijos',lambda:totals(oid),(15000,0,15000,8000,7000))
    test('Sėkmingas techninis atsakymas priimamas be žmogaus sesijos',lambda:anonymous.request('payment_result',event(pid,'Sėkmingas'))[0],200)
    test('Sėkmė užskaito 8000 ct ir panaikina rezervą',lambda:totals(oid),(15000,8000,7000,0,7000))
    test('Pasikartojantis callback atpažįstamas',lambda:anonymous.request('payment_result',event(pid,'Sėkmingas'))[1]['duplicate'],True)
    test('Operacijos ID nekuria antro sėkmingo mokėjimo',lambda:sql("SELECT COUNT(*) FROM payments WHERE order_id=? AND status='Sėkmingas'",(oid,)),[(1,)])
    test('Pakartotinis callback likučio antrą kartą nemažina',lambda:totals(oid),(15000,8000,7000,0,7000))
    test('Galutiniam atsakymui prieštaraujantis rezultatas atmetamas',lambda:anonymous.request('payment_result',event(pid,'Nesėkmingas'))[0],409)
    test('Prieštaraujantis rezultatas nekeičia apskaitos',lambda:totals(oid),(15000,8000,7000,0,7000))
    test('Prieštaravimas pažymimas techninio veikėjo audite',lambda:bool(sql("SELECT 1 FROM audit WHERE entity='Mokėjimas' AND entity_id=? AND result='Klaida' AND external_actor IS NOT NULL AND action LIKE 'Prieštaraujantis%'",(pid,))),True,'PF-02')
    test('Techniniai laukai ir kortelės duomenys negrąžinami klientui',lambda:set(summary(oid)['payments'][0]),{'id','order_id','amount_cents','status','method','created_at','resolved_at'},'NF-15')
    test('Kito kliento savitarna neturi šio kliento mokėjimų',lambda:any(p['order_id']==oid for p in foreign.request('state')[1]['payments']),False,'NF-11')
    failed=ok(client,'payment_start',data(oid,7000))
    test('Viso leistino likučio mokėjimas rezervuoja visą sumą',lambda:totals(oid),(15000,8000,7000,7000,0))
    test('Visiškai rezervavus neleidžiama dar 1 ct',lambda:client.request('payment_start',data(oid,1))[0],409)
    test('Nesėkmingas mock rezultatas registruojamas',lambda:resolve(failed,'Nesėkmingas')[0],200)
    test('Nesėkmė atlaisvina rezervą ir nekeičia realaus likučio',lambda:totals(oid),(15000,8000,7000,0,7000))
    test('Nesėkmė nepanaikina remonto leidimo',lambda:mechanic.request('task_status',{'id':task,'status':'Sustabdytas','note':'Pertrauka'})[0],200,'FR-21')
    ok(mechanic,'task_status',{'id':task,'status':'Vykdomas'})
    test('Nesėkmė pati neuždaro užsakymo',lambda:sql('SELECT status FROM orders WHERE id=?',(oid,)),[('Vykdomas',)],'FR-13')
    test('Nepavykusio mokėjimo istorija lieka',lambda:sql('SELECT status,resolved_at IS NOT NULL FROM payments WHERE id=?',(failed,)),[('Nesėkmingas',1)])
    test('Pakartota nesėkmė atpažįstama',lambda:resolve(failed,'Nesėkmingas')[1]['duplicate'],True)
    test('Nesėkmė vėliau nepaverčiama sėkme',lambda:resolve(failed,'Sėkmingas')[0],409)
    local_request=data(oid,2000);local=ok(adviser,'payment_local',local_request)
    test('Vadybininko vietinis mokėjimas mažina likutį',lambda:totals(oid),(15000,10000,5000,0,5000))
    test('Vietinio mokėjimo įrašas turi autorių ir neturi tiekėjo ID',lambda:sql('SELECT method,status,operation_id,recorded_by FROM payments WHERE id=?',(local,)),[('Vietoje','Sėkmingas',None,2)])
    test('Vietinis mokėjimas audituotas',lambda:bool(sql("SELECT 1 FROM audit WHERE entity='Mokėjimas' AND entity_id=? AND user_id=2 AND action='Užregistruotas vietinis mokėjimas'",(local,))),True,'PF-02')
    test('Vietinio registravimo pakartojimas nedubliuoja mokėjimo',lambda:adviser.request('payment_local',local_request)[1]['id'],local)
    test('Vietinis viršmokestis draudžiamas',lambda:boss.request('payment_local',data(oid,5001))[0],409)
    test('Vietinio mokėjimo negalima išspręsti kaip internetinio',lambda:resolve(local,'Sėkmingas')[0],409)
    part=ok(client,'payment_start',data(oid,4999));ok(client,'payment_mock_result',{'id':part,'status':'Sėkmingas'})
    finish(oid);ok(adviser,'order_ready',{'id':oid})
    test('Likutis tiksliai 1 ct išsaugomas',lambda:totals(oid),(15000,14999,1,0,1),'NF-06')
    test('Vienas nesumokėtas centas blokuoja perdavimą',lambda:adviser.request('order_handover',{'id':oid})[0],409,'FR-13')
    test('Vienas nesumokėtas centas blokuoja uždarymą',lambda:adviser.request('order_close',{'id':oid,'note':'Baigta'})[1]['error'],'Prieš perduodant automobilį ir uždarant užsakymą reikia padengti visą likutį.','FR-13')
    test('Vadovas registruoja tiksliai 1 ct vietinį mokėjimą',lambda:boss.request('payment_local',data(oid,1))[0],200)
    test('Finansinis likutis tampa tiksliai nulis',lambda:totals(oid),(15000,15000,0,0,0),'NF-06')
    test('Net 1 ct viršmokestis apmokėtam užsakymui atmetamas',lambda:client.request('payment_start',data(oid,1))[0],409)
    test('Be faktinio perdavimo net apmokėto užsakymo uždaryti negalima',lambda:adviser.request('order_close',{'id':oid,'note':'Baigta'})[1]['error'],'Pirmiausia užregistruokite faktinį automobilio perdavimą.','FR-13')
    extra=ok(adviser,'estimate_save',{'order_id':oid,'lines':[{'kind':'Darbas','title':'Atmestas papildomas darbas','quantity_1000':1000,'unit_cents':500}]})
    test('Rengiama papildoma versija blokuoja uždarymą',lambda:adviser.request('order_close',{'id':oid,'note':'Baigta'})[1]['error'],'Reikia išspręsti visas rengiamas arba pateiktas sąmatų versijas.','FR-13')
    ok(adviser,'estimate_submit',{'id':extra})
    test('Pateikta papildoma versija blokuoja uždarymą',lambda:adviser.request('order_close',{'id':oid,'note':'Baigta'})[0],409,'FR-13')
    ok(client,'estimate_decide',{'id':extra,'status':'Atmesta'});ok(adviser,'order_ready',{'id':oid})
    test('Atmestas papildymas nepakeičia jau apmokėtos apimties',lambda:totals(oid),(15000,15000,0,0,0))
    test('Klientas pats perdavimo neregistruoja',lambda:client.request('order_handover',{'id':oid})[0],403,'NF-10')
    test('Mechanikas perdavimo neregistruoja',lambda:mechanic.request('order_handover',{'id':oid})[0],403,'NF-12')
    test('Vadovas užregistruoja tikrą automobilio perdavimą',lambda:boss.request('order_handover',{'id':oid})[0],200,'FR-13')
    test('Perdavimas turi laiką, bet dar neuždaro užsakymo',lambda:sql('SELECT status,handover_at IS NOT NULL,closed_at FROM orders WHERE id=?',(oid,)),[('Paruoštas',1,None)],'FR-13')
    test('Perdavimo autorius atsekamas',lambda:bool(sql("SELECT 1 FROM audit WHERE entity='Užsakymas' AND entity_id=? AND user_id=1 AND action='Automobilis perduotas klientui'",(oid,))),True,'PF-02')
    test('Pakartotinis perdavimas atmetamas',lambda:adviser.request('order_handover',{'id':oid})[0],409,'FR-13')
    test('Po perdavimo nauji darbai nebederinami',lambda:adviser.request('estimate_save',{'order_id':oid,'lines':[{'kind':'Darbas','title':'Pavėluotas','quantity_1000':1000,'unit_cents':1}]})[0],409,'FR-13')
    test('Po perdavimo diagnostika nebepriskiriama',lambda:adviser.request('diagnostic_assign',{'order_id':oid,'mechanic_id':3})[0],409,'FR-13')
    test('Visas sąlygas įvykdęs užsakymas uždaromas',lambda:adviser.request('order_close',{'id':oid,'note':'Apmokėta ir perduota'})[0],200,'FR-13')
    test('Uždarymas išsaugo autorių ir abu laikus',lambda:sql('SELECT status,handover_at IS NOT NULL,closed_at IS NOT NULL,closed_by FROM orders WHERE id=?',(oid,)),[('Uždarytas',1,1,2)],'FR-13')
    for action in ('order_close','order_ready','order_handover','order_cancel'):
        test('Uždaryto užsakymo nekeičia '+action,lambda action=action:adviser.request(action,{'id':oid,'note':'Pakartota'})[0],409,'FR-13')
    test('Pakartotas mokėjimo raktas po uždarymo vis dar grąžina ankstesnį rezultatą',lambda:client.request('payment_start',request)[1]['id'],pid)
    test('DB saugo centus sveikuoju tipu',lambda:sql('SELECT DISTINCT typeof(amount_cents) FROM payments'),[('integer',)],'NF-06')
    for title,query,args in (
        ('Unikalus operacijos ID',"INSERT INTO payments(order_id,operation_id,request_key,amount_cents,status,method,created_at) SELECT order_id,operation_id,'another-unique-key',amount_cents,'Laukia',method,created_at FROM payments WHERE id=?",(pid,)),
        ('Unikalus užklausos raktas',"INSERT INTO payments(order_id,operation_id,request_key,amount_cents,status,method,created_at) SELECT order_id,'mock_another',request_key,amount_cents,'Laukia',method,created_at FROM payments WHERE id=?",(pid,)),
        ('Mokėjimo suma nekintama','UPDATE payments SET amount_cents=amount_cents+1 WHERE id=?',(pid,)),
        ('Galutinė mokėjimo būsena nekintama',"UPDATE payments SET status='Nesėkmingas' WHERE id=?",(pid,)),
        ('Mokėjimo istorija netrinama','DELETE FROM payments WHERE id=?',(pid,)),
        ('Žurnalas nekintamas',"UPDATE audit SET action='Pakeista' WHERE entity='Mokėjimas'",()),
        ('Žurnalas netrinamas',"DELETE FROM audit WHERE entity='Mokėjimas'",())):
        test(title,lambda query=query,args=args:rejected(query,args),True,'NF-16')
    # A separately paid order with unfinished work tests the work-completion gate itself.
    unfinished,_=order(100)
    ok(adviser,'payment_local',data(unfinished,100))
    test('Apmokėtas, bet nebaigtas darbas blokuoja uždarymą',lambda:adviser.request('order_close',{'id':unfinished,'note':'Per anksti'})[1]['error'],'Reikia užbaigti visus patvirtintos apimties darbus.','FR-13')
    test('Apmokėtas, bet nebaigtas darbas blokuoja perdavimą',lambda:adviser.request('order_handover',{'id':unfinished})[0],409,'FR-13')
    # Zero-charge return after rejection of the entire initial scope.
    rejected_order,_=order(decision='Atmesta')
    test('Visą sąmatą atmetus užduotys nesukuriamos',lambda:tasks(rejected_order),[],'FR-19')
    test('Visą sąmatą atmetus mokėtina suma nulinė',lambda:totals(rejected_order),(0,0,0,0,0))
    test('Nepriimtai sąmatai mokėjimas neleidžiamas',lambda:client.request('payment_start',data(rejected_order,1))[0],409)
    test('Neremontuotas automobilis paruošiamas grąžinti',lambda:adviser.request('order_ready',{'id':rejected_order})[0],200,'FR-13')
    test('Neremontuotas automobilis perduodamas be fiktyvaus mokėjimo',lambda:adviser.request('order_handover',{'id':rejected_order})[0],200,'FR-13')
    test('Atmestos sąmatos užsakymas uždaromas pagal tą patį grąžinimo procesą',lambda:adviser.request('order_close',{'id':rejected_order,'note':'Klientas atsisakė remonto, automobilis grąžintas'})[0],200,'FR-13')
    # Reservations under concurrent HTTP requests (each handler uses BEGIN IMMEDIATE).
    race,_=order()
    barrier=threading.Barrier(2)
    def simultaneous(browser,action,payload):
        barrier.wait(timeout=5)
        return browser.request(action,payload)[0]
    def race_requests(jobs):
        nonlocal barrier
        barrier=threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(simultaneous,*job) for job in jobs]
            return sorted(f.result() for f in futures)
    test('Dvi lygiagrečios 8000 ct užklausos į 10000 ct likutį neviršija limito',lambda:race_requests([(client,'payment_start',data(race,8000)),(client,'payment_start',data(race,8000))]),[200,409],'NF-16')
    test('Po lenktynės rezervuota tik 8000 ct',lambda:totals(race),(10000,0,10000,8000,2000))
    pending=summary(race)['payments'][0]['id'];resolve(pending,'Nesėkmingas')
    shared=data(race,1000)
    test('Lygiagretus identiškas request_key aptarnaujamas idempotentiškai',lambda:race_requests([(client,'payment_start',shared),(client,'payment_start',shared)]),[200,200],'NF-16')
    same_id=sql('SELECT id FROM payments WHERE request_key=?',(shared['request_key'],))[0][0]
    test('Lygiagretiems pakartojimams sukuriamas vienas įrašas',lambda:sql('SELECT COUNT(*) FROM payments WHERE request_key=?',(shared['request_key'],)),[(1,)],'NF-16')
    callback=event(same_id,'Sėkmingas')
    test('Du vienalaikiai callback apdorojami saugiai',lambda:race_requests([(anonymous,'payment_result',callback),(anonymous,'payment_result',callback)]),[200,200],'NF-16')
    test('Du callback užskaito tik vieną 1000 ct mokėjimą',lambda:totals(race),(10000,1000,9000,0,9000))
    test('Vietinis ir internetinis mokėjimai lenktynėje neviršija likučio',lambda:race_requests([(client,'payment_start',data(race,8000)),(adviser,'payment_local',data(race,8000))]),[200,409],'NF-16')
    test('Sėkmingų ir laukiančių suma neviršija patvirtintos apimties',lambda:all((lambda s:s['paid_cents']+s['reserved_cents']<=s['confirmed_total_cents'])(summary(o['id'])) for o in client.request('state')[1]['orders']),True,'NF-16')
    test('DB FK patikra po mokėjimų scenarijų',lambda:sql('PRAGMA foreign_key_check'),[],'NF-16')

def stage3_migration(folder):
    old=main.DB;main.DB=folder/'stage2_source.db'
    with main.connect() as c:
        c.executescript((main.ROOT/'testdata/schema_stage2.sql').read_text(encoding='utf-8'))
        c.execute("INSERT INTO users(id,username,name,role,password_hash) VALUES(7,'old','Vadybininkas','vadybininkas','hash')")
        c.execute("INSERT INTO clients(id,name,phone) VALUES(9,'Klientas','1234567')")
        c.execute("INSERT INTO users(id,username,name,role,password_hash,client_id) VALUES(8,'customer','Klientas','klientas','hash',9)")
        c.execute("INSERT INTO cars VALUES(11,9,'OLD03','Toyota','Yaris',2018)")
        c.execute("INSERT INTO appointments VALUES(13,11,'2026-12-01T08:00','2026-12-01T09:00',1,'Gedimas','Atvyko',7)")
        c.execute("INSERT INTO orders(id,appointment_id,mileage,created_at) VALUES(15,13,100,'2026-12-01')")
        c.execute("INSERT INTO estimates(id,order_id,version,total_cents,created_by,created_at) VALUES(17,15,1,10000,7,'2026-12-01')")
        c.execute("INSERT INTO estimate_lines VALUES(19,17,'Darbas','Remontas',NULL,1000,10000,10000)")
        c.execute("UPDATE estimates SET status='Pateikta',submitted_at='2026-12-01' WHERE id=17")
        c.execute("INSERT INTO estimate_decisions(estimate_id,client_id,user_id,decision,decided_at) VALUES(17,9,8,'Patvirtinta','2026-12-01')")
        c.execute('INSERT INTO tasks(id,line_id) VALUES(21,19)')
        c.execute("INSERT INTO audit VALUES(23,7,'Užsakymas',15,'Sukurtas','2026-12-01')")
        tables=['users','clients','cars','appointments','orders','estimates','estimate_lines','estimate_decisions','tasks','audit']
        before={table:([r['name'] for r in c.execute(f'PRAGMA table_info({table})')],[tuple(r) for r in c.execute(f'SELECT * FROM {table}')]) for table in tables}
    def unchanged():
        main.init_db(seed=False)
        with main.connect() as c:
            return all([tuple(r) for r in c.execute(f"SELECT {','.join(columns)} FROM {table}")]==values for table,(columns,values) in before.items())
    check(len(RESULTS)+1,'TS-27','NF-05','3 etapo migracija išlaiko 2 etapo paskyras, sprendimus, darbus ir auditą','Atnaujinti tikrą 2 etapo schemą.',unchanged,True)
    check(len(RESULTS)+1,'TS-27','NF-05','3 etapo migracija saugiai kartojama','Antrą kartą atverti DB.',unchanged,True)
    check(len(RESULTS)+1,'TS-27','NF-05','Prieš migraciją išsaugoma 2 etapo DB kopija','Patikrinti kopiją.',lambda:main.DB.with_name(main.DB.name+'.pre_stage3.bak').exists(),True)
    with main.connect() as c:
        check(len(RESULTS)+1,'TS-27','NF-16','Migracija nekuria išgalvotų mokėjimų ar perdavimo įrodymų','Tik nauja schema.',lambda:(c.execute('SELECT COUNT(*) FROM payments').fetchone()[0],tuple(c.execute('SELECT handover_at,closed_by FROM orders').fetchone()),c.execute('PRAGMA foreign_key_check').fetchall()),(0,(None,None),[]))
    main.DB=old

def stage4_checks(port,adviser,boss,mechanic):
    def test(title,fn,expected,req='FR-30'):
        check(len(RESULTS)+1,'TS-28',req,title,title,fn,expected)
    def ok(browser,action,data):
        status,body=browser.request(action,data);assert status==200,(action,body)
        return body.get('id')
    def sql(query,args=()):
        with main.connect() as c:return [tuple(x) for x in c.execute(query,args)]
    def rejected(query,args=()):
        with main.connect() as c:
            try:c.execute(query,args)
            except sqlite3.IntegrityError:return True
            c.rollback();return False
    def notes(event):return sql('SELECT id,channel,status FROM notifications WHERE event_key=? ORDER BY id',(event,))
    def attempts(nid):return sql('SELECT attempt_no,result,error_code FROM notification_attempts WHERE notification_id=? ORDER BY attempt_no',(nid,))
    def pay(amount):return {'order_id':oid,'amount_cents':amount,'request_key':secrets.token_hex(16)}
    old_now=main.now
    main.now=lambda:'2027-04-01T00:00:00'
    try:
        cid=ok(adviser,'client_save',{'name':'Pranešimų klientas','phone':'+37060000777','email':'pranesimai@example.com'})
        uid=ok(boss,'user_save',{'username':'pranesimai','name':'Pranešimų klientas','role':'klientas','client_id':cid,'password':'Demo2026!!'})
        client=Browser(port);client.login('pranesimai','Demo2026!!')
        car=ok(client,'car_save',{'plate':'MSG001','make':'Toyota','model':'Yaris','year':2020})
        payload={'car_id':car,'start_at':'2027-05-01T09:00','end_at':'2027-05-01T10:00','bay':1,'problem':'Pranešimų scenarijus'}
        visit=ok(client,'appointment_save',payload);event=f'appointment:{visit}'
        test('Patvirtintas vizitas kuria po vieną SMS ir el. pašto pranešimą',lambda:[x[1] for x in notes(event)],['SMS','El. paštas'])
        test('Sėkmingo siuntimo būsena reiškia tik perdavimą tiekėjui',lambda:[x[2] for x in notes(event)],['Perduotas tiekėjui']*2,'NF-19')
        test('Pakartota konfliktuojanti registracija atmetama',lambda:client.request('appointment_save',payload)[0],409)
        test('Neįvykęs vizitas nesukuria papildomų pranešimų',lambda:len(notes(event)),2)
        # A DB failure while enqueuing must roll back the business write too.
        with main.connect() as c:c.execute("CREATE TRIGGER stage4_queue_failure BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT,'Testo DB klaida'); END")
        test('Pranešimo registravimo DB klaida neatlieka pusės vizito transakcijos',lambda:client.request('appointment_save',{**payload,'start_at':'2027-05-02T09:00','end_at':'2027-05-02T10:00'})[0],409,'NF-05')
        with main.connect() as c:c.execute('DROP TRIGGER stage4_queue_failure')
        test('Po atšauktos transakcijos naujo vizito nėra',lambda:sql("SELECT COUNT(*) FROM appointments WHERE car_id=? AND start_at='2027-05-02T09:00'",(car,)),[(0,)],'NF-05')
        ok(adviser,'appointment_status',{'id':visit,'status':'Atvyko','mileage':190000})
        oid=sql('SELECT id FROM orders WHERE appointment_id=?',(visit,))[0][0]
        test('Užsakymas užfiksuoja klientą, automobilį ir problemą priimant',lambda:sql('SELECT client_id,car_id,problem FROM orders WHERE id=?',(oid,)),[(cid,car,payload['problem'])],'NF-11')
        assignment=ok(adviser,'diagnostic_assign',{'order_id':oid,'mechanic_id':3})
        ok(mechanic,'diagnostic_add',{'assignment_id':assignment,'result':'Reikalingas remontas','proposed_works':'Pradinis darbas'})
        line={'kind':'Darbas','title':'Pranešimų scenarijaus darbas','quantity_1000':1000,'unit_cents':10000}
        v1=ok(adviser,'estimate_save',{'order_id':oid,'lines':[line]})
        test('Rengiama sąmata nekuria pateikimo pranešimo',lambda:notes(f'estimate:{v1}'),[])
        ok(boss,'notification_mode',{'mode':'failure'})
        original_send=main.notification_provider.send;observed=[]
        def probe(**kwargs):
            observed.append(sql('SELECT status FROM estimates WHERE id=?',(v1,))==[('Pateikta',)])
            return original_send(**kwargs)
        main.notification_provider.send=probe
        try:ok(adviser,'estimate_submit',{'id':v1})
        finally:main.notification_provider.send=original_send
        test('Adapteris kviečiamas tik po matomo verslo COMMIT',lambda:observed,[True,True],'NF-05')
        test('Pradinės sąmatos pranešimo tipas teisingas',lambda:sql('SELECT DISTINCT type FROM notifications WHERE estimate_id=?',(v1,)),[('Pradinė sąmata',)])
        test('Tiekėjo gedimas nepanaikina sąmatos pateikimo',lambda:sql('SELECT status FROM estimates WHERE id=?',(v1,)),[('Pateikta',)],'NF-18')
        nid,email_nid=[x[0] for x in notes(f'estimate:{v1}')]
        test('Nepavykęs bandymas išsaugotas prie to paties pranešimo',lambda:attempts(nid),[(1,'Siuntimo klaida','MOCK_UNAVAILABLE')],'FR-31')
        test('Pranešimas lieka Siuntimo klaida',lambda:sql('SELECT status FROM notifications WHERE id=?',(nid,)),[('Siuntimo klaida',)],'FR-31')
        for browser,label in ((client,'Klientas'),(mechanic,'Mechanikas')):
            test(label+' nemato pranešimų techninės sąsajos',lambda browser=browser:browser.request('notifications')[0],403,'NF-10')
            test(label+' negali kartoti pranešimo',lambda browser=browser:browser.request('notification_retry',{'id':nid,'attempt_no':1})[0],403,'NF-10')
            test(label+' nekonfigūruoja tiekėjo imitacijos',lambda browser=browser:browser.request('notification_mode',{'mode':'success'})[0],403,'NF-10')
        test('Klientas negauna pranešimų ar audito per snapshot',lambda:any(k in client.request('state')[1] for k in ('notifications','attempts','audit')),False,'NF-11')
        test('Svetimo pranešimo ID nesuteikia klientui skaitymo teisės',lambda:client.request(f'notifications?id={nid+1000}')[0],403,'NF-11')
        test('Vadybininkas mato pranešimus',lambda:adviser.request('notifications')[0],200,'FR-32')
        test('Vadybininkas negauna vidinių bandymų ar raktų',lambda:('attempts' in adviser.request('notifications')[1] or any('event_key' in n for n in adviser.request('notifications')[1]['notifications'])),False,'NF-12')
        test('Tik vadovas keičia tiekėjo imitacijos režimą',lambda:adviser.request('notification_mode',{'mode':'success'})[0],403,'NF-10')
        test('Retry be CSRF neleidžiamas',lambda:adviser.request('notification_retry',{'id':nid,'attempt_no':1},csrf=False)[0],403,'NF-13')
        test('Vadybininkas pakartoja nepavykusį siuntimą',lambda:adviser.request('notification_retry',{'id':nid,'attempt_no':1})[0],200,'FR-32')
        test('Retry prideda bandymą, nekeičia notification skaičiaus',lambda:(len(notes(f'estimate:{v1}')),len(attempts(nid))),(2,2),'FR-32')
        test('Pakartota ta pati retry užklausa nedubliuoja bandymo',lambda:adviser.request('notification_retry',{'id':nid,'attempt_no':1})[0],409,'FR-32')
        ok(boss,'notification_mode',{'mode':'success'})
        test('Pakartotinis siuntimas gali pavykti',lambda:adviser.request('notification_retry',{'id':nid,'attempt_no':2})[0],200,'FR-32')
        test('Bandymų istorijoje lieka du gedimai ir sėkmė',lambda:[x[1] for x in attempts(nid)],['Siuntimo klaida','Siuntimo klaida','Perduotas tiekėjui'],'FR-32')
        test('Sėkmingas pranešimas pakartotinai nesiunčiamas',lambda:adviser.request('notification_retry',{'id':nid,'attempt_no':3})[0],409,'FR-32')
        ok(boss,'notification_retry',{'id':email_nid,'attempt_no':1})
        test('Retry nepakeičia pateiktos sąmatos verslo būsenos',lambda:sql('SELECT status FROM estimates WHERE id=?',(v1,)),[('Pateikta',)],'FR-32')
        test('Pakartotas sąmatos pateikimas nekuria naujo pranešimo',lambda:(adviser.request('estimate_submit',{'id':v1})[0],len(notes(f'estimate:{v1}'))),(409,2))
        test('DB neleidžia dublikuoti event_key ir channel',lambda:rejected('''INSERT INTO notifications(client_id,estimate_id,order_id,event_key,channel,type,recipient,content,created_at)
            SELECT client_id,estimate_id,order_id,event_key,channel,type,recipient,content,created_at FROM notifications WHERE id=?''',(nid,)),True,'NF-05')
        test('Pranešimų būsenos netampa Perskaityta ar Gautas',lambda:sql("SELECT COUNT(*) FROM notifications WHERE status NOT IN ('Sukurtas','Perduotas tiekėjui','Siuntimo klaida')"),[(0,)],'NF-19')
        main.now=lambda:'2027-04-01T23:59:59'
        ok(client,'estimate_decide',{'id':v1,'status':'Patvirtinta'})
        t1=sql('SELECT t.id FROM tasks t JOIN estimate_lines l ON l.id=t.line_id WHERE l.estimate_id=?',(v1,))[0][0]
        ok(adviser,'task_assign',{'id':t1,'mechanic_id':3});ok(mechanic,'task_status',{'id':t1,'status':'Vykdomas'})
        main.now=lambda:'2027-04-02T00:00:00'
        v2=ok(adviser,'estimate_save',{'order_id':oid,'lines':[{**line,'title':'Papildomas pranešimų darbas','unit_cents':5000}]})
        ok(boss,'notification_mode',{'mode':'timeout'});ok(adviser,'estimate_submit',{'id':v2})
        test('Papildomai pateiktai versijai kuriamas atskiras įvykis',lambda:sql('SELECT DISTINCT type FROM notifications WHERE estimate_id=?',(v2,)),[('Papildyta sąmata',)])
        n2=notes(f'estimate:{v2}')[0][0]
        test('Laiko viršijimas įrašomas kaip techninė siuntimo klaida',lambda:attempts(n2),[(1,'Siuntimo klaida','MOCK_TIMEOUT')],'NF-18')
        test('Laiko viršijimas neanuliuoja papildomos sąmatos pateikimo',lambda:sql('SELECT status FROM estimates WHERE id=?',(v2,)),[('Pateikta',)],'NF-18')
        ok(boss,'notification_mode',{'mode':'success'});ok(adviser,'notification_retry',{'id':n2,'attempt_no':1})
        retry_id=notes(f'estimate:{v2}')[1][0]
        ok(boss,'notification_mode',{'mode':'failure'})
        def concurrent_retry():
            gate=threading.Barrier(2)
            def call():
                gate.wait(timeout=5)
                return adviser.request('notification_retry',{'id':retry_id,'attempt_no':1})[0]
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(call) for _ in range(2)]
                return sorted(f.result() for f in futures)
        test('Dvi vienalaikės retry užklausos prideda tik vieną bandymą',concurrent_retry,[200,409],'FR-32')
        test('Po retry lenktynės istorijoje tik du bandymai',lambda:len(attempts(retry_id)),2,'FR-32')
        ok(boss,'notification_mode',{'mode':'success'});ok(boss,'notification_retry',{'id':retry_id,'attempt_no':2})
        # Simulate stopping after business commit and before calling the dispatcher.
        dispatch=main.dispatch_after_commit;main.dispatch_after_commit=lambda:None
        try:
            recovered_visit=ok(client,'appointment_save',{**payload,'start_at':'2027-05-03T09:00','end_at':'2027-05-03T10:00'})
        finally:main.dispatch_after_commit=dispatch
        pending_event=f'appointment:{recovered_visit}'
        test('Po COMMIT dar neišsiųsta užduotis išlieka DB',lambda:[x[2] for x in notes(pending_event)],['Sukurtas']*2,'NF-18')
        test('Nepradėtam siuntimui nėra išgalvotų bandymų',lambda:attempts(notes(pending_event)[0][0]),[],'NF-18')
        main.dispatch_after_commit()
        test('Atnaujintas siuntimo vykdymas aptinka išlikusias užduotis',lambda:[x[2] for x in notes(pending_event)],['Perduotas tiekėjui']*2,'NF-18')
        test('Atkūrimas neprideda antro verslo įvykio',lambda:len(notes(pending_event)),2,'NF-18')
        ok(client,'estimate_decide',{'id':v2,'status':'Patvirtinta'})
        t2=sql('SELECT t.id FROM tasks t JOIN estimate_lines l ON l.id=t.line_id WHERE l.estimate_id=?',(v2,))[0][0]
        ok(adviser,'task_assign',{'id':t2,'mechanic_id':3});ok(mechanic,'task_status',{'id':t2,'status':'Vykdomas'})
        ok(mechanic,'task_status',{'id':t1,'status':'Baigtas','minutes':17,'note':'Baigta'})
        failed=ok(client,'payment_start',pay(3000));ok(client,'payment_mock_result',{'id':failed,'status':'Nesėkmingas'})
        test('Nesėkmingas mokėjimas nekuria sėkmės pranešimo',lambda:notes(f'payment:{failed}'),[])
        pending=ok(client,'payment_start',pay(2000))
        test('Laukiantis mokėjimas nekuria sėkmės pranešimo',lambda:notes(f'payment:{pending}'),[])
        req=pay(1000);paid=ok(adviser,'payment_local',req)
        test('Vietinis sėkmingas mokėjimas sukuria pranešimus',lambda:len(notes(f'payment:{paid}')),2)
        test('Pakartotas vietinis mokėjimas nedubliuoja pranešimų',lambda:(adviser.request('payment_local',req)[0],len(notes(f'payment:{paid}'))),(200,2))
        main.now=lambda:'2027-04-03T12:00:00'
        ok(client,'payment_mock_result',{'id':pending,'status':'Sėkmingas'})
        test('Internetinis sėkmingas mokėjimas sukuria pranešimus',lambda:len(notes(f'payment:{pending}')),2)
        test('Pakartotas callback nedubliuoja pranešimų',lambda:(client.request('payment_mock_result',{'id':pending,'status':'Sėkmingas'})[0],len(notes(f'payment:{pending}'))),(200,2))
        ok(mechanic,'task_status',{'id':t2,'status':'Baigtas','minutes':23,'note':'Baigta'})
        ok(adviser,'order_ready',{'id':oid});ready=f'ready:{oid}:{v2}'
        test('Automobilio paruošimas sukuria pranešimus',lambda:len(notes(ready)),2)
        test('Pakartota paruošimo užklausa nedubliuoja pranešimo',lambda:(adviser.request('order_ready',{'id':oid})[0],len(notes(ready))),(200,2))
        collect=f'collection:{oid}:15000:3000'
        test('Likutis atsiimant blokuoja perdavimą, bet užregistruoja perspėjimą',lambda:(adviser.request('order_handover',{'id':oid})[0],len(notes(collect))),(409,2))
        test('Pakartota to paties likučio patikra nedubliuoja pranešimo',lambda:(adviser.request('order_handover',{'id':oid})[0],len(notes(collect))),(409,2))
        test('Pranešimas apie likutį neapsimeta automobilio perdavimu',lambda:sql('SELECT handover_at,status FROM orders WHERE id=?',(oid,)),[(None,'Paruoštas')],'FR-13')
        ok(adviser,'payment_local',pay(12000));ok(adviser,'order_handover',{'id':oid});ok(adviser,'order_close',{'id':oid,'note':'Atiduota'})
        def report(a,b):return boss.request(f'reports?from={a}&to={b}')[1]
        expected1={'orders':1,'closed_orders':0,'work_minutes':0,'confirmed_cents':10000,'paid_cents':0}
        expected2={'orders':0,'closed_orders':0,'work_minutes':17,'confirmed_cents':5000,'paid_cents':1000}
        expected3={'orders':0,'closed_orders':1,'work_minutes':23,'confirmed_cents':0,'paid_cents':14000}
        test('Suvestinė įskaito pirmos dienos pabaigos patvirtinimą',lambda:report('2027-04-01','2027-04-01')['totals'],expected1,'FR-33')
        test('Suvestinė antrą dieną neskaičiuoja kopijuotų origin ir nesėkmingų mokėjimų',lambda:report('2027-04-02','2027-04-02')['totals'],expected2,'FR-33')
        test('Baigtis ir mokėjimai priskiriami faktinėms įvykio datoms',lambda:report('2027-04-03','2027-04-03')['totals'],expected3,'FR-33')
        test('Suvestinė grupuojama pagal dieną serveryje',lambda:report('2027-04-01','2027-04-03')['daily'],[{'date':d,**v} for d,v in [('2027-04-01',expected1),('2027-04-02',expected2),('2027-04-03',expected3)]],'FR-33')
        test('Bendra vertė 15000 ct, versijų istorija nedvigubina vertės',lambda:report('2027-04-01','2027-04-03')['totals']['confirmed_cents'],15000,'FR-33')
        test('Tuščias laikotarpis grąžina nulius',lambda:report('2027-04-04','2027-04-04')['totals'],dict.fromkeys(expected1,0),'FR-33')
        for query in ('from=2027-04-03&to=2027-04-01','from=2027-13-01&to=2027-04-01','from=bad&to=bad'):
            test('Neteisingas suvestinės laikotarpis atmetamas '+query,lambda query=query:boss.request('reports?'+query)[0],400,'FR-33')
        for browser,label in ((client,'Klientas'),(mechanic,'Mechanikas'),(adviser,'Vadybininkas')):
            test(label+' negauna vadovo suvestinių',lambda browser=browser:browser.request('reports?from=2027-04-01&to=2027-04-03')[0],403,'NF-10')
            test(label+' negauna žurnalo',lambda browser=browser:browser.request('audit?from=2027-04-01&to=2027-04-03')[0],403,'NF-10')
        audit=boss.request('audit?from=2027-04-01&to=2027-04-03&external_only=1&result=Klaida&entity=Prane%C5%A1imas')[1]
        test('Vadovo klaidų filtras pateikia tik pranešimų tiekėjo klaidas',lambda:bool(audit['audit']) and all(a['external_actor']=='Pranešimų paslauga (imitacija)' and a['result']=='Klaida' and a['entity']=='Pranešimas' for a in audit['audit']),True,'PF-06')
        test('Audito puslapiavimas negrąžina viso žurnalo',lambda:len(boss.request('audit?from=2027-04-01&to=2027-04-03&limit=1')[1]['audit']),1,'PF-06')
        test('Vadovas mato bandymų techninius kodus',lambda:any(a['error_code']=='MOCK_TIMEOUT' for a in boss.request('notifications')[1]['attempts']),True,'PF-06')
        for title,q,args in (
            ('Pranešimo turinys nekeičiamas',"UPDATE notifications SET content='Kitas' WHERE id=?",(nid,)),
            ('Pranešimas nenaikinamas','DELETE FROM notifications WHERE id=?',(nid,)),
            ('Bandymas nekintamas',"UPDATE notification_attempts SET error_code='Kitas' WHERE notification_id=?",(nid,)),
            ('Bandymas nenaikinamas','DELETE FROM notification_attempts WHERE notification_id=?',(nid,)),
            ('Užsakymo kliento tapatybė nekintama','UPDATE orders SET client_id=client_id+1 WHERE id=?',(oid,)),
            ('Užsakymo automobilio ryšys saugomas','UPDATE orders SET car_id=car_id+1 WHERE id=?',(oid,))):
            test(title,lambda q=q,args=args:rejected(q,args),True,'NF-16')
        # Failed transaction cannot replace frozen owner with a different car owner.
        test('Pranešimo kontekstas negali priklausyti kitam klientui',lambda:rejected("INSERT INTO notifications(client_id,order_id,event_key,channel,type,recipient,content,created_at) VALUES(1,?,'foreign-client-event','SMS','Testas','1234567','Testas','2027-04-03')",(oid,)),True,'NF-11')
        staffid=ok(boss,'user_save',{'username':'edit_staff','name':'Keičiama paskyra','role':'vadybininkas','password':'Demo2026!!'})
        staff=Browser(port);staff.login('edit_staff','Demo2026!!')
        update={'id':staffid,'username':'edit_staff','name':'Pakeistas vardas','role':'vadovas'}
        for browser,label in ((client,'Klientas'),(mechanic,'Mechanikas'),(adviser,'Vadybininkas')):
            test(label+' negali redaguoti paskyros ar eskaluoti rolės',lambda browser=browser:browser.request('user_update',update)[0],403,'NF-10')
        test('Paskyros redagavimui privalomas CSRF',lambda:boss.request('user_update',update,csrf=False)[0],403,'NF-13')
        test('Vadovas pakeičia darbuotojo duomenis ir rolę',lambda:boss.request('user_update',update)[0],200,'FR-03')
        test('Nauja rolė taikoma jau prisijungusiai paskyrai',lambda:staff.request('reports?from=2027-04-01&to=2027-04-03')[0],200,'NF-10')
        ok(boss,'user_update',{**update,'role':'mechanikas'})
        test('Sumažinus rolę senos sesijos vadovo teisės nebegalioja',lambda:staff.request('reports?from=2027-04-01&to=2027-04-03')[0],403,'NF-10')
        test('Rolės pakeitimas įrašytas žurnale',lambda:bool(sql("SELECT 1 FROM audit WHERE entity='Naudotojas' AND entity_id=? AND action LIKE '%vadovas → mechanikas%'",(staffid,))),True,'PF-02')
        test('Dirbančio mechaniko rolė nepakeičiama',lambda:boss.request('user_update',{'id':3,'name':'Mechanikas A','username':'mechanikas','role':'vadybininkas'})[0],409,'FR-03')
        test('Vadovas negali pats panaikinti savo vadovo rolės',lambda:boss.request('user_update',{'id':1,'name':'Vadovas','username':'vadovas','role':'mechanikas'})[0],409,'FR-03')
        test('Kliento paskyra neperjungiama kitam klientui',lambda:boss.request('user_update',{'id':uid,'name':'Pranešimų klientas','username':'pranesimai','role':'klientas','client_id':1})[0],409,'NF-11')
        ok(boss,'user_disable',{'id':staffid})
        test('Deaktyvavimas blokuoja esamą pakeistos rolės sesiją',lambda:staff.request('state')[0],401,'NF-09')
        test('Deaktyvuota redaguota paskyra nebeprisijungia',lambda:staff.request('login',{'username':'edit_staff','password':'Demo2026!!'})[0],401,'NF-09')
        new_hash=sql('SELECT password_hash FROM users WHERE id=?',(uid,))[0][0]
        test('Nauja maiša saugo algoritmą ir darbo koeficientą',lambda:new_hash.split('$')[:2],['pbkdf2_sha256','260000'],'NF-13')
        test('Vienodas slaptažodis gauna skirtingas druskas',lambda:main.password_hash('Vienodas123!').split('$')[2]!=main.password_hash('Vienodas123!').split('$')[2],True,'NF-13')
        legacy=':'.join(new_hash.split('$')[2:])
        with main.connect() as c:c.execute('UPDATE users SET password_hash=? WHERE id=?',(legacy,uid))
        legacy_browser=Browser(port)
        test('Senas hash formatas tebėra tinkamas prisijungimui',lambda:legacy_browser.request('login',{'username':'pranesimai','password':'Demo2026!!'})[0],200,'NF-13')
        test('Neteisingas slaptažodis su sena maiša atmetamas',lambda:legacy_browser.request('login',{'username':'pranesimai','password':'wrong'})[0],401,'NF-13')
        custom_salt=secrets.token_hex(16)
        digest=main.hashlib.pbkdf2_hmac('sha256',b'Test12345!',bytes.fromhex(custom_salt),120000).hex()
        test('Tikrinamas maišoje nurodytas, ne hardcoded koeficientas',lambda:main.password_ok('Test12345!',f'pbkdf2_sha256$120000${custom_salt}${digest}'),True,'NF-13')
        test('Sugadinta maiša grąžina nesėkmę, ne serverio klaidą',lambda:main.password_ok('abc','invalid'),False,'NF-13')
        ok(boss,'user_update',{'id':uid,'username':'pranesimai','name':'Pranešimų klientas','role':'klientas','password':'Pakeistas2027!'})
        test('Pakeitus slaptažodį senos sesijos panaikinamos',lambda:client.request('state')[0],401,'NF-13')
        test('Senas slaptažodis po pakeitimo netinka',lambda:client.request('login',{'username':'pranesimai','password':'Demo2026!!'})[0],401,'NF-13')
        client.login('pranesimai','Pakeistas2027!')
        sid=client.cookie.split('=',1)[1]
        with main.SESSION_LOCK:main.SESSIONS[sid]['expires']=time.time()+5
        test('Dar nepasibaigusi sesija atnaujinama',lambda:client.request('state')[0],200,'PF-01')
        test('Neveiklumo terminas atnaujinamas 30 minučių',lambda:main.SESSIONS[sid]['expires']-time.time()>1798,True,'PF-01')
        with main.SESSION_LOCK:main.SESSIONS[sid]['expires']=time.time()-1
        test('Pasibaigusi neveiklumo sesija nebetinka',lambda:client.request('state')[0],401,'PF-01')
        client.login('pranesimai','Pakeistas2027!');ok(client,'logout',{})
        test('Atsijungimas panaikina sesiją',lambda:client.request('state')[0],401,'PF-01')
        prior_origin=main.PUBLIC_ORIGIN
        try:
            main.PUBLIC_ORIGIN=''
            test('Vietinio HTTP slapukas neteigia HTTPS',lambda:main.session_cookie('test'),'sid=test; HttpOnly; SameSite=Strict; Path=/','NF-14')
            main.PUBLIC_ORIGIN='https://servisas.example'
            test('HTTPS konfigūracijoje slapukas Secure',lambda:'; Secure' in main.session_cookie('test'),True,'NF-14')
            test('HTTPS atsijungimo slapukas taip pat Secure',lambda:main.session_cookie('',True).endswith('; Secure; Max-Age=0'),True,'NF-14')
        finally:main.PUBLIC_ORIGIN=prior_origin
        test('Slaptažodžiai ir maišos nepatenka į auditą',lambda:any('Pakeistas2027!' in a[0] or 'pbkdf2_sha256$' in a[0] for a in sql('SELECT action FROM audit')),False,'NF-13')
        test('DB realizuoja visas 15 loginių esybių',lambda:{r[0] for r in sql("SELECT name FROM sqlite_master WHERE type='table'")},{'users','clients','cars','appointments','orders','diagnostic_assignments','diagnostic_entries','estimates','estimate_lines','estimate_decisions','tasks','payments','notifications','notification_attempts','audit'},'NF-05')
        test('Galutinė FK patikra po 4 etapo scenarijų',lambda:sql('PRAGMA foreign_key_check'),[],'NF-05')
    finally:
        main.now=old_now;main.notification_provider.configure('success')

def stage4_migration(folder):
    old=main.DB;main.DB=folder/'stage3_source.db'
    encoded=main.password_hash('Senas2026!');legacy=':'.join(encoded.split('$')[2:])
    with main.connect() as c:
        c.executescript((main.ROOT/'testdata/schema_stage3.sql').read_text())
        c.execute("INSERT INTO users(id,username,name,role,password_hash) VALUES(1,'legacy','Senas vadovas','vadovas',?)",(legacy,))
        c.execute("INSERT INTO clients(id,name,phone) VALUES(1,'Senas klientas','1234567')")
        c.execute("INSERT INTO cars VALUES(1,1,'OLDS4','Toyota','Yaris',2018)")
        c.execute("INSERT INTO appointments VALUES(1,1,'2027-01-01T09:00','2027-01-01T10:00',1,'Išsaugota problema','Atvyko',1)")
        c.execute("INSERT INTO orders(id,appointment_id,mileage,created_at) VALUES(1,1,123,'2027-01-01T09:00:00')")
    def test(title,fn,expected):check(len(RESULTS)+1,'TS-29','NF-05',title,title,fn,expected)
    main.init_db(seed=False)
    def state():
        with main.connect() as c:
            h=c.execute('SELECT password_hash FROM users WHERE id=1').fetchone()[0]
            return (tuple(c.execute('SELECT id,client_id,car_id,problem,mileage FROM orders').fetchone()),h,main.password_ok('Senas2026!',h),c.execute('PRAGMA foreign_key_check').fetchall())
    expected=((1,1,1,'Išsaugota problema',123),encoded,True,[])
    test('Migracija išlaiko slaptažodį ir užfiksuoja užsakymo kontekstą',state,expected)
    main.init_db(seed=False)
    test('4 etapo migracija saugiai kartojama',state,expected)
    test('Prieš 4 etapo migraciją išsaugota kopija',lambda:main.DB.with_name(main.DB.name+'.pre_stage4.bak').exists(),True)
    with main.connect() as c:
        test('Migracija nekuria pranešimų už senus įvykius',lambda:c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],0)
    main.DB=old

def stage5a_checks(port,adviser,boss):
    def test(title,fn,expected,req='NF-11'):
        check(len(RESULTS)+1,'TS-30',req,title,title,fn,expected)
    def ok(browser,action,data):
        status,body=browser.request(action,data)
        assert status==200,(action,body)
        return body.get('id')
    def sql(q,args=()):
        with main.connect() as c:return [tuple(r) for r in c.execute(q,args)]
    adviser.login('vadybininkas');boss.login('vadovas')
    mechanic=Browser(port);mechanic.login('mechanikas')
    owners=[];clients=[]
    for i in (1,2):
        cid=ok(adviser,'client_save',{'name':f'5A klientas {i}','phone':f'+3706000500{i}'})
        ok(boss,'user_save',{'username':f'5a_client{i}','name':f'5A klientas {i}','role':'klientas','client_id':cid,'password':'Demo2026!!'})
        client=Browser(port);client.login(f'5a_client{i}','Demo2026!!')
        owners.append(cid);clients.append(client)
    first,second=clients
    car_data={'plate':'QA5A01','make':'Toyota','model':'Yaris','year':2020}
    car=ok(first,'car_save',car_data)
    transfer={**car_data,'id':car,'client_id':owners[1]}
    slot={'car_id':car,'start_at':'2028-01-02T09:00','end_at':'2028-01-02T10:00','bay':1,'problem':'Privati pirmojo kliento problema'}
    visit=ok(first,'appointment_save',slot)
    test('Savininko keitimas blokuojamas esant Patvirtintam vizitui',lambda:adviser.request('car_save',transfer)[0],409,'FR-05')
    test('Klientas negali perduoti automobilio nurodęs svetimą client_id',lambda:(first.request('car_save',transfer)[0],sql('SELECT client_id FROM cars WHERE id=?',(car,))),(200,[(owners[0],)]),'FR-05')
    test('Minutėmis suvienodinami sekundžių intervalai nepriimami',lambda:first.request('appointment_save',{**slot,'start_at':'2028-01-02T11:00:10','end_at':'2028-01-02T11:00:20'})[0],400,'FR-08')
    test('Neleistinas sekundžių intervalas nesukuria vizito',lambda:len(sql('SELECT id FROM appointments WHERE car_id=?',(car,))),1,'FR-08')
    ok(adviser,'appointment_status',{'id':visit,'status':'Atvyko','mileage':99000})
    oid=sql('SELECT id FROM orders WHERE appointment_id=?',(visit,))[0][0]
    test('Savininko keitimas blokuojamas esant neužbaigtam užsakymui',lambda:boss.request('car_save',transfer)[0],409,'FR-05')
    assignment=ok(adviser,'diagnostic_assign',{'order_id':oid,'mechanic_id':3})
    test('Diagnostikos validavimo klaida turi lietuvišką lauką',lambda:mechanic.request('diagnostic_add',{'assignment_id':assignment,'result':'','proposed_works':'Patikra'})[1]['error'],'Laukas „diagnostikos rezultatas“ privalomas (iki 2000 simbolių).','PF-03')
    ok(mechanic,'diagnostic_add',{'assignment_id':assignment,'result':'Nustatytas gedimas','proposed_works':'Pakeisti dalį'})
    version=ok(adviser,'estimate_save',{'order_id':oid,'lines':[{'kind':'Darbas','title':'Patikros darbas','quantity_1000':1000,'unit_cents':2500}]})
    ok(adviser,'estimate_submit',{'id':version});ok(first,'estimate_decide',{'id':version,'status':'Patvirtinta'})
    task=sql('SELECT t.id FROM tasks t JOIN estimate_lines l ON l.id=t.line_id WHERE l.estimate_id=?',(version,))[0][0]
    ok(adviser,'task_assign',{'id':task,'mechanic_id':3})
    ok(mechanic,'task_status',{'id':task,'status':'Vykdomas'})
    ok(mechanic,'task_status',{'id':task,'status':'Baigtas','minutes':25,'note':'Patikra atlikta'})
    ok(adviser,'order_ready',{'id':oid});settle_and_handover(adviser,oid,'5a-owner-payment')
    ok(adviser,'order_close',{'id':oid,'note':'Grąžinta pirmam klientui'})
    test('Vadybininkas gali pakeisti savininką užbaigus aptarnavimą',lambda:adviser.request('car_save',transfer)[0],200,'FR-05')
    test('Naujas savininkas mato įsigytą automobilį',lambda:second.request(f'client/car?id={car}')[0],200)
    test('Senas savininkas nebegali redaguoti perduoto automobilio',lambda:first.request('car_save',{**car_data,'id':car})[0],404)
    test('Senas savininkas išlaiko savo vizito istoriją',lambda:first.request(f'client/appointment?id={visit}')[0],200)
    test('Naujas savininkas negauna seno vizito pakeitęs ID',lambda:second.request(f'client/appointment?id={visit}')[0],404)
    test('Naujas savininkas nemato seno vizito bendroje savitarnoje',lambda:second.request('state')[1]['appointments'],[])
    test('Senas savininkas išlaiko užsakymo nuosavybę',lambda:first.request(f'client/order?id={oid}')[0],200)
    test('Naujas savininkas negauna seno užsakymo',lambda:second.request(f'client/order?id={oid}')[0],404)
    test('Naujas savininkas negauna senos sąmatos',lambda:second.request(f'client/estimate?id={version}')[0],404)
    test('Naujas savininkas negauna seno mokėjimo istorijos',lambda:second.request(f'payments?order_id={oid}')[0],404)
    test('Naujas savininkas negali mokėti už seną užsakymą',lambda:second.request('payment_start',{'order_id':oid,'amount_cents':100,'request_key':'5a-foreign-pay'})[0],404)
    test('Priėmimo kontekstas nekinta keičiant savininką',lambda:sql('SELECT client_id,car_id,problem FROM orders WHERE id=?',(oid,)),[(owners[0],car,slot['problem'])],'NF-16')
    test('Savininko keitimas atsekamas audite',lambda:bool(sql("SELECT 1 FROM audit WHERE entity='Automobilis' AND entity_id=? AND action LIKE 'Pakeistas savininkas:%'",(car,))),True,'PF-02')
    test('Mechanikui neperduodamas visų darbuotojų katalogas',lambda:[u['id'] for u in mechanic.request('state')[1]['users']],[3],'NF-12')
    new_visit=ok(second,'appointment_save',{**slot,'start_at':'2028-01-03T09:00','end_at':'2028-01-03T10:00','problem':'Naujo savininko patikra'})
    test('Naujas vizitas susietas su nauju klientu',lambda:sql('SELECT client_id FROM appointments WHERE id=?',(new_visit,)),[(owners[1],)])
    test('Senas klientas nemato naujo vizito',lambda:first.request(f'client/appointment?id={new_visit}')[0],404)
    test('Naujo vizito pranešimas skirtas naujam klientui',lambda:sql('SELECT DISTINCT client_id FROM notifications WHERE appointment_id=?',(new_visit,)),[(owners[1],)],'FR-28')
    ok(second,'appointment_status',{'id':new_visit,'status':'Atšauktas'})
    test('Vadovas taip pat gali atlikti leistiną savininko keitimą',lambda:boss.request('car_save',{**transfer,'client_id':owners[0]})[0],200,'FR-05')
    test('Atšaukto vizito istorija nelieka naujam automobilio savininkui',lambda:first.request(f'client/appointment?id={new_visit}')[0],404)
    test('Atšaukęs vizitą klientas išlaiko savo įrašą',lambda:second.request(f'client/appointment?id={new_visit}')[0],200)
    def rejects_history_change():
        try:
            with main.connect() as c:c.execute('UPDATE appointments SET client_id=? WHERE id=?',(owners[1],visit))
            return False
        except main.sqlite3.IntegrityError:return True
    test('DB saugo istorinio vizito kliento tapatybę',rejects_history_change,True,'NF-16')
    test('5A scenarijaus FK patikra',lambda:sql('PRAGMA foreign_key_check'),[],'NF-05')

def stage5a_migration(folder):
    old=main.DB;main.DB=folder/'stage4_source.db'
    with main.connect() as c:
        c.executescript((main.ROOT/'testdata/schema_stage4.sql').read_text())
        c.execute("INSERT INTO users(id,username,name,role,password_hash) VALUES(1,'legacy','Vadovas','vadovas',?)",(main.password_hash('Senas2026!'),))
        c.execute("INSERT INTO clients VALUES(1,'Pirmas','1234567','',1)")
        c.execute("INSERT INTO clients VALUES(2,'Antras','1234568','',1)")
        c.execute("INSERT INTO cars VALUES(1,2,'MIG5A','Toyota','Yaris',2020)")
        c.execute("INSERT INTO appointments VALUES(1,1,'2028-01-01T09:00','2028-01-01T10:00',1,'Istorinė problema','Atvyko',1)")
        c.execute("INSERT INTO appointments VALUES(2,1,'2028-01-02T09:00','2028-01-02T10:00',1,'Naujas vizitas','Patvirtintas',1)")
        c.execute("INSERT INTO orders(id,appointment_id,car_id,client_id,problem,mileage,created_at) VALUES(1,1,1,1,'Istorinė problema',100,'2028-01-01')")
    def test(title,fn,expected):check(len(RESULTS)+1,'TS-31','NF-05',title,title,fn,expected)
    def clients():
        with main.connect() as c:return [tuple(r) for r in c.execute('SELECT id,client_id FROM appointments ORDER BY id')]
    main.init_db(seed=False)
    test('5A migracija išlaiko užsakymo klientą, o naujam vizitui naudoja automobilio klientą',clients,[(1,1),(2,2)])
    main.init_db(seed=False)
    test('5A migracija saugiai kartojama',clients,[(1,1),(2,2)])
    test('Prieš 5A migraciją išsaugota DB kopija',lambda:main.DB.with_name(main.DB.name+'.pre_stage5a.bak').exists(),True)
    main.DB=old

def settle_and_handover(adviser,order_id,key):
    status,summary=adviser.request(f'payments?order_id={order_id}')
    assert status==200,summary
    if summary['balance_cents']:
        status,body=adviser.request('payment_local',{'order_id':order_id,'amount_cents':summary['balance_cents'],'request_key':key})
        assert status==200,body
    status,body=adviser.request('order_handover',{'id':order_id})
    assert status==200,body

if __name__=='__main__':
    raise SystemExit(0 if run() else 1)
