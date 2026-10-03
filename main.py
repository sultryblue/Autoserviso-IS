"""Autoserviso mokomoji sistema. Paleidimas: python main.py. Tik vietiniam demonstravimui."""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import payment_provider
import notification_provider
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'servisas.db'
SESSIONS = {}
SESSION_LOCK = threading.Lock()
SESSION_TTL = 1800
PBKDF2_ITERATIONS = 260000
NOTIFICATION_LOCK = threading.Lock()
# Explicit trusted deployment configuration; never trust a browser-supplied X-Forwarded-Proto.
PUBLIC_ORIGIN = os.environ.get('SERVISO_PUBLIC_ORIGIN','').rstrip('/')
if PUBLIC_ORIGIN and (urlparse(PUBLIC_ORIGIN).scheme!='https' or not urlparse(PUBLIC_ORIGIN).netloc
                      or urlparse(PUBLIC_ORIGIN).path or urlparse(PUBLIC_ORIGIN).query or urlparse(PUBLIC_ORIGIN).fragment):
    raise RuntimeError('SERVISO_PUBLIC_ORIGIN turi būti HTTPS kilmė be kelio.')

class RuleError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status

def now():
    return datetime.now().isoformat(timespec='seconds')

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return f'pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}'

def password_ok(password, saved):
    try:
        if ':' in saved:
            salt,digest=saved.split(':');rounds=260000
        else:
            algorithm,factor,salt,digest=saved.split('$')
            if algorithm!='pbkdf2_sha256': return False
            rounds=int(factor)
        if not 1<=rounds<=2000000 or not re.fullmatch(r'[0-9a-f]{32}',salt) or not re.fullmatch(r'[0-9a-f]{64}',digest): return False
        computed=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),rounds).hex()
        return hmac.compare_digest(computed,digest)
    except (ValueError,TypeError): return False

def session_cookie(token, expired=False):
    return f'sid={token}; HttpOnly; SameSite=Strict; Path=/' + ('; Secure' if PUBLIC_ORIGIN else '') + ('; Max-Age=0' if expired else '')

def connect():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def rows(c, query, args=()):
    return [dict(r) for r in c.execute(query, args)]

def one(c, table, key):
    # Table names originate only from the application, never from request fields.
    r = c.execute(f'SELECT * FROM {table} WHERE id=?', (integer(key),)).fetchone()
    if not r:
        raise RuleError('Įrašas nerastas.', 404)
    return dict(r)

def integer(value, minimum=1, maximum=1000000000):
    try:
        number = int(str(value))
    except (ValueError, TypeError):
        raise RuleError('Reikia įrašyti sveikąjį skaičių.')
    if number < minimum or number > maximum:
        raise RuleError(f'Skaičius turi būti nuo {minimum} iki {maximum}.')
    return number

def required(data, field, maximum=500):
    s = str(data.get(field, '')).strip()
    if not s or len(s) > maximum:
        label={'name':'vardas','phone':'telefonas','plate':'numeris','make':'markė','model':'modelis','problem':'priežastis','decision_note':'kliento sprendimo pastaba','note':'pastaba','title':'pavadinimas','password':'slaptažodis','username':'prisijungimo vardas','result':'diagnostikos rezultatas','proposed_works':'siūlomi darbai','from':'laikotarpio pradžia','to':'laikotarpio pabaiga','date':'data','start_at':'vizito pradžia','end_at':'vizito pabaiga','status':'būsena','role':'rolė'}.get(field,'duomenys')
        raise RuleError(f'Laukas „{label}“ privalomas (iki {maximum} simbolių).')
    return s

def role(user, *allowed):
    if user['role'] not in allowed:
        raise RuleError('Šiam veiksmui neturite teisių.', 403)

def adviser(user):
    role(user, 'vadybininkas', 'vadovas')

def client_identity(c, user):
    role(user, 'klientas')
    linked = c.execute('SELECT client_id FROM users WHERE id=? AND role=? AND active=1',
                       (user['id'], 'klientas')).fetchone()
    if not linked or linked['client_id'] is None:
        raise RuleError('Paskyra nesusieta su klientu.', 403)
    client = one(c, 'clients', linked['client_id'])
    if not client['active']:
        raise RuleError('Kliento paskyra neaktyvi.', 403)
    return client

def owned(c, user, table, key):
    cid = client_identity(c, user)['id']
    joins = {
        'cars': 'cars x',
        'appointments': 'appointments x JOIN cars v ON v.id=x.car_id',
        'orders': 'orders x JOIN appointments a ON a.id=x.appointment_id JOIN cars v ON v.id=a.car_id'
    }
    owner = 'x.client_id'
    if not c.execute(f'SELECT 1 FROM {joins[table]} WHERE x.id=? AND {owner}=?',
                     (integer(key), cid)).fetchone():
        raise RuleError('Įrašas nerastas arba neprieinamas.', 404)
    return one(c, table, key)

def client_snapshot(c, user):
    client = client_identity(c, user)
    cid = client['id']
    result = {
        'user': {k:user[k] for k in ('id','name','role','username')},
        'client': {k:client[k] for k in ('id','name','phone','email')},
        'cars': rows(c, 'SELECT id,plate,make,model,year FROM cars WHERE client_id=?', (cid,)),
        'appointments': rows(c, '''SELECT a.id,a.car_id,a.start_at,a.end_at,a.bay,a.problem,a.status,v.plate
            FROM appointments a JOIN cars v ON v.id=a.car_id WHERE a.client_id=? ORDER BY a.start_at''', (cid,)),
        'orders': rows(c, '''SELECT o.id,o.appointment_id,o.mileage,o.status,o.created_at,o.handover_at,o.closed_at,
            o.problem,v.plate,v.make,v.model FROM orders o JOIN appointments a ON a.id=o.appointment_id
            JOIN cars v ON v.id=o.car_id WHERE o.client_id=? ORDER BY o.id DESC''', (cid,))
    }
    result['estimates']=rows(c,'''SELECT e.id,e.order_id,e.version,e.status,e.total_cents,e.created_at,e.submitted_at
        FROM estimates e JOIN orders o ON o.id=e.order_id JOIN appointments a ON a.id=o.appointment_id
        JOIN cars v ON v.id=a.car_id WHERE o.client_id=? AND e.status<>'Rengiama' ORDER BY e.version''',(cid,))
    result['lines']=rows(c,'''SELECT l.* FROM estimate_lines l JOIN estimates e ON e.id=l.estimate_id
        JOIN orders o ON o.id=e.order_id JOIN appointments a ON a.id=o.appointment_id
        JOIN cars v ON v.id=a.car_id WHERE o.client_id=? AND e.status<>'Rengiama' ORDER BY l.id''',(cid,))
    result['decisions']=rows(c,'SELECT estimate_id,decision,decided_at,note FROM estimate_decisions WHERE client_id=?',(cid,))
    result['tasks']=rows(c,'''SELECT t.id,e.order_id,l.title,t.status,t.minutes FROM tasks t
        JOIN estimate_lines l ON l.id=t.line_id JOIN estimates e ON e.id=l.estimate_id
        JOIN orders o ON o.id=e.order_id JOIN appointments a ON a.id=o.appointment_id
        JOIN cars v ON v.id=a.car_id WHERE o.client_id=? AND e.status='Patvirtinta' ''',(cid,))
    add_payment_data(c,result)
    return result

def slot_conflict(c, car_id, bay, start, end, exclude=0):
    return c.execute("""SELECT 1 FROM appointments WHERE status IN ('Patvirtintas','Atvyko')
        AND id<>? AND (bay=? OR car_id=?) AND start_at<? AND end_at>?""",
        (exclude, bay, car_id, end, start)).fetchone() is not None

def free_slots(c, user, d):
    role(user, 'klientas', 'vadybininkas', 'vadovas')
    car = owned(c,user,'cars',d.get('car_id')) if user['role']=='klientas' else one(c,'cars',d.get('car_id'))
    exclude = integer(d.get('id',0),0)
    if exclude:
        visit = owned(c,user,'appointments',exclude) if user['role']=='klientas' else one(c,'appointments',exclude)
        if visit['status']!='Patvirtintas': raise RuleError('Vizito keisti nebegalima.',409)
    try:
        day = datetime.strptime(required(d,'date',10),'%Y-%m-%d')
    except ValueError:
        raise RuleError('Neteisinga data.')
    duration = integer(d.get('minutes',60),1,600)
    result=[]
    start=day.replace(hour=8)
    while start+timedelta(minutes=duration)<=day.replace(hour=18):
        end=start+timedelta(minutes=duration)
        a,b=start.isoformat(timespec='minutes'),end.isoformat(timespec='minutes')
        for bay in (1,2):
            if not slot_conflict(c,car['id'],bay,a,b,exclude):
                result.append({'start_at':a,'end_at':b,'bay':bay})
        start+=timedelta(minutes=30)
    return {'slots':result}

def migrate_stage1():
    """Rebuild only the two changed tables; keep IDs, references and passwords."""
    with connect() as c:
        existing=c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if not existing or 'client_id' in existing['sql']:
            return
        backup=DB.with_name(DB.name+'.pre_stage1.bak')
        if not backup.exists():
            with sqlite3.connect(backup) as target: c.backup(target)
        schema=(ROOT/'schema.sql').read_text(encoding='utf-8')
        c.execute('PRAGMA foreign_keys=OFF')
        c.execute('BEGIN IMMEDIATE')
        for table in ('users','appointments'):
            ddl=re.search(r'CREATE TABLE IF NOT EXISTS '+table+r' \(.*?\n\);',schema,re.S).group()
            c.execute(ddl.replace('IF NOT EXISTS '+table,table+'_stage1'))
            columns=[r['name'] for r in c.execute(f'PRAGMA table_info({table})')]
            fields=','.join(columns)
            selected=','.join("CASE status WHEN 'Suplanuotas' THEN 'Patvirtintas' ELSE status END" if x=='status' else x for x in columns)
            if table=='appointments':
                fields+=',client_id'
                selected+=', (SELECT client_id FROM cars WHERE cars.id=appointments.car_id)'
            c.execute(f'INSERT INTO {table}_stage1({fields}) SELECT {selected} FROM {table}')
            c.execute(f'DROP TABLE {table}')
            c.execute(f'ALTER TABLE {table}_stage1 RENAME TO {table}')
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Migracijos ryšių patikra nepavyko.')
        c.commit()

def seed_client_account(c):
    client=c.execute("SELECT id FROM clients WHERE email='klientas.a@example.com' AND active=1").fetchone()
    if client and not c.execute('SELECT 1 FROM users WHERE client_id=? OR username=?',(client['id'],'klientas')).fetchone():
        c.execute('INSERT INTO users(username,name,role,password_hash,client_id) VALUES(?,?,?,?,?)',
                  ('klientas','Mokomasis klientas A','klientas',password_hash('Demo2026!'),client['id']))

def migrate_stage2():
    with connect() as c:
        fields=[r['name'] for r in c.execute('PRAGMA table_info(estimates)')]
        if not fields or 'submitted_at' in fields: return
        backup=DB.with_name(DB.name+'.pre_stage2.bak')
        if not backup.exists():
            with sqlite3.connect(backup) as target: c.backup(target)
        # Old employee decisions cannot be represented as decisions made by a client.
        # Never silently invent their authorship or erase completed work.
        if c.execute("SELECT 1 FROM estimates WHERE status<>'Rengiama'").fetchone() or c.execute('SELECT 1 FROM tasks').fetchone():
            raise RuntimeError('Senoje DB yra darbuotojų suderintų sąmatų arba darbų. DB nepakeista; kopija: '+str(backup)+'. Demonstravimui naudokite --db naujas_demo.db.')
        schema=(ROOT/'schema.sql').read_text(encoding='utf-8')
        c.execute('PRAGMA foreign_keys=OFF');c.execute('BEGIN IMMEDIATE')
        for table in ('estimates','estimate_lines','tasks'):
            ddl=re.search(r'CREATE TABLE IF NOT EXISTS '+table+r' \(.*?\n\);',schema,re.S).group()
            c.execute(ddl.replace('IF NOT EXISTS '+table,table+'_stage2'))
        c.execute('''INSERT INTO estimates_stage2(id,order_id,version,status,total_cents,created_at,created_by)
          SELECT e.id,e.order_id,e.version,e.status,e.total_cents,e.created_at,a.created_by
          FROM estimates e JOIN orders o ON o.id=e.order_id JOIN appointments a ON a.id=o.appointment_id''')
        c.execute('''INSERT INTO estimate_lines_stage2(id,estimate_id,kind,title,quantity_1000,unit_cents,line_total_cents)
          SELECT id,estimate_id,kind,title,quantity*1000,unit_cents,quantity*unit_cents FROM estimate_lines''')
        for table in ('tasks','estimate_lines','estimates'): c.execute(f'DROP TABLE {table}')
        for table in ('estimates','estimate_lines','tasks'): c.execute(f'ALTER TABLE {table}_stage2 RENAME TO {table}')
        if c.execute('PRAGMA foreign_key_check').fetchall(): raise RuntimeError('2 etapo migracijos FK klaida.')
        c.commit()

def confirmed_lines(c, order_id):
    return rows(c,'''SELECT p.* FROM estimate_lines p WHERE p.id IN (
        SELECT DISTINCT COALESCE(l.origin_line_id,l.id) FROM estimate_lines l
        JOIN estimates e ON e.id=l.estimate_id WHERE e.order_id=? AND e.status='Patvirtinta') ORDER BY p.id''',(order_id,))

def confirmed_total(c, order_id):
    return sum(x['line_total_cents'] for x in confirmed_lines(c,order_id))

def migrate_stage3():
    with connect() as c:
        columns={r['name'] for r in c.execute('PRAGMA table_info(orders)')}
        if not columns or 'handover_at' in columns: return
        backup=DB.with_name(DB.name+'.pre_stage3.bak')
        if not backup.exists():
            with sqlite3.connect(backup) as target: c.backup(target)
        c.execute('BEGIN IMMEDIATE')
        c.execute('ALTER TABLE orders ADD COLUMN handover_at TEXT')
        c.execute('ALTER TABLE orders ADD COLUMN closed_by INTEGER REFERENCES users(id)')
        c.execute('ALTER TABLE audit ADD COLUMN external_actor TEXT')
        c.execute("ALTER TABLE audit ADD COLUMN result TEXT NOT NULL DEFAULT 'Atlikta'")
        # Never fabricate payments or handover evidence for historical orders.
        c.commit()

def migrate_stage4():
    with connect() as c:
        columns={r['name'] for r in c.execute('PRAGMA table_info(orders)')}
        if not columns:return
        legacy=rows(c,'SELECT id,password_hash FROM users')
        legacy=[u for u in legacy if re.fullmatch(r'[0-9a-f]{32}:[0-9a-f]{64}',u['password_hash'])]
        if 'client_id' in columns and not legacy:return
        backup=DB.with_name(DB.name+'.pre_stage4.bak')
        if not backup.exists():
            with sqlite3.connect(backup) as target:c.backup(target)
        c.execute('PRAGMA foreign_keys=OFF');c.execute('BEGIN IMMEDIATE')
        if 'client_id' not in columns:
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_appointment_identity ON appointments(id,car_id)')
            ddl=re.search(r'CREATE TABLE IF NOT EXISTS orders \(.*?\n\);',(ROOT/'schema.sql').read_text(),re.S).group()
            c.execute(ddl.replace('IF NOT EXISTS orders','orders_stage4'))
            c.execute('''INSERT INTO orders_stage4(id,appointment_id,car_id,client_id,problem,mileage,status,
                created_at,handover_at,closed_at,closed_by,closing_note)
                SELECT o.id,o.appointment_id,a.car_id,v.client_id,a.problem,o.mileage,o.status,
                o.created_at,o.handover_at,o.closed_at,o.closed_by,o.closing_note FROM orders o
                JOIN appointments a ON a.id=o.appointment_id JOIN cars v ON v.id=a.car_id''')
            c.execute('DROP TRIGGER IF EXISTS decision_insert_guard')
            c.execute('DROP TABLE orders');c.execute('ALTER TABLE orders_stage4 RENAME TO orders')
        for u in legacy:
            salt,digest=u['password_hash'].split(':')
            c.execute('UPDATE users SET password_hash=? WHERE id=?',(f'pbkdf2_sha256$260000${salt}${digest}',u['id']))
        if c.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('4 etapo migracijos FK klaida.')
        c.commit()

def migrate_stage5a():
    """Keep the visit's client when a car is later sold; preserve existing IDs."""
    with connect() as c:
        fields=[r['name'] for r in c.execute('PRAGMA table_info(appointments)')]
        if not fields or 'client_id' in fields: return
        backup=DB.with_name(DB.name+'.pre_stage5a.bak')
        if not backup.exists():
            with sqlite3.connect(backup) as target:c.backup(target)
        c.execute('BEGIN IMMEDIATE')
        c.execute('ALTER TABLE appointments ADD COLUMN client_id INTEGER REFERENCES clients(id)')
        c.execute('''UPDATE appointments SET client_id=COALESCE(
            (SELECT client_id FROM orders WHERE appointment_id=appointments.id),
            (SELECT client_id FROM cars WHERE id=appointments.car_id))''')
        c.execute('DROP TRIGGER IF EXISTS notification_insert_guard')
        if c.execute('SELECT 1 FROM appointments WHERE client_id IS NULL').fetchone() or c.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('5A etapo vizitų migracijos ryšių klaida.')

def queue_notification(c,user,event_key,event_type,content,*,appointment_id=None,order_id=None,estimate_id=None,payment_id=None):
    if order_id:
        cid=one(c,'orders',order_id)['client_id']
    else:
        cid=one(c,'appointments',appointment_id)['client_id']
    client=one(c,'clients',cid)
    for channel,recipient in (('SMS',client['phone']),('El. paštas',client['email'])):
        if not recipient:continue
        if c.execute('SELECT 1 FROM notifications WHERE event_key=? AND channel=?',(event_key,channel)).fetchone():continue
        nid=c.execute('''INSERT INTO notifications(client_id,appointment_id,order_id,estimate_id,payment_id,
            event_key,channel,type,recipient,content,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (cid,appointment_id,order_id,estimate_id,payment_id,event_key,channel,event_type,recipient,content,now())).lastrowid
        audit(c,user,'Pranešimas',nid,'Sukurta pranešimo užduotis: '+event_type)

def dispatch_notifications():
    """Durable outbox: caller has already committed the business transaction.

    Delivery occurs outside any business/DB transaction. The stable provider key
    protects retries after a crash between delivery and saving its result.
    Only one dispatcher runs in this local server process.
    """
    with NOTIFICATION_LOCK:
        with connect() as c:pending=rows(c,"SELECT * FROM notifications WHERE status='Sukurtas' ORDER BY id")
        for n in pending:
            try:
                result=notification_provider.send(request_key=n['event_key']+'|'+n['channel'],
                    channel=n['channel'],recipient=n['recipient'],content=n['content'])
            except TimeoutError:result={'result':'Siuntimo klaida','provider_id':None,'error_code':'MOCK_TIMEOUT'}
            except Exception:result={'result':'Siuntimo klaida','provider_id':None,'error_code':'PROVIDER_ERROR'}
            if not isinstance(result,dict):result={'result':'Siuntimo klaida','provider_id':None,'error_code':'PROVIDER_ERROR'}
            # Store only whitelisted technical fields, never an exception or raw provider response.
            status=result.get('result')
            code=result.get('error_code','')
            if status not in ('Perduotas tiekėjui','Siuntimo klaida') or code not in ('','MOCK_UNAVAILABLE','MOCK_TIMEOUT','MOCK_KEY_CONFLICT','PROVIDER_ERROR'):
                result={'provider_id':None};status='Siuntimo klaida';code='PROVIDER_ERROR'
            provider_id=result.get('provider_id')
            if provider_id is not None and not re.fullmatch(r'mock_msg_[0-9a-f]{24}',str(provider_id)):
                provider_id=None;status='Siuntimo klaida';code='PROVIDER_ERROR'
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                if one(c,'notifications',n['id'])['status']!='Sukurtas':continue
                attempt=c.execute('SELECT COALESCE(MAX(attempt_no),0)+1 FROM notification_attempts WHERE notification_id=?',(n['id'],)).fetchone()[0]
                c.execute('''INSERT INTO notification_attempts(notification_id,attempt_no,attempted_at,provider_id,result,error_code)
                    VALUES(?,?,?,?,?,?)''',(n['id'],attempt,now(),provider_id,status,code))
                c.execute('UPDATE notifications SET status=? WHERE id=?',(status,n['id']))
                audit(c,None,'Pranešimas',n['id'],status,result='Klaida' if status=='Siuntimo klaida' else 'Atlikta',external_actor='Pranešimų paslauga (imitacija)')

def dispatch_after_commit():
    try:dispatch_notifications()
    except sqlite3.Error:
        # Business data are committed. Unresolved outbox rows survive for the next dispatch/startup.
        pass

def notification_admin(c,user):
    adviser(user)
    data={'notifications':rows(c,'''SELECT n.id,n.client_id,n.order_id,n.appointment_id,n.estimate_id,n.payment_id,
        n.channel,n.type,n.recipient,n.content,n.status,n.created_at,
        (SELECT COUNT(*) FROM notification_attempts a WHERE a.notification_id=n.id) attempts
        FROM notifications n ORDER BY n.id DESC''')}
    if user['role']=='vadovas':
        data['attempts']=rows(c,'SELECT * FROM notification_attempts ORDER BY id DESC')
        data['mock_mode']=notification_provider.mode()
    return data

def notification_mutate(c,user,action,d):
    if action=='notification_mode':
        role(user,'vadovas');mode=required(d,'mode',20)
        if mode not in notification_provider.MODES:raise RuleError('Nežinomas imitacijos režimas.')
        audit(c,user,'Pranešimų imitacija',0,'Nustatytas režimas: '+mode)
        return {'ok':True,'_notification_mode':mode}
    adviser(user);n=one(c,'notifications',d.get('id'))
    attempt=c.execute('SELECT COALESCE(MAX(attempt_no),0) FROM notification_attempts WHERE notification_id=?',(n['id'],)).fetchone()[0]
    if n['status']!='Siuntimo klaida' or integer(d.get('attempt_no'),0)!=attempt:
        raise RuleError('Galima kartoti tik dabartinį nepavykusį bandymą. Atnaujinkite sąrašą.',409)
    c.execute("UPDATE notifications SET status='Sukurtas' WHERE id=?",(n['id'],))
    audit(c,user,'Pranešimas',n['id'],'Paprašyta pakartoti siuntimą')
    return {'ok':True,'id':n['id']}

def payment_summary(c, order_id):
    total=confirmed_total(c,order_id)
    amounts=c.execute('''SELECT COALESCE(SUM(CASE WHEN status='Sėkmingas' THEN amount_cents ELSE 0 END),0),
        COALESCE(SUM(CASE WHEN status='Laukia' THEN amount_cents ELSE 0 END),0)
        FROM payments WHERE order_id=?''',(order_id,)).fetchone()
    paid,reserved=amounts
    balance=max(0,total-paid)
    return {'confirmed_total_cents':total,'paid_cents':paid,'balance_cents':balance,
            'reserved_cents':reserved,'available_cents':max(0,balance-reserved)}

def payment_history(c, order_id):
    # Explicit projection: no request keys, provider controls or technical logs in the UI.
    return rows(c,'''SELECT id,order_id,amount_cents,status,method,created_at,resolved_at
        FROM payments WHERE order_id=? ORDER BY id''',(order_id,))

def add_payment_data(c, result):
    result['payments']=[]
    for order in result['orders']:
        order.update(payment_summary(c,order['id']))
        result['payments'].extend(payment_history(c,order['id']))

def payment_access(c, user, order_id):
    role(user,'klientas','vadybininkas','vadovas')
    return owned(c,user,'orders',order_id) if user['role']=='klientas' else one(c,'orders',order_id)

def read_payments(c, user, order_id):
    order=payment_access(c,user,order_id)
    return {**payment_summary(c,order['id']),'payments':payment_history(c,order['id'])}

def create_payment(c, user, d, local=False):
    adviser(user) if local else role(user,'klientas')
    order=payment_access(c,user,d.get('order_id'))
    amount=integer(d.get('amount_cents'))
    request_key=required(d,'request_key',100)
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',request_key): raise RuleError('Neteisingas mokėjimo užklausos raktas.')
    method='Vietoje' if local else 'Internetu'
    prior=c.execute('SELECT * FROM payments WHERE request_key=?',(request_key,)).fetchone()
    if prior:
        if (prior['order_id'],prior['amount_cents'],prior['method'],prior['recorded_by']) != (order['id'],amount,method,user['id']):
            raise RuleError('Šis užklausos raktas jau panaudotas kitokiam mokėjimui.',409)
        return {'ok':True,'id':prior['id'],'duplicate':True,'status':prior['status']}
    open_order(c,order['id'])
    if amount>payment_summary(c,order['id'])['available_cents']:
        raise RuleError('Suma viršija leistiną likutį; įvertinkite laukiančius mokėjimus.',409)
    stamp=now();status='Sėkmingas' if local else 'Laukia'
    key=c.execute('''INSERT INTO payments(order_id,operation_id,request_key,amount_cents,status,method,
        created_at,resolved_at,recorded_by,technical_code) VALUES(?,?,?,?,?,?,?,?,?,?)''',
        (order['id'],None if local else payment_provider.new_operation(),request_key,amount,status,method,
         stamp,stamp if local else None,user['id'],'LOCAL_RECORDED' if local else 'MOCK_PENDING')).lastrowid
    audit(c,user,'Mokėjimas',key,'Užregistruotas vietinis mokėjimas' if local else 'Inicijuotas mokėjimas (imitacija)')
    if local:
        queue_notification(c,user,f'payment:{key}','Sėkmingas mokėjimas',f'Užsakymo U-{order["id"]} mokėjimas sėkmingai užskaitytas.',order_id=order['id'],payment_id=key)
    return {'ok':True,'id':key,'status':status,'duplicate':False}

def process_payment_result(c, message):
    """Trusted adapter messages only. Called inside the same write transaction as accounting."""
    if not payment_provider.verified(message): raise RuleError('Nepatvirtintas mokėjimo tiekėjo atsakymas.',403)
    operation=required(message,'operation_id',100)
    order_id=integer(message.get('order_id'));amount=integer(message.get('amount_cents'))
    status=message.get('status')
    payment=c.execute('SELECT * FROM payments WHERE operation_id=?',(operation,)).fetchone()
    if not payment: raise RuleError('Tiekėjo operacija neatpažinta.',404)
    key=payment['id']
    if (payment['order_id'],payment['amount_cents'],'EUR') != (order_id,amount,message.get('currency')) or status not in payment_provider.STATUSES:
        audit(c,None,'Mokėjimas',key,'Atmestas neatitinkantis tiekėjo rezultatas',result='Klaida')
        return {'ok':False,'error':'Tiekėjo duomenys neatitinka mokėjimo. Likutis nepakeistas.','_http_status':409}
    if payment['status']!='Laukia':
        if status!=payment['status']:
            audit(c,None,'Mokėjimas',key,'Prieštaraujantis galutinis tiekėjo rezultatas',result='Klaida')
            return {'ok':False,'error':'Mokėjimas jau turi kitą galutinį rezultatą. Likutis nepakeistas.','_http_status':409}
        return {'ok':True,'id':key,'status':payment['status'],'duplicate':True}
    if status=='Laukia':
        # A delay/timeout is not proof of failure: the existing reservation remains.
        audit(c,None,'Mokėjimas',key,'Tiekėjo rezultatas: Laukia')
        return {'ok':True,'id':key,'status':status,'duplicate':True}
    code='MOCK_SUCCESS' if status=='Sėkmingas' else 'MOCK_FAILED'
    c.execute('UPDATE payments SET status=?,resolved_at=?,technical_code=? WHERE id=?',(status,now(),code,key))
    audit(c,None,'Mokėjimas',key,'Tiekėjo rezultatas: '+status)
    if status=='Sėkmingas':
        queue_notification(c,None,f'payment:{key}','Sėkmingas mokėjimas',f'Užsakymo U-{order_id} mokėjimas sėkmingai užskaitytas.',order_id=order_id,payment_id=key)
    return {'ok':True,'id':key,'status':status,'duplicate':False}

def mock_payment_result(c, user, d):
    role(user,'klientas')
    payment=one(c,'payments',d.get('id'))
    owned(c,user,'orders',payment['order_id'])
    if payment['method']!='Internetu': raise RuleError('Vietiniam mokėjimui tiekėjo rezultatas netaikomas.',409)
    # Browser selects only a demo scenario; IDs, amount and signature come from the adapter.
    return process_payment_result(c,payment_provider.result(payment,required(d,'status',20)))

def completion_scope(c, order_id):
    if c.execute("SELECT 1 FROM estimates WHERE order_id=? AND status IN ('Rengiama','Pateikta')",(order_id,)).fetchone():
        raise RuleError('Reikia išspręsti visas rengiamas arba pateiktas sąmatų versijas.',409)
    approved=confirmed_lines(c,order_id);tasks=order_tasks(c,order_id);current=current_estimate(c,order_id)
    work_ids={line['id'] for line in approved if line['kind']=='Darbas'}
    done=bool(approved) and work_ids=={t['line_id'] for t in tasks} and all(t['status']=='Baigtas' for t in tasks)
    rejected=not approved and not tasks and current and current['status']=='Atmesta'
    if not (done or rejected): raise RuleError('Reikia užbaigti visus patvirtintos apimties darbus.',409)

def diagnostic_rows(c, order_id):
    return rows(c,'''SELECT d.*,COALESCE(a.order_id,e.order_id) order_id FROM diagnostic_entries d
        LEFT JOIN diagnostic_assignments a ON a.id=d.assignment_id
        LEFT JOIN tasks t ON t.id=d.task_id LEFT JOIN estimate_lines l ON l.id=t.line_id
        LEFT JOIN estimates e ON e.id=l.estimate_id WHERE COALESCE(a.order_id,e.order_id)=? ORDER BY d.id''',(order_id,))

def open_order(c, key):
    order=one(c,'orders',key)
    if order['status'] in ('Uždarytas','Atšauktas') or order['handover_at']:
        raise RuleError('Užsakymas užbaigtas arba automobilis jau perduotas; keisti negalima.',409)
    return order

def order_after_proposal(c, order, submitted=False):
    if order['status'] in ('Vykdomas','Paruoštas'):
        status='Vykdomas'
    elif submitted:
        status='Derinamas'
    elif confirmed_lines(c,order['id']):
        status='Patvirtintas'
    else:
        latest=current_estimate(c,order['id'])
        status='Derinamas' if latest and latest['status']=='Atmesta' else 'Naujas'
    c.execute('UPDATE orders SET status=? WHERE id=?',(status,order['id']))

def client_estimate(c,user,key):
    estimate=one(c,'estimates',key)
    owned(c,user,'orders',estimate['order_id'])
    if estimate['status']=='Rengiama': raise RuleError('Sąmata dar nepateikta.',404)
    return {'estimate':{k:estimate[k] for k in ('id','order_id','version','status','total_cents','created_at','submitted_at')},
            'lines':rows(c,'SELECT * FROM estimate_lines WHERE estimate_id=? ORDER BY id',(estimate['id'],)),
            'decision':next(iter(rows(c,'SELECT decision,decided_at,note FROM estimate_decisions WHERE estimate_id=?',(estimate['id'],))),None)}

def diagnostic_mutate(c,user,action,d):
    if action=='diagnostic_assign':
        adviser(user);order=open_order(c,d.get('order_id'));mechanic=one(c,'users',d.get('mechanic_id'))
        if mechanic['role']!='mechanikas' or not mechanic['active']: raise RuleError('Pasirinkite aktyvų mechaniką.',409)
        active=c.execute('SELECT * FROM diagnostic_assignments WHERE order_id=? AND ended_at IS NULL',(order['id'],)).fetchone()
        if active and active['mechanic_id']==mechanic['id']: return active['id']
        stamp=now()
        c.execute('UPDATE diagnostic_assignments SET ended_at=? WHERE order_id=? AND ended_at IS NULL',(stamp,order['id']))
        key=c.execute('INSERT INTO diagnostic_assignments(order_id,mechanic_id,assigned_by,assigned_at) VALUES(?,?,?,?)',
                      (order['id'],mechanic['id'],user['id'],stamp)).lastrowid
        audit(c,user,'Diagnostikos paskyrimas',key,'Paskirtas mechanikas '+str(mechanic['id']))
        return key
    role(user,'mechanikas')
    if set(d)-{'assignment_id','task_id','result','proposed_works'}:
        raise RuleError('Diagnostikai leidžiami tik rezultatas ir siūlomi darbai; kainos nenustatomos.')
    aid,tid=d.get('assignment_id'),d.get('task_id')
    if bool(aid)==bool(tid): raise RuleError('Pasirinkite vieną diagnostikos paskyrimą arba savo darbą.')
    if aid:
        assignment=one(c,'diagnostic_assignments',aid)
        if assignment['mechanic_id']!=user['id'] or assignment['ended_at'] is not None:
            raise RuleError('Diagnostika jums aktyviai nepaskirta.',403)
        order=open_order(c,assignment['order_id'])
    else:
        task=one(c,'tasks',tid)
        if task['mechanic_id']!=user['id']: raise RuleError('Darbas paskirtas kitam mechanikui.',403)
        line=one(c,'estimate_lines',task['line_id']);estimate=one(c,'estimates',line['estimate_id'])
        order=open_order(c,estimate['order_id'])
        if estimate['status']!='Patvirtinta' or task['status'] not in ('Vykdomas','Sustabdytas','Baigtas'):
            raise RuleError('Papildomą gedimą registruokite vykdydami patvirtintą savo darbą.',409)
    key=c.execute('INSERT INTO diagnostic_entries(assignment_id,task_id,author_id,created_at,result,proposed_works,kind) VALUES(?,?,?,?,?,?,?)',
        (aid,tid,user['id'],now(),required(d,'result',2000),required(d,'proposed_works',2000),'Pirminė' if aid else 'Papildoma')).lastrowid
    if order['status']=='Paruoštas':
        c.execute("UPDATE orders SET status='Vykdomas' WHERE id=?",(order['id'],))
        audit(c,user,'Užsakymas',order['id'],'Atšauktas paruošimas: papildomas gedimas')
    audit(c,user,'Diagnostikos įrašas',key,'Įrašytas rezultatas ir siūlomi darbai')
    return key

def save_estimate(c,user,d):
    adviser(user);order=open_order(c,d.get('order_id'));key=d.get('id')
    if not diagnostic_rows(c,order['id']): raise RuleError('Pirmiausia turi būti įrašytas mechaniko diagnostikos rezultatas.',409)
    current=current_estimate(c,order['id'])
    if key:
        estimate=one(c,'estimates',key)
        if estimate['order_id']!=order['id'] or estimate['status']!='Rengiama': raise RuleError('Redaguoti galima tik šio užsakymo rengiamą versiją.',409)
    elif current and current['status'] in ('Rengiama','Pateikta'):
        raise RuleError('Pirmiausia užbaikite esamos versijos rengimą ir derinimą.',409)
    proposed=d.get('lines',[])
    if not isinstance(proposed,list) or len(proposed)>100: raise RuleError('Netinkamas sąmatos eilučių sąrašas.')
    approved=confirmed_lines(c,order['id']);origins={x['id']:x for x in approved};seen=set();parsed=[]
    for line in proposed:
        origin=line.get('origin_line_id')
        if origin is not None:
            origin=integer(origin)
            if origin not in origins or origin in seen: raise RuleError('Neteisinga arba pasikartojanti kilmės eilutė.',409)
            seen.add(origin);source=origins[origin]
            for field in ('kind','title','quantity_1000','unit_cents','line_total_cents'):
                if field in line and line[field]!=source[field]: raise RuleError('Patvirtintos eilutės keisti negalima.',409)
            continue  # Server copies every approved origin exactly once, even if omitted by UI.
        kind=required(line,'kind');title=required(line,'title',150)
        if kind not in ('Darbas','Detalė'): raise RuleError('Neteisingas eilutės tipas.')
        qty=integer(line.get('quantity_1000'),1,999000);price=integer(line.get('unit_cents'),0,10000000)
        if any((kind,title,qty,price)==(x['kind'],x['title'],x['quantity_1000'],x['unit_cents']) for x in approved):
            raise RuleError('Jau patvirtinta eilutė perkeliama pagal kilmę, ne kaip naujas darbas.',409)
        parsed.append((None,kind,title,qty,price,(qty*price+500)//1000))
    if not parsed: raise RuleError('Įrašykite bent vieną naujai siūlomą eilutę.')
    if not approved and not any(x[1]=='Darbas' for x in parsed): raise RuleError('Pradinėje sąmatoje turi būti darbas.')
    copied=[(x['id'],x['kind'],x['title'],x['quantity_1000'],x['unit_cents'],x['line_total_cents']) for x in approved]
    total=sum(x[5] for x in copied+parsed)
    if key:
        c.execute('DELETE FROM estimate_lines WHERE estimate_id=?',(key,))
        c.execute('UPDATE estimates SET total_cents=? WHERE id=?',(total,key))
    else:
        version=current['version']+1 if current else 1
        key=c.execute('INSERT INTO estimates(order_id,version,total_cents,created_by,created_at) VALUES(?,?,?,?,?)',
                      (order['id'],version,total,user['id'],now())).lastrowid
    c.executemany('INSERT INTO estimate_lines(estimate_id,origin_line_id,kind,title,quantity_1000,unit_cents,line_total_cents) VALUES(?,?,?,?,?,?,?)',
                  [(key,*x) for x in copied+parsed])
    order_after_proposal(c,order)
    audit(c,user,'Sąmata',key,'Išsaugota rengiama versija; suma '+str(total)+' ct')
    return key

def decide_estimate(c,user,d):
    role(user,'klientas');key=d.get('id');estimate=one(c,'estimates',key)
    owned(c,user,'orders',estimate['order_id']);order=open_order(c,estimate['order_id'])
    if estimate['status']!='Pateikta': raise RuleError('Sprendimas galimas tik dėl pateiktos ir dar neišspręstos versijos.',409)
    status=required(d,'status')
    if status not in ('Patvirtinta','Atmesta'): raise RuleError('Neteisingas sprendimas.')
    note=str(d.get('decision_note','')).strip()
    if len(note)>2000: raise RuleError('Pastaba per ilga.')
    c.execute('INSERT INTO estimate_decisions(estimate_id,client_id,user_id,decision,decided_at,note) VALUES(?,?,?,?,?,?)',
              (estimate['id'],client_identity(c,user)['id'],user['id'],status,now(),note))
    if status=='Patvirtinta':
        for line in confirmed_lines(c,order['id']):
            if line['kind']=='Darbas':
                c.execute('INSERT INTO tasks(line_id) SELECT ? WHERE NOT EXISTS(SELECT 1 FROM tasks WHERE line_id=?)',(line['id'],line['id']))
    order_after_proposal(c,order)
    audit(c,user,'Sąmata',estimate['id'],status)
    return estimate['id']

def audit(c, user, entity, key, action, result='Atlikta', external_actor='Mokėjimų tiekėjas (imitacija)'):
    c.execute('INSERT INTO audit(user_id,external_actor,entity,entity_id,action,happened_at,result) VALUES(?,?,?,?,?,?,?)',
              (user['id'] if user else None,None if user else external_actor,entity,key,action,now(),result))

def date_range(d):
    try:
        start=datetime.strptime(required(d,'from',10),'%Y-%m-%d').date()
        end=datetime.strptime(required(d,'to',10),'%Y-%m-%d').date()
        if start>end:raise ValueError()
        return start.isoformat(),(end+timedelta(days=1)).isoformat()
    except (ValueError,OverflowError):raise RuleError('Patikrinkite laikotarpio pradžią ir pabaigą.')

def reports(c,user,d):
    role(user,'vadovas');start,end=date_range(d)
    metrics=('orders','closed_orders','work_minutes','confirmed_cents','paid_cents')
    daily={}
    queries={
        'orders':('SELECT created_at stamp,1 value FROM orders WHERE created_at>=? AND created_at<?',()),
        'closed_orders':("SELECT closed_at stamp,1 value FROM orders WHERE status='Uždarytas' AND closed_at>=? AND closed_at<?",()),
        'work_minutes':("SELECT finished_at stamp,minutes value FROM tasks WHERE status='Baigtas' AND finished_at>=? AND finished_at<?",()),
        'confirmed_cents':('''SELECT d.decided_at stamp,l.line_total_cents value FROM estimate_lines l
            JOIN estimates e ON e.id=l.estimate_id JOIN estimate_decisions d ON d.estimate_id=e.id
            WHERE e.status='Patvirtinta' AND l.origin_line_id IS NULL AND d.decided_at>=? AND d.decided_at<?''',()),
        'paid_cents':("SELECT resolved_at stamp,amount_cents value FROM payments WHERE status='Sėkmingas' AND resolved_at>=? AND resolved_at<?",())}
    for metric,(query,_) in queries.items():
        for row in c.execute(query,(start,end)):
            bucket=daily.setdefault(row['stamp'][:10],dict.fromkeys(metrics,0))
            bucket[metric]+=row['value']
    return {'from':start,'to':d['to'],'totals':{key:sum(day[key] for day in daily.values()) for key in metrics},
            'daily':[{'date':day,**daily[day]} for day in sorted(daily)]}

def audit_view(c,user,d):
    role(user,'vadovas');start,end=date_range(d)
    where=['a.happened_at>=?','a.happened_at<?'];args=[start,end]
    for field,column in (('entity','a.entity'),('result','a.result')):
        if d.get(field):where.append(column+'=?');args.append(str(d[field])[:100])
    if d.get('user_id'):where.append('a.user_id=?');args.append(integer(d['user_id']))
    if d.get('external_only')=='1':where.append('a.external_actor IS NOT NULL')
    limit=integer(d.get('limit',100),1,200);offset=integer(d.get('offset',0),0)
    condition=' AND '.join(where)
    total=c.execute('SELECT COUNT(*) FROM audit a WHERE '+condition,args).fetchone()[0]
    return {'total':total,'offset':offset,'limit':limit,'audit':rows(c,'''SELECT a.*,u.name FROM audit a
        LEFT JOIN users u ON u.id=a.user_id WHERE '''+condition+' ORDER BY a.happened_at DESC,a.id DESC LIMIT ? OFFSET ?',(*args,limit,offset))}

def user_update(c,user,d):
    role(user,'vadovas');item=one(c,'users',d.get('id'))
    name=required(d,'name',100);username=required(d,'username',40);new_role=required(d,'role',20)
    if new_role not in ('klientas','mechanikas','vadybininkas','vadovas'):raise RuleError('Neteisinga rolė.')
    if (item['role']=='klientas')!=(new_role=='klientas') or d.get('client_id',item['client_id'])!=item['client_id']:
        raise RuleError('Kliento paskyros ryšys nekeičiamas. Darbuotojui ar kitam klientui kurkite atskirą paskyrą.',409)
    if item['id']==user['id'] and new_role!=item['role']:raise RuleError('Savo vadovo rolės pakeisti negalima.',409)
    if new_role!=item['role']:
        employee_available(c,item['id'])
    password=d.get('password','')
    if password and (not isinstance(password,str) or not 10<=len(password)<=200):raise RuleError('Slaptažodis turi būti nuo 10 iki 200 simbolių.')
    c.execute('UPDATE users SET name=?,username=?,role=?,password_hash=? WHERE id=?',
        (name,username,new_role,password_hash(password) if password else item['password_hash'],item['id']))
    audit(c,user,'Naudotojas',item['id'],'Pakeista paskyra; rolė '+item['role']+' → '+new_role+('; pakeistas slaptažodis' if password else ''))
    return {'ok':True,'id':item['id'],'_invalidate_user':item['id'] if password else None}

def employee_available(c,key):
    if c.execute("SELECT 1 FROM tasks WHERE mechanic_id=? AND status IN ('Suplanuotas','Vykdomas','Sustabdytas')",(key,)).fetchone():
        raise RuleError('Naudotojas turi nebaigtų darbų.',409)
    if c.execute("SELECT 1 FROM diagnostic_assignments a JOIN orders o ON o.id=a.order_id WHERE a.mechanic_id=? AND a.ended_at IS NULL AND o.status NOT IN ('Uždarytas','Atšauktas')",(key,)).fetchone():
        raise RuleError('Naudotojas turi aktyvią diagnostiką.',409)

def current_estimate(c, order_id):
    r = c.execute('SELECT * FROM estimates WHERE order_id=? ORDER BY version DESC LIMIT 1', (order_id,)).fetchone()
    return dict(r) if r else None

def order_tasks(c, order_id):
    return rows(c, '''SELECT t.*,l.title,l.estimate_id,e.order_id FROM tasks t
      JOIN estimate_lines l ON l.id=t.line_id JOIN estimates e ON e.id=l.estimate_id
      WHERE e.order_id=? AND e.status='Patvirtinta' ''', (order_id,))

def init_db(seed=True):
    migrate_stage1()
    migrate_stage2()
    migrate_stage3()
    migrate_stage4()
    migrate_stage5a()
    with connect() as c:
        c.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
            if seed: seed_client_account(c)
            return
        for username, name, r in [('vadovas','Serviso vadovas','vadovas'),
                                   ('vadybininkas','Priėmimo vadybininkas','vadybininkas'),
                                   ('mechanikas','Mechanikas A','mechanikas'),
                                   ('mechanikas2','Mechanikas B','mechanikas')]:
            c.execute('INSERT INTO users(username,name,role,password_hash) VALUES(?,?,?,?)',
                      (username,name,r,password_hash('Demo2026!')))
        if seed:
            c.executemany('INSERT INTO clients(name,phone,email) VALUES(?,?,?)',
                          [('Mokomasis klientas A','+37060000001','klientas.a@example.com'),
                           ('Mokomasis klientas B','+37060000002','klientas.b@example.com')])
            c.executemany('INSERT INTO cars(client_id,plate,make,model,year) VALUES(?,?,?,?,?)',
                          [(1,'DEMO01','Toyota','Corolla',2017),(2,'DEMO02','Škoda','Octavia',2019)])
            day = datetime.now().date() + timedelta(days=1)
            c.execute('INSERT INTO appointments(car_id,client_id,start_at,end_at,bay,problem,created_by) VALUES(?,?,?,?,?,?,?)',
                      (1,1,f'{day}T09:00',f'{day}T10:00',1,'Periodinė priežiūra: alyva ir filtras.',2))
            c.execute("UPDATE appointments SET status='Atvyko' WHERE id=1")
            c.execute('INSERT INTO orders(appointment_id,car_id,client_id,problem,mileage,created_at) SELECT a.id,a.car_id,v.client_id,a.problem,?,? FROM appointments a JOIN cars v ON v.id=a.car_id WHERE a.id=1',(146200,now()))
            c.execute('INSERT INTO estimates(order_id,version,total_cents,created_by,created_at) VALUES(?,?,?,?,?)',(1,1,9500,2,now()))
            c.executemany('INSERT INTO estimate_lines(estimate_id,kind,title,quantity_1000,unit_cents,line_total_cents) VALUES(?,?,?,?,?,?)',
                          [(1,'Darbas','Variklio alyvos ir filtro keitimas',1000,3500,3500),
                           (1,'Detalė','Variklio alyva (1 l)',5000,1000,5000),(1,'Detalė','Alyvos filtras',1000,1000,1000)])
            c.execute('INSERT INTO diagnostic_assignments(order_id,mechanic_id,assigned_by,assigned_at) VALUES(1,3,2,?)',(now(),))
            c.execute("INSERT INTO diagnostic_entries(assignment_id,author_id,created_at,result,proposed_works,kind) VALUES(1,3,?,?,?,'Pirminė')",
                      (now(),'Atliktas mokomasis periodinės priežiūros įvertinimas.','Pakeisti variklio alyvą ir filtrą.'))
            seed_client_account(c)

def snapshot(c, user):
    if user['role']=='klientas':
        return client_snapshot(c,user)
    role(user,'vadybininkas','mechanikas','vadovas')
    result = {'user': {k:user[k] for k in ('id','name','role','username')},
              'users':rows(c,'SELECT id,name,role,active'+(',username,client_id' if user['role']=='vadovas' else '')+' FROM users'+('' if user['role']=='vadovas' else " WHERE role<>'klientas'"))}
    if user['role']=='mechanikas':
        result['users']=[u for u in result['users'] if u['id']==user['id']]
        result['tasks']=rows(c,'''SELECT t.*,l.title,e.order_id,o.status order_status,o.handover_at,
          o.problem,v.plate,v.make,v.model FROM tasks t JOIN estimate_lines l ON l.id=t.line_id
          JOIN estimates e ON e.id=l.estimate_id JOIN orders o ON o.id=e.order_id
          JOIN appointments a ON a.id=o.appointment_id JOIN cars v ON v.id=a.car_id
          WHERE t.mechanic_id=? AND e.status='Patvirtinta' ''',(user['id'],))
        result['diagnostic_assignments']=rows(c,'''SELECT d.*,v.plate,o.problem FROM diagnostic_assignments d
            JOIN orders o ON o.id=d.order_id JOIN appointments a ON a.id=o.appointment_id JOIN cars v ON v.id=a.car_id
            WHERE d.mechanic_id=? AND d.ended_at IS NULL AND o.handover_at IS NULL AND o.status NOT IN ('Uždarytas','Atšauktas')''',(user['id'],))
        result['diagnostic_entries']=rows(c,'''SELECT d.* FROM diagnostic_entries d
            LEFT JOIN diagnostic_assignments a ON a.id=d.assignment_id LEFT JOIN tasks t ON t.id=d.task_id
            WHERE (a.mechanic_id=? AND a.ended_at IS NULL) OR t.mechanic_id=?''',(user['id'],user['id']))
        return result
    result.update({
        'clients':rows(c,'SELECT * FROM clients'),
        'cars':rows(c,'''SELECT v.*,k.name client_name FROM cars v JOIN clients k ON k.id=v.client_id'''),
        'appointments':rows(c,'''SELECT a.*,v.plate,k.name client_name FROM appointments a
            JOIN cars v ON v.id=a.car_id JOIN clients k ON k.id=a.client_id ORDER BY a.start_at'''),
        'orders':rows(c,'''SELECT o.*,v.plate,v.make,v.model,k.name client_name
            FROM orders o JOIN appointments a ON a.id=o.appointment_id
            JOIN cars v ON v.id=o.car_id JOIN clients k ON k.id=o.client_id ORDER BY o.id DESC'''),
        'estimates':rows(c,'SELECT * FROM estimates ORDER BY version'),
        'decisions':rows(c,'SELECT * FROM estimate_decisions'),
        'diagnostic_assignments':rows(c,'SELECT * FROM diagnostic_assignments'),
        'diagnostic_entries':rows(c,'''SELECT d.*,COALESCE(a.order_id,e.order_id) order_id FROM diagnostic_entries d
            LEFT JOIN diagnostic_assignments a ON a.id=d.assignment_id LEFT JOIN tasks t ON t.id=d.task_id
            LEFT JOIN estimate_lines l ON l.id=t.line_id LEFT JOIN estimates e ON e.id=l.estimate_id'''),
        'lines':rows(c,'SELECT * FROM estimate_lines'),
        'tasks':rows(c,'''SELECT t.*,l.title,e.order_id FROM tasks t JOIN estimate_lines l ON l.id=t.line_id
            JOIN estimates e ON e.id=l.estimate_id ORDER BY t.id''')
    })
    add_payment_data(c,result)
    if user['role']=='vadovas':
        result['audit']=rows(c,'''SELECT a.*,u.name FROM audit a LEFT JOIN users u ON u.id=a.user_id
            ORDER BY a.id DESC LIMIT 100''')
    return result

def mutate(c, user, action, d):
    """All business writes run in one BEGIN IMMEDIATE transaction in the handler."""
    key = d.get('id')
    if user['role']=='klientas':
        client=client_identity(c,user)
        if action not in ('client_save','car_save','appointment_save','appointment_status','estimate_decide','payment_start','payment_mock_result'):
            raise RuleError('Šiam veiksmui neturite teisių.',403)
        if action=='client_save':
            if key is not None and integer(key)!=client['id']:
                raise RuleError('Įrašas nerastas arba neprieinamas.',404)
            key=client['id']
        if action=='car_save':
            if key: owned(c,user,'cars',key)
            d={**d,'client_id':client['id']}
        if action in ('appointment_save','appointment_status'):
            if key: owned(c,user,'appointments',key)
            if action=='appointment_save': owned(c,user,'cars',d.get('car_id'))
            elif d.get('status')!='Atšauktas':
                raise RuleError('Klientas gali tik atšaukti Patvirtintą vizitą.',403)
    if action=='payment_start': return create_payment(c,user,d)
    if action=='payment_local': return create_payment(c,user,d,local=True)
    if action=='payment_mock_result': return mock_payment_result(c,user,d)
    if action in ('notification_retry','notification_mode'):return notification_mutate(c,user,action,d)
    if action=='user_update':return user_update(c,user,d)
    if action=='client_save':
        role(user,'klientas','vadybininkas','vadovas')
        name, phone = required(d,'name',100), required(d,'phone',20)
        if not re.fullmatch(r'\+?[0-9 ]{7,20}',phone):
            raise RuleError('Patikrinkite telefono numerį.')
        email = str(d.get('email','')).strip()
        if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
            raise RuleError('Patikrinkite el. pašto adresą.')
        if key:
            one(c,'clients',key)
            c.execute('UPDATE clients SET name=?,phone=?,email=? WHERE id=?',(name,phone,email,key))
        else:
            key=c.execute('INSERT INTO clients(name,phone,email) VALUES(?,?,?)',(name,phone,email)).lastrowid
        audit(c,user,'Klientas',key,'Išsaugota kortelė')
    elif action=='client_archive':
        adviser(user); one(c,'clients',key)
        active=c.execute('''SELECT 1 FROM appointments a JOIN cars v ON v.id=a.car_id
            LEFT JOIN orders o ON o.appointment_id=a.id WHERE v.client_id=? AND
            (a.status='Patvirtintas' OR o.status NOT IN ('Uždarytas','Atšauktas'))''',(key,)).fetchone()
        if active: raise RuleError('Klientas turi nebaigtų vizitų arba užsakymų.',409)
        c.execute('UPDATE clients SET active=0 WHERE id=?',(key,)); audit(c,user,'Klientas',key,'Archyvuota')
    elif action=='car_save':
        role(user,'klientas','vadybininkas','vadovas'); client=one(c,'clients',d.get('client_id'))
        if not client['active']: raise RuleError('Klientas archyvuotas.')
        plate=required(d,'plate',12).replace(' ','').upper()
        make,model=required(d,'make',50),required(d,'model',50)
        year=integer(d.get('year'),1950,datetime.now().year+1)
        if key:
            old=one(c,'cars',key)
            if old['client_id']!=client['id']:
                adviser(user)
                if c.execute("""SELECT 1 FROM appointments a LEFT JOIN orders o ON o.appointment_id=a.id
                    WHERE a.car_id=? AND (a.status='Patvirtintas' OR
                    (a.status='Atvyko' AND o.id IS NULL))""",(key,)).fetchone() or c.execute(
                    "SELECT 1 FROM orders WHERE car_id=? AND status NOT IN ('Uždarytas','Atšauktas')",(key,)).fetchone():
                    raise RuleError('Savininką galima keisti tik užbaigus aktyvius vizitus ir užsakymus.',409)
                audit(c,user,'Automobilis',key,f"Pakeistas savininkas: {old['client_id']} → {client['id']}")
            c.execute('UPDATE cars SET client_id=?,plate=?,make=?,model=?,year=? WHERE id=?',(client['id'],plate,make,model,year,key))
        else:
            key=c.execute('INSERT INTO cars(client_id,plate,make,model,year) VALUES(?,?,?,?,?)',
                          (client['id'],plate,make,model,year)).lastrowid
        audit(c,user,'Automobilis',key,'Išsaugota kortelė')
    elif action=='appointment_save':
        role(user,'klientas','vadybininkas','vadovas'); car=one(c,'cars',d.get('car_id'))
        if not one(c,'clients',car['client_id'])['active']: raise RuleError('Klientas archyvuotas.')
        start,end=required(d,'start_at',20),required(d,'end_at',20)
        try: a,b=datetime.fromisoformat(start),datetime.fromisoformat(end)
        except ValueError: raise RuleError('Neteisinga vizito data.')
        if a.tzinfo or b.tzinfo or a.second or b.second or a.microsecond or b.microsecond:
            raise RuleError('Vizito laiką nurodykite minučių tikslumu, be laiko juostos.')
        if a.date()!=b.date() or a>=b or a.hour<8 or b.hour>18 or (b.hour==18 and b.minute>0):
            raise RuleError('Vizitas turi vykti tą pačią dieną tarp 08:00 ir 18:00; pabaiga vėlesnė už pradžią.')
        start,end=a.isoformat(timespec='minutes'),b.isoformat(timespec='minutes')
        bay=integer(d.get('bay'),1,2)
        if key and one(c,'appointments',key)['status']!='Patvirtintas': raise RuleError('Galima keisti tik Patvirtintą vizitą.',409)
        conflict=slot_conflict(c,car['id'],bay,start,end,key or 0)
        if conflict: raise RuleError('Šiuo laiku darbo vieta arba automobilis jau užregistruotas.',409)
        values=(car['id'],car['client_id'],start,end,bay,required(d,'problem'))
        if key:
            c.execute('UPDATE appointments SET car_id=?,client_id=?,start_at=?,end_at=?,bay=?,problem=? WHERE id=?',(*values,key))
        else:
            key=c.execute('INSERT INTO appointments(car_id,client_id,start_at,end_at,bay,problem,created_by) VALUES(?,?,?,?,?,?,?)',(*values,user['id'])).lastrowid
            queue_notification(c,user,f'appointment:{key}','Patvirtintas vizitas',f'Vizitas patvirtintas: {start}, darbo vieta {bay}.',appointment_id=key)
        audit(c,user,'Vizitas',key,'Išsaugotas vizitas')
    elif action=='appointment_status':
        role(user,'klientas','vadybininkas','vadovas'); item=one(c,'appointments',key); status=required(d,'status')
        if item['status']!='Patvirtintas' or status not in ('Atšauktas','Neatvyko','Atvyko'):
            raise RuleError('Toks vizito būsenos pakeitimas negalimas.',409)
        c.execute('UPDATE appointments SET status=? WHERE id=?',(status,key))
        if status=='Atvyko':
            oid=c.execute('''INSERT INTO orders(appointment_id,car_id,client_id,problem,mileage,created_at)
                SELECT a.id,a.car_id,a.client_id,a.problem,?,? FROM appointments a WHERE a.id=?''',
                (integer(d.get('mileage'),0),now(),key)).lastrowid
            audit(c,user,'Užsakymas',oid,'Sukurtas priėmus automobilį')
        audit(c,user,'Vizitas',key,status)
    elif action in ('diagnostic_assign','diagnostic_add'):
        key=diagnostic_mutate(c,user,action,d)
    elif action=='estimate_save':
        key=save_estimate(c,user,d)
    elif action=='estimate_decide':
        key=decide_estimate(c,user,d)
    elif action=='estimate_submit':
        adviser(user);estimate=one(c,'estimates',key);order=open_order(c,estimate['order_id'])
        if estimate['status']!='Rengiama': raise RuleError('Pateikti galima tik rengiamą versiją.',409)
        c.execute("UPDATE estimates SET status='Pateikta',submitted_at=? WHERE id=?",(now(),key))
        order_after_proposal(c,order,submitted=True)
        queue_notification(c,user,f'estimate:{key}','Pradinė sąmata' if estimate['version']==1 else 'Papildyta sąmata',
            f'Užsakymui U-{order["id"]} pateikta sąmatos {estimate["version"]} versija. Peržiūrėkite ir pateikite sprendimą savitarnoje.',order_id=order['id'],estimate_id=estimate['id'])
        audit(c,user,'Sąmata',key,'Pateikta klientui')
    elif action=='task_assign':
        adviser(user); task=one(c,'tasks',key); mechanic=one(c,'users',d.get('mechanic_id'))
        if task['status']!='Suplanuotas' or mechanic['role']!='mechanikas' or not mechanic['active']:
            raise RuleError('Galima paskirti tik suplanuotą darbą aktyviam mechanikui.',409)
        line=one(c,'estimate_lines',task['line_id']);estimate=one(c,'estimates',line['estimate_id'])
        open_order(c,estimate['order_id'])
        if estimate['status']!='Patvirtinta': raise RuleError('Darbo apimtis nepatvirtinta.',409)
        c.execute('UPDATE tasks SET mechanic_id=?,assigned_at=? WHERE id=?',(mechanic['id'],now(),key))
        audit(c,user,'Darbas',key,f"Paskirtas mechanikui {mechanic['id']}")
    elif action=='task_status':
        role(user, 'mechanikas')
        task=one(c,'tasks',key)
        if user['role']=='mechanikas' and task['mechanic_id']!=user['id']: raise RuleError('Darbas paskirtas kitam mechanikui.',403)
        line=one(c,'estimate_lines',task['line_id']); estimate=one(c,'estimates',line['estimate_id']); order=open_order(c,estimate['order_id'])
        if estimate['status']!='Patvirtinta' or order['status'] in ('Uždarytas','Atšauktas'):
            raise RuleError('Darbui nėra galiojančio patvirtinimo.',409)
        if not task['mechanic_id']: raise RuleError('Pirmiausia paskirkite mechaniką.',409)
        status=required(d,'status')
        transitions={'Suplanuotas':['Vykdomas'],'Vykdomas':['Sustabdytas','Baigtas'],'Sustabdytas':['Vykdomas']}
        if status not in transitions.get(task['status'],[]): raise RuleError('Toks darbo būsenos pakeitimas negalimas.',409)
        note=str(d.get('note','')).strip()[:500]
        minutes=integer(d.get('minutes',task['minutes']),0,100000)
        if status in ('Sustabdytas','Baigtas') and not note: raise RuleError('Įrašykite sustabdymo priežastį arba atliktų darbų pastabą.')
        if status=='Baigtas' and 'minutes' not in d: raise RuleError('Įrašykite faktinę trukmę minutėmis.')
        c.execute('UPDATE tasks SET status=?,minutes=?,note=?,started_at=COALESCE(started_at,?),finished_at=? WHERE id=?',
                  (status,minutes,note,now(),now() if status=='Baigtas' else None,key))
        c.execute("UPDATE orders SET status='Vykdomas' WHERE id=?",(order['id'],))
        audit(c,user,'Darbas',key,status)
    elif action in ('order_ready','order_handover','order_close'):
        adviser(user); order=one(c,'orders',key)
        completion_scope(c,key)
        if action=='order_ready':
            open_order(c,key);status='Paruoštas'
            c.execute('UPDATE orders SET status=? WHERE id=?',(status,key))
            version=current_estimate(c,key)
            queue_notification(c,user,f'ready:{key}:{version["id"]}','Automobilis paruoštas',f'Užsakymo U-{key} automobilis paruoštas atsiimti.',order_id=key)
        else:
            if order['status']!='Paruoštas': raise RuleError('Pirmiausia pažymėkite automobilį paruoštu.',409)
            if payment_summary(c,key)['balance_cents']!=0:
                message='Prieš perduodant automobilį ir uždarant užsakymą reikia padengti visą likutį.'
                if action=='order_handover':
                    balance=payment_summary(c,key)
                    queue_notification(c,user,f'collection:{key}:{balance["confirmed_total_cents"]}:{balance["paid_cents"]}',
                        'Likutis atsiimant',f'Atsiimant U-{key} automobilį liko sumokėti {balance["balance_cents"]//100},{balance["balance_cents"]%100:02d} Eur.',order_id=key)
                    audit(c,user,'Užsakymas',key,'Atsiėmimo metu nustatytas neapmokėtas likutis; perdavimas neįvyko',result='Atmesta')
                    return {'ok':False,'error':message,'_http_status':409}
                raise RuleError(message,409)
            if action=='order_handover':
                if order['handover_at']: raise RuleError('Automobilio perdavimas jau užregistruotas.',409)
                status='Paruoštas'
                c.execute('UPDATE orders SET handover_at=? WHERE id=?',(now(),key))
                audit(c,user,'Užsakymas',key,'Automobilis perduotas klientui')
                return {'ok':True,'id':key}
            if not order['handover_at']: raise RuleError('Pirmiausia užregistruokite faktinį automobilio perdavimą.',409)
            status='Uždarytas';note=required(d,'note')
            c.execute('UPDATE orders SET status=?,closed_at=?,closed_by=?,closing_note=? WHERE id=?',
                      (status,now(),user['id'],note,key))
        if status=='Uždarytas':
            c.execute('UPDATE diagnostic_assignments SET ended_at=? WHERE order_id=? AND ended_at IS NULL',(now(),key))
        audit(c,user,'Užsakymas',key,status)
    elif action=='user_save':
        role(user,'vadovas'); username=required(d,'username',40); name=required(d,'name',100); r=required(d,'role')
        if r not in ('klientas','vadybininkas','mechanikas','vadovas'): raise RuleError('Neteisinga rolė.')
        cid=one(c,'clients',d.get('client_id'))['id'] if r=='klientas' else None
        password=required(d,'password',200)
        if len(password)<10: raise RuleError('Naujas slaptažodis turi būti bent 10 simbolių.')
        key=c.execute('INSERT INTO users(username,name,role,password_hash,client_id) VALUES(?,?,?,?,?)',(username,name,r,password_hash(password),cid)).lastrowid
        audit(c,user,'Naudotojas',key,'Sukurta paskyra')
    elif action=='user_disable':
        role(user,'vadovas'); item=one(c,'users',key)
        if item['id']==user['id']: raise RuleError('Savo paskyros išjungti negalima.')
        employee_available(c,key)
        c.execute('UPDATE users SET active=0 WHERE id=?',(key,)); audit(c,user,'Naudotojas',key,'Išjungta paskyra')
    else:
        raise RuleError('Nežinomas veiksmas.',404)
    return {'ok':True,'id':key}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, value, status=200, cookie=None, mime='application/json; charset=utf-8'):
        data=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers(); self.wfile.write(data)

    def session(self, c):
        cookie=SimpleCookie(self.headers.get('Cookie','')); token=cookie.get('sid')
        with SESSION_LOCK:
            session=SESSIONS.get(token.value if token else '')
            if not session or session['expires']<time.time(): raise RuleError('Prisijunkite iš naujo.',401)
            session['expires']=time.time()+SESSION_TTL
            user=one(c,'users',session['user_id'])
            if not user['active']: raise RuleError('Paskyra išjungta.',401)
            if user['role']=='klientas': client_identity(c,user)
            return user,session

    def do_GET(self):
        path=urlparse(self.path).path
        try:
            if path in ('/api/state','/api/free_slots','/api/client/car','/api/client/appointment','/api/client/order','/api/client/estimate','/api/payments','/api/notifications','/api/reports','/api/audit'):
                with connect() as c:
                    c.execute('BEGIN')
                    user,session=self.session(c)
                    params={k:v[0] for k,v in parse_qs(urlparse(self.path).query).items()}
                    if path=='/api/notifications':
                        self.send(notification_admin(c,user))
                    elif path=='/api/reports':
                        self.send(reports(c,user,params))
                    elif path=='/api/audit':
                        self.send(audit_view(c,user,params))
                    elif path=='/api/payments':
                        self.send(read_payments(c,user,params.get('order_id')))
                    elif path=='/api/state':
                        self.send({**snapshot(c,user),'csrf':session['csrf']})
                    elif path=='/api/client/estimate':
                        self.send(client_estimate(c,user,params.get('id')))
                    elif path=='/api/free_slots':
                        self.send(free_slots(c,user,params))
                    else:
                        table={'/api/client/car':'cars','/api/client/appointment':'appointments','/api/client/order':'orders'}[path]
                        owned(c,user,table,params.get('id'))
                        self.send(next(x for x in client_snapshot(c,user)[table] if x['id']==integer(params.get('id'))))
            else:
                files={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
                if path not in files: raise RuleError('Puslapis nerastas.',404)
                file=ROOT/'static'/files[path]
                mime={'html':'text/html','js':'text/javascript','css':'text/css'}[file.suffix[1:]]
                self.send(file.read_bytes(),mime=mime+'; charset=utf-8')
        except RuleError as e: self.send({'error':e.message},e.status)

    def do_POST(self):
        user=None;action='';data={}
        try:
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise RuleError('Tikėtasi JSON duomenų.',415)
            origin=self.headers.get('Origin')
            allowed_origins=(PUBLIC_ORIGIN,) if PUBLIC_ORIGIN else (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}')
            if origin and origin not in allowed_origins:
                raise RuleError('Neleistina užklausos kilmė.',403)
            size=integer(self.headers.get('Content-Length'),1,100000)
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict): raise RuleError('Neteisingi duomenys.')
            action=urlparse(self.path).path.removeprefix('/api/')
            with connect() as c:
                if action=='payment_result':
                    # Technical interface authenticates the provider, not a human session.
                    c.execute('BEGIN IMMEDIATE')
                    result=process_payment_result(c,data)
                    c.commit(); dispatch_after_commit(); self.send(result,result.pop('_http_status',200)); return
                if action=='login':
                    r=c.execute('SELECT * FROM users WHERE username=? AND active=1',(str(data.get('username','')),)).fetchone()
                    if not r or not password_ok(str(data.get('password','')),r['password_hash']): raise RuleError('Neteisingas vardas arba slaptažodis.',401)
                    if r['role']=='klientas': client_identity(c,dict(r))
                    token=secrets.token_urlsafe(32)
                    with SESSION_LOCK:
                        for expired in [k for k,v in SESSIONS.items() if v['expires']<time.time()]: del SESSIONS[expired]
                        SESSIONS[token]={'user_id':r['id'],'csrf':secrets.token_hex(24),'expires':time.time()+SESSION_TTL}
                    self.send({'ok':True},cookie=session_cookie(token))
                    return
                user,session=self.session(c)
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']): raise RuleError('Neteisingas saugos kodas. Atnaujinkite puslapį.',403)
                if action=='logout':
                    cookie=SimpleCookie(self.headers.get('Cookie',''))
                    with SESSION_LOCK: SESSIONS.pop(cookie['sid'].value,None)
                    self.send({'ok':True},cookie=session_cookie('',expired=True)); return
                c.execute('BEGIN IMMEDIATE')
                user,session=self.session(c)  # Recheck active status and role after acquiring the write transaction.
                result=mutate(c,user,action,data)
                c.commit()
                mode=result.pop('_notification_mode',None)
                if mode:notification_provider.configure(mode)
                invalidated=result.pop('_invalidate_user',None)
                if invalidated:
                    with SESSION_LOCK:
                        for sid in [k for k,v in SESSIONS.items() if v['user_id']==invalidated]:del SESSIONS[sid]
                dispatch_after_commit()
                self.send(result,result.pop('_http_status',200))
        except RuleError as e:
            if user and action in ('user_update','user_save','user_disable','notification_retry','notification_mode','order_handover','order_close'):
                with connect() as log:
                    try:key=integer(data.get('id',0),0)
                    except RuleError:key=0
                    audit(log,user,'Atmestas veiksmas',key,action,result='Atmesta')
            self.send({'error':e.message},e.status)
        except sqlite3.IntegrityError: self.send({'error':'Toks unikalus įrašas jau yra arba susiję duomenys netinkami.'},409)
        except (ValueError,TypeError,KeyError): self.send({'error':'Neteisingi arba nepilni duomenys.'},400)
        except Exception:
            import traceback
            traceback.print_exc()
            self.send({'error':'Vidinė klaida. Pakeitimai neišsaugoti.'},500)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Autoserviso mokomoji sistema')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--db',type=Path,default=DB)
    args=parser.parse_args(); DB=args.db
    init_db()
    dispatch_after_commit()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Atidarykite http://127.0.0.1:{args.port}\nDemonstracinis slaptažodis: Demo2026!',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()
