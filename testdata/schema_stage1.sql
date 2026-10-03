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
 created_by INTEGER NOT NULL REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointments(id),
 mileage INTEGER NOT NULL CHECK(mileage >= 0), status TEXT NOT NULL DEFAULT 'Naujas'
 CHECK(status IN ('Naujas','Derinamas','Patvirtintas','Vykdomas','Paruoštas','Uždarytas','Atšauktas')),
 created_at TEXT NOT NULL, closed_at TEXT, closing_note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS estimates (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
 version INTEGER NOT NULL CHECK(version > 0), status TEXT NOT NULL DEFAULT 'Rengiama'
 CHECK(status IN ('Rengiama','Pateikta','Patvirtinta','Atmesta','Pakeista')),
 total_cents INTEGER NOT NULL DEFAULT 0 CHECK(total_cents >= 0),
 decision_note TEXT NOT NULL DEFAULT '', decision_at TEXT, decided_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL, UNIQUE(order_id,version)
);
CREATE TABLE IF NOT EXISTS estimate_lines (
 id INTEGER PRIMARY KEY, estimate_id INTEGER NOT NULL REFERENCES estimates(id),
 kind TEXT NOT NULL CHECK(kind IN ('Darbas','Detalė')), title TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity > 0), unit_cents INTEGER NOT NULL CHECK(unit_cents >= 0)
);
CREATE TABLE IF NOT EXISTS tasks (
 id INTEGER PRIMARY KEY, line_id INTEGER NOT NULL UNIQUE REFERENCES estimate_lines(id),
 mechanic_id INTEGER REFERENCES users(id), status TEXT NOT NULL DEFAULT 'Suplanuota'
 CHECK(status IN ('Suplanuota','Vykdoma','Sustabdyta','Baigta','Atšaukta')),
 minutes INTEGER NOT NULL DEFAULT 0 CHECK(minutes >= 0), note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), entity TEXT NOT NULL,
 entity_id INTEGER NOT NULL, action TEXT NOT NULL, happened_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appointments_slot ON appointments(bay,start_at,end_at,status);
CREATE INDEX IF NOT EXISTS idx_estimates_order ON estimates(order_id,version);
CREATE INDEX IF NOT EXISTS idx_tasks_mechanic ON tasks(mechanic_id,status);
