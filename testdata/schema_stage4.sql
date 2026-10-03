PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('klientas','vadybininkas','mechanikas','vadovas')),
 password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 client_id INTEGER UNIQUE REFERENCES clients(id),
 CHECK((role='klientas' AND client_id IS NOT NULL) OR (role<>'klientas' AND client_id IS NULL))
);
CREATE TABLE IF NOT EXISTS clients (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL,
 email TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS cars (
 id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
 plate TEXT NOT NULL UNIQUE, make TEXT NOT NULL, model TEXT NOT NULL, year INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
 id INTEGER PRIMARY KEY, car_id INTEGER NOT NULL REFERENCES cars(id),
 start_at TEXT NOT NULL, end_at TEXT NOT NULL, bay INTEGER NOT NULL CHECK(bay IN (1,2)),
 problem TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Patvirtintas'
 CHECK(status IN ('Patvirtintas','Atvyko','Atšauktas','Neatvyko')),
 created_by INTEGER NOT NULL REFERENCES users(id), UNIQUE(id,car_id)
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointments(id),
 car_id INTEGER NOT NULL REFERENCES cars(id), client_id INTEGER NOT NULL REFERENCES clients(id),
 problem TEXT NOT NULL,
 mileage INTEGER NOT NULL CHECK(mileage >= 0), status TEXT NOT NULL DEFAULT 'Naujas'
 CHECK(status IN ('Naujas','Derinamas','Patvirtintas','Vykdomas','Paruoštas','Uždarytas','Atšauktas')),
 created_at TEXT NOT NULL, handover_at TEXT, closed_at TEXT,
 closed_by INTEGER REFERENCES users(id), closing_note TEXT NOT NULL DEFAULT '',
 FOREIGN KEY(appointment_id,car_id) REFERENCES appointments(id,car_id)
);
CREATE TABLE IF NOT EXISTS estimates (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
 version INTEGER NOT NULL CHECK(version > 0), status TEXT NOT NULL DEFAULT 'Rengiama'
 CHECK(status IN ('Rengiama','Pateikta','Patvirtinta','Atmesta')),
 total_cents INTEGER NOT NULL DEFAULT 0 CHECK(total_cents >= 0),
 created_by INTEGER NOT NULL REFERENCES users(id), submitted_at TEXT,
 created_at TEXT NOT NULL, UNIQUE(order_id,version)
);
CREATE TABLE IF NOT EXISTS estimate_lines (
 id INTEGER PRIMARY KEY, estimate_id INTEGER NOT NULL REFERENCES estimates(id),
 kind TEXT NOT NULL CHECK(kind IN ('Darbas','Detalė')), title TEXT NOT NULL,
 origin_line_id INTEGER REFERENCES estimate_lines(id),
 quantity_1000 INTEGER NOT NULL CHECK(typeof(quantity_1000)='integer' AND quantity_1000>0),
 unit_cents INTEGER NOT NULL CHECK(typeof(unit_cents)='integer' AND unit_cents>=0),
 line_total_cents INTEGER NOT NULL CHECK(typeof(line_total_cents)='integer' AND
 line_total_cents=(quantity_1000*unit_cents+500)/1000)
);
CREATE TABLE IF NOT EXISTS estimate_decisions (
 id INTEGER PRIMARY KEY, estimate_id INTEGER NOT NULL UNIQUE REFERENCES estimates(id),
 client_id INTEGER NOT NULL REFERENCES clients(id), user_id INTEGER NOT NULL REFERENCES users(id),
 decision TEXT NOT NULL CHECK(decision IN ('Patvirtinta','Atmesta')),
 decided_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tasks (
 id INTEGER PRIMARY KEY, line_id INTEGER NOT NULL UNIQUE REFERENCES estimate_lines(id),
 mechanic_id INTEGER REFERENCES users(id), status TEXT NOT NULL DEFAULT 'Suplanuotas'
 CHECK(status IN ('Suplanuotas','Vykdomas','Sustabdytas','Baigtas')),
 assigned_at TEXT, started_at TEXT, finished_at TEXT,
 minutes INTEGER NOT NULL DEFAULT 0 CHECK(minutes >= 0), note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS diagnostic_assignments (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
 mechanic_id INTEGER NOT NULL REFERENCES users(id), assigned_by INTEGER NOT NULL REFERENCES users(id),
 assigned_at TEXT NOT NULL, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS diagnostic_entries (
 id INTEGER PRIMARY KEY, assignment_id INTEGER REFERENCES diagnostic_assignments(id),
 task_id INTEGER REFERENCES tasks(id), author_id INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL, result TEXT NOT NULL, proposed_works TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('Pirminė','Papildoma')),
 CHECK((assignment_id IS NOT NULL AND task_id IS NULL AND kind='Pirminė') OR
       (assignment_id IS NULL AND task_id IS NOT NULL AND kind='Papildoma'))
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), entity TEXT NOT NULL,
 entity_id INTEGER NOT NULL, action TEXT NOT NULL, happened_at TEXT NOT NULL,
 external_actor TEXT, result TEXT NOT NULL DEFAULT 'Atlikta'
);
CREATE TABLE IF NOT EXISTS payments (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
 operation_id TEXT UNIQUE, request_key TEXT NOT NULL UNIQUE,
 amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents>0),
 status TEXT NOT NULL CHECK(status IN ('Laukia','Sėkmingas','Nesėkmingas')),
 method TEXT NOT NULL CHECK(method IN ('Internetu','Vietoje')),
 created_at TEXT NOT NULL, resolved_at TEXT, recorded_by INTEGER REFERENCES users(id),
 technical_code TEXT NOT NULL DEFAULT '',
 CHECK((method='Internetu' AND operation_id IS NOT NULL) OR
       (method='Vietoje' AND operation_id IS NULL AND status='Sėkmingas' AND recorded_by IS NOT NULL)),
 CHECK((status='Laukia' AND resolved_at IS NULL) OR (status<>'Laukia' AND resolved_at IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS notifications (
 id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
 appointment_id INTEGER REFERENCES appointments(id), order_id INTEGER REFERENCES orders(id),
 estimate_id INTEGER REFERENCES estimates(id), payment_id INTEGER REFERENCES payments(id),
 event_key TEXT NOT NULL, channel TEXT NOT NULL CHECK(channel IN ('SMS','El. paštas')),
 type TEXT NOT NULL, recipient TEXT NOT NULL, content TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Sukurtas' CHECK(status IN ('Sukurtas','Perduotas tiekėjui','Siuntimo klaida')),
 created_at TEXT NOT NULL, UNIQUE(event_key,channel),
 CHECK(appointment_id IS NOT NULL OR order_id IS NOT NULL OR estimate_id IS NOT NULL OR payment_id IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS notification_attempts (
 id INTEGER PRIMARY KEY, notification_id INTEGER NOT NULL REFERENCES notifications(id),
 attempt_no INTEGER NOT NULL CHECK(attempt_no>0), attempted_at TEXT NOT NULL,
 provider_id TEXT, result TEXT NOT NULL CHECK(result IN ('Perduotas tiekėjui','Siuntimo klaida')),
 error_code TEXT NOT NULL DEFAULT '', UNIQUE(notification_id,attempt_no)
);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status,id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit(happened_at,id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_appointment_identity ON appointments(id,car_id);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id,status);
CREATE INDEX IF NOT EXISTS idx_appointments_slot ON appointments(bay,start_at,end_at,status);
CREATE INDEX IF NOT EXISTS idx_estimates_order ON estimates(order_id,version);
CREATE INDEX IF NOT EXISTS idx_tasks_mechanic ON tasks(mechanic_id,status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_active_diagnostic ON diagnostic_assignments(order_id) WHERE ended_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_open_estimate ON estimates(order_id) WHERE status IN ('Rengiama','Pateikta');
CREATE UNIQUE INDEX IF NOT EXISTS idx_line_origin ON estimate_lines(estimate_id,COALESCE(origin_line_id,id));
CREATE TRIGGER IF NOT EXISTS estimate_insert_guard BEFORE INSERT ON estimates
WHEN NEW.status<>'Rengiama' OR NEW.submitted_at IS NOT NULL OR EXISTS(SELECT 1 FROM estimates WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'Nauja sąmata turi būti rengiama; istorija neperrašoma'); END;
CREATE TRIGGER IF NOT EXISTS estimate_identity_lock BEFORE UPDATE ON estimates
WHEN NEW.id<>OLD.id OR NEW.order_id<>OLD.order_id OR NEW.version<>OLD.version OR
 NEW.created_by<>OLD.created_by OR NEW.created_at<>OLD.created_at OR
 (OLD.status<>'Rengiama' AND (NEW.total_cents<>OLD.total_cents OR NEW.submitted_at IS NOT OLD.submitted_at))
BEGIN SELECT RAISE(ABORT,'Sąmatos turinys nekintamas'); END;
CREATE TRIGGER IF NOT EXISTS estimate_state_guard BEFORE UPDATE OF status ON estimates
WHEN NEW.status<>OLD.status AND NOT (
 (OLD.status='Rengiama' AND NEW.status='Pateikta' AND NEW.submitted_at IS NOT NULL AND
  EXISTS(SELECT 1 FROM estimate_lines WHERE estimate_id=OLD.id) AND
  NEW.total_cents=(SELECT SUM(line_total_cents) FROM estimate_lines WHERE estimate_id=OLD.id)) OR
 (OLD.status='Pateikta' AND EXISTS(SELECT 1 FROM estimate_decisions WHERE estimate_id=OLD.id AND decision=NEW.status)))
BEGIN SELECT RAISE(ABORT,'Neleistinas sąmatos perėjimas'); END;
CREATE TRIGGER IF NOT EXISTS estimate_delete_guard BEFORE DELETE ON estimates
BEGIN SELECT RAISE(ABORT,'Sąmatos istorija nenaikinama'); END;
CREATE TRIGGER IF NOT EXISTS line_insert_guard BEFORE INSERT ON estimate_lines
WHEN (SELECT status FROM estimates WHERE id=NEW.estimate_id)<>'Rengiama'
BEGIN SELECT RAISE(ABORT,'Pateiktos versijos eilutės nekintamos'); END;
CREATE TRIGGER IF NOT EXISTS line_update_guard BEFORE UPDATE ON estimate_lines
WHEN (SELECT status FROM estimates WHERE id=OLD.estimate_id)<>'Rengiama' OR
 (SELECT status FROM estimates WHERE id=NEW.estimate_id)<>'Rengiama'
BEGIN SELECT RAISE(ABORT,'Pateiktos versijos eilutės nekintamos'); END;
CREATE TRIGGER IF NOT EXISTS line_delete_guard BEFORE DELETE ON estimate_lines
WHEN (SELECT status FROM estimates WHERE id=OLD.estimate_id)<>'Rengiama'
BEGIN SELECT RAISE(ABORT,'Pateiktos versijos eilutės nekintamos'); END;
CREATE TRIGGER IF NOT EXISTS origin_insert_guard BEFORE INSERT ON estimate_lines
WHEN NEW.origin_line_id IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM estimate_lines p JOIN estimates e ON e.id=p.estimate_id
 JOIN estimates n ON n.id=NEW.estimate_id WHERE p.id=NEW.origin_line_id AND p.origin_line_id IS NULL
 AND e.order_id=n.order_id AND e.status='Patvirtinta' AND p.kind=NEW.kind AND p.title=NEW.title
 AND p.quantity_1000=NEW.quantity_1000 AND p.unit_cents=NEW.unit_cents AND p.line_total_cents=NEW.line_total_cents)
BEGIN SELECT RAISE(ABORT,'Neteisinga pirminė eilutė'); END;
CREATE TRIGGER IF NOT EXISTS origin_update_guard BEFORE UPDATE ON estimate_lines
WHEN NEW.origin_line_id IS NOT OLD.origin_line_id OR (OLD.origin_line_id IS NOT NULL AND
 (NEW.estimate_id<>OLD.estimate_id OR NEW.kind<>OLD.kind OR NEW.title<>OLD.title OR
  NEW.quantity_1000<>OLD.quantity_1000 OR NEW.unit_cents<>OLD.unit_cents OR NEW.line_total_cents<>OLD.line_total_cents))
BEGIN SELECT RAISE(ABORT,'Perkelta eilutė nekintama'); END;
CREATE TRIGGER IF NOT EXISTS decision_insert_guard BEFORE INSERT ON estimate_decisions
WHEN NOT EXISTS(SELECT 1 FROM estimates e JOIN orders o ON o.id=e.order_id
 JOIN appointments a ON a.id=o.appointment_id JOIN cars v ON v.id=a.car_id
 JOIN users u ON u.id=NEW.user_id WHERE e.id=NEW.estimate_id AND e.status='Pateikta'
 AND o.status NOT IN ('Uždarytas','Atšauktas') AND u.role='klientas' AND u.active=1
 AND u.client_id=o.client_id AND o.client_id=NEW.client_id)
BEGIN SELECT RAISE(ABORT,'Neleistinas kliento sprendimas'); END;
CREATE TRIGGER IF NOT EXISTS decision_apply AFTER INSERT ON estimate_decisions
BEGIN UPDATE estimates SET status=NEW.decision WHERE id=NEW.estimate_id; END;
CREATE TRIGGER IF NOT EXISTS decision_update_guard BEFORE UPDATE ON estimate_decisions
BEGIN SELECT RAISE(ABORT,'Sprendimas nekintamas'); END;
CREATE TRIGGER IF NOT EXISTS decision_delete_guard BEFORE DELETE ON estimate_decisions
BEGIN SELECT RAISE(ABORT,'Sprendimas nenaikinamas'); END;
CREATE TRIGGER IF NOT EXISTS task_origin_guard BEFORE INSERT ON tasks
WHEN NOT EXISTS(SELECT 1 FROM estimate_lines l JOIN estimates e ON e.id=l.estimate_id
 WHERE l.id=NEW.line_id AND l.origin_line_id IS NULL AND l.kind='Darbas' AND e.status='Patvirtinta')
BEGIN SELECT RAISE(ABORT,'Darbui reikia patvirtintos pirminės eilutės'); END;
CREATE TRIGGER IF NOT EXISTS task_line_lock BEFORE UPDATE OF line_id ON tasks WHEN NEW.line_id<>OLD.line_id
BEGIN SELECT RAISE(ABORT,'Darbo kilmė nekintama'); END;
CREATE TRIGGER IF NOT EXISTS diagnostic_entry_update_guard BEFORE UPDATE ON diagnostic_entries
BEGIN SELECT RAISE(ABORT,'Diagnostikos taisymas yra naujas įrašas'); END;
CREATE TRIGGER IF NOT EXISTS diagnostic_entry_delete_guard BEFORE DELETE ON diagnostic_entries
BEGIN SELECT RAISE(ABORT,'Diagnostikos istorija nenaikinama'); END;
CREATE TRIGGER IF NOT EXISTS payment_insert_guard BEFORE INSERT ON payments
WHEN EXISTS(SELECT 1 FROM payments WHERE id=NEW.id OR request_key=NEW.request_key OR operation_id=NEW.operation_id)
BEGIN SELECT RAISE(ABORT,'Mokėjimo keitimas per INSERT draudžiamas'); END;
CREATE TRIGGER IF NOT EXISTS payment_update_guard BEFORE UPDATE ON payments
WHEN NEW.id<>OLD.id OR NEW.order_id<>OLD.order_id OR NEW.operation_id IS NOT OLD.operation_id
 OR NEW.request_key<>OLD.request_key OR NEW.amount_cents<>OLD.amount_cents OR NEW.method<>OLD.method
 OR NEW.created_at<>OLD.created_at OR NEW.recorded_by IS NOT OLD.recorded_by
 OR OLD.status<>'Laukia'
BEGIN SELECT RAISE(ABORT,'Mokėjimo tapatybė ir galutinis rezultatas nekintami'); END;
CREATE TRIGGER IF NOT EXISTS payment_delete_guard BEFORE DELETE ON payments
BEGIN SELECT RAISE(ABORT,'Mokėjimų istorija nenaikinama'); END;
CREATE TRIGGER IF NOT EXISTS audit_actor_guard BEFORE INSERT ON audit
WHEN (NEW.user_id IS NULL AND NEW.external_actor IS NULL) OR
     (NEW.user_id IS NOT NULL AND NEW.external_actor IS NOT NULL) OR EXISTS(SELECT 1 FROM audit WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'Žurnalo veikėjas privalomas ir vienareikšmis'); END;
CREATE TRIGGER IF NOT EXISTS audit_update_guard BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT,'Žurnalas tik papildomas'); END;
CREATE TRIGGER IF NOT EXISTS audit_delete_guard BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT,'Žurnalas tik papildomas'); END;
CREATE TRIGGER IF NOT EXISTS order_identity_lock BEFORE UPDATE ON orders
WHEN NEW.id<>OLD.id OR NEW.appointment_id<>OLD.appointment_id OR NEW.car_id<>OLD.car_id
 OR NEW.client_id<>OLD.client_id OR NEW.problem<>OLD.problem
BEGIN SELECT RAISE(ABORT,'Užsakymo priėmimo kontekstas nekintamas'); END;
CREATE TRIGGER IF NOT EXISTS notification_insert_guard BEFORE INSERT ON notifications
WHEN NEW.status<>'Sukurtas' OR EXISTS(SELECT 1 FROM notifications WHERE id=NEW.id OR (event_key=NEW.event_key AND channel=NEW.channel))
 OR (NEW.order_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM orders WHERE id=NEW.order_id AND client_id=NEW.client_id))
 OR (NEW.appointment_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM appointments a JOIN cars v ON v.id=a.car_id
     WHERE a.id=NEW.appointment_id AND v.client_id=NEW.client_id))
 OR (NEW.estimate_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM estimates e JOIN orders o ON o.id=e.order_id
     WHERE e.id=NEW.estimate_id AND o.client_id=NEW.client_id AND (NEW.order_id IS NULL OR o.id=NEW.order_id)))
 OR (NEW.payment_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM payments p JOIN orders o ON o.id=p.order_id
     WHERE p.id=NEW.payment_id AND o.client_id=NEW.client_id AND (NEW.order_id IS NULL OR o.id=NEW.order_id)))
 OR (NEW.order_id IS NOT NULL AND NEW.appointment_id IS NOT NULL AND NOT EXISTS(
     SELECT 1 FROM orders WHERE id=NEW.order_id AND appointment_id=NEW.appointment_id))
BEGIN SELECT RAISE(ABORT,'Pranešimo kontekstas neatitinka kliento arba įvykis jau yra'); END;
CREATE TRIGGER IF NOT EXISTS notification_update_guard BEFORE UPDATE ON notifications
WHEN NEW.id<>OLD.id OR NEW.client_id<>OLD.client_id OR NEW.appointment_id IS NOT OLD.appointment_id
 OR NEW.order_id IS NOT OLD.order_id OR NEW.estimate_id IS NOT OLD.estimate_id OR NEW.payment_id IS NOT OLD.payment_id
 OR NEW.event_key<>OLD.event_key OR NEW.channel<>OLD.channel OR NEW.type<>OLD.type
 OR NEW.recipient<>OLD.recipient OR NEW.content<>OLD.content OR NEW.created_at<>OLD.created_at
 OR NOT ((OLD.status='Sukurtas' AND NEW.status IN ('Perduotas tiekėjui','Siuntimo klaida'))
         OR (OLD.status='Siuntimo klaida' AND NEW.status='Sukurtas'))
BEGIN SELECT RAISE(ABORT,'Pranešimo turinys nekintamas arba neleistina būsena'); END;
CREATE TRIGGER IF NOT EXISTS notification_delete_guard BEFORE DELETE ON notifications
BEGIN SELECT RAISE(ABORT,'Pranešimų istorija nenaikinama'); END;
CREATE TRIGGER IF NOT EXISTS attempt_insert_guard BEFORE INSERT ON notification_attempts
WHEN EXISTS(SELECT 1 FROM notification_attempts WHERE id=NEW.id)
 OR NEW.attempt_no<>(SELECT COALESCE(MAX(attempt_no),0)+1 FROM notification_attempts WHERE notification_id=NEW.notification_id)
 OR (SELECT status FROM notifications WHERE id=NEW.notification_id)<>'Sukurtas'
BEGIN SELECT RAISE(ABORT,'Siuntimo bandymas turi tęsti to paties pranešimo istoriją'); END;
CREATE TRIGGER IF NOT EXISTS attempt_update_guard BEFORE UPDATE ON notification_attempts
BEGIN SELECT RAISE(ABORT,'Bandymų istorija tik papildoma'); END;
CREATE TRIGGER IF NOT EXISTS attempt_delete_guard BEFORE DELETE ON notification_attempts
BEGIN SELECT RAISE(ABORT,'Bandymų istorija tik papildoma'); END;
