"""SQLite local / PostgreSQL Supabase: transacciones cortas bajo exclusión global.

Siete jugadores y ocho rondas justifican un agregado JSON por partida. Las rondas
cerradas tienen además un diario UNIQUE(game_id, round_no). No hay datos del juego
expuestos por PostgREST. Solo el servidor Python conoce la conexión SQL.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import time
from urllib.parse import urlparse, parse_qs

SQLITE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS games (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rounds (game_id TEXT NOT NULL, round_no INTEGER NOT NULL,
    payload TEXT NOT NULL, PRIMARY KEY(game_id, round_no));
CREATE TABLE IF NOT EXISTS group_rounds (game_id TEXT NOT NULL, company_id TEXT NOT NULL,
    round_no INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(game_id, company_id, round_no));
CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, role TEXT NOT NULL,
    game_id TEXT, company_id TEXT, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (principal TEXT PRIMARY KEY, failures INTEGER NOT NULL,
    window_start REAL NOT NULL, locked_until REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, at REAL NOT NULL, action TEXT NOT NULL,
    principal TEXT NOT NULL, game_id TEXT);
'''

class Tx:
    def __init__(self, conn, postgres):
        self.conn, self.postgres = conn, postgres
        self.cur = conn.cursor()
    def execute(self, query, args=()):
        return self.cur.execute(query.replace('?', '%s') if self.postgres else query, args)
    def one(self, query, args=()):
        self.execute(query, args)
        return self.cur.fetchone()
    def all(self, query, args=()):
        self.execute(query, args)
        return self.cur.fetchall()
    def now(self):
        if self.postgres:
            return float(self.one('SELECT EXTRACT(EPOCH FROM clock_timestamp())')[0])
        return time.time()
    def meta(self, key):
        r = self.one('SELECT value FROM meta WHERE key=?', (key,))
        return r[0] if r else None
    def set_meta(self, key, value):
        self.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
    def game(self, gid):
        row = self.one('SELECT payload FROM games WHERE id=?', (gid,))
        return json.loads(row[0]) if row else None
    def save(self, game):
        payload = json.dumps(game, ensure_ascii=False, allow_nan=False)
        self.execute('INSERT INTO games(id,payload) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (game['id'], payload))

class Store:
    def __init__(self, path='data/viral.sqlite3', database_url=''):
        self.path, self.database_url = str(path), database_url
        self.postgres = bool(database_url)
        if not self.postgres:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=30)
            conn.executescript(SQLITE_SCHEMA)
            conn.commit()
            conn.close()
    @contextmanager
    def transaction(self):
        if self.postgres:
            import psycopg2
            parsed = urlparse(self.database_url)
            sslmode = parse_qs(parsed.query).get('sslmode', ['prefer'])[0] if parsed.hostname in ('localhost', '127.0.0.1', '::1') else 'require'
            conn = psycopg2.connect(self.database_url, connect_timeout=10, sslmode=sslmode, application_name='viral')
        else:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.execute('PRAGMA busy_timeout=30000')
        tx = Tx(conn, self.postgres)
        try:
            if self.postgres:
                tx.execute('SET LOCAL search_path TO viral_private')
                tx.execute("SET LOCAL statement_timeout = '25s'")
                tx.execute('SELECT pg_advisory_xact_lock(92715031)')
            else:
                tx.execute('BEGIN IMMEDIATE')
            yield tx
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            tx.cur.close()
            conn.close()
