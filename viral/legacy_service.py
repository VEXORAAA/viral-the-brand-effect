"""Operaciones autorizadas y ciclo persistente de la partida."""
from copy import deepcopy
import json
import secrets
import uuid
from .config import COMPANIES, rules
from .engine import (RuleError, initial_companies, conservative, validate_strategy,
                     strategy_cost, simulate, ranking, indicators)
from .security import hash_secret, verify_secret, token_digest, new_pins, valid_pins
from .pin_vault import PinVault

class AccessError(PermissionError):
    pass

class GameService:
    def __init__(self, store, admin_password, clock=None, pin_key=None):
        if not isinstance(admin_password, str) or not 12 <= len(admin_password) <= 128:
            raise RuleError('Configura VIRAL_ADMIN_PASSWORD con 12–128 caracteres antes de iniciar.')
        self.store, self.clock = store, clock
        self.pin_vault = PinVault(store, pin_key)
        with store.transaction() as tx:
            if not tx.meta('admin_hash'):
                tx.set_meta('admin_hash', hash_secret(admin_password))
            elif not verify_secret(admin_password, tx.meta('admin_hash')):
                # La variable de entorno es la fuente de autoridad para rotar credenciales.
                tx.set_meta('admin_hash', hash_secret(admin_password))
                tx.execute("DELETE FROM sessions WHERE role='admin'")
                self._audit(tx, 'ADMIN_SECRET_ROTATED', 'admin', None)
    def _now(self, tx):
        return float(self.clock()) if self.clock else tx.now()
    def _audit(self, tx, action, principal, gid):
        tx.execute('INSERT INTO audit(id,at,action,principal,game_id) VALUES(?,?,?,?,?)',
                   (uuid.uuid4().hex, self._now(tx), action, str(principal), gid))
    def _auth(self, tx, token, role=None):
        row = tx.one('SELECT role,game_id,company_id,expires FROM sessions WHERE digest=?', (token_digest(token),))
        if not row or row[3] <= self._now(tx) or (role and row[0] != role):
            raise AccessError('Tu sesión venció o no tienes acceso. Vuelve a ingresar.')
        return {'role': row[0], 'game_id': row[1], 'company_id': row[2]}
    def login(self, role, password, company_id=None):
        if role not in ('admin', 'player') or not isinstance(password, str) or len(password) > 256:
            raise AccessError('Credenciales inválidas.')
        token = None
        error = 'Credenciales inválidas.'
        with self.store.transaction() as tx:
            now = self._now(tx)
            gid = tx.meta('active_game') if role == 'player' else None
            principal = f'{role}:{gid or ""}:{company_id if role == "player" else "admin"}'
            # El acceso de aula permite reintentar inmediatamente, incluso con bloqueos antiguos.
            tx.execute('DELETE FROM attempts WHERE principal=?', (principal,))
            stored = tx.meta('admin_hash')
            if role == 'player':
                g = tx.game(gid) if gid else None
                c = next((c for c in g['companies'] if c['id'] == str(company_id)), None) if g else None
                stored = c['pin_hash'] if c else ''
            if verify_secret(password, stored):
                token = secrets.token_urlsafe(32)
                tx.execute('INSERT INTO sessions(digest,role,game_id,company_id,expires) VALUES(?,?,?,?,?)',
                           (token_digest(token), role, gid, str(company_id) if role == 'player' else None, now + 43200))
                tx.execute('DELETE FROM sessions WHERE expires<=?', (now,))
                self._audit(tx, 'LOGIN', principal, gid)
            else:
                self._audit(tx, 'LOGIN_FAILED', principal, gid)
        if not token:
            raise AccessError(error)
        return token
    def logout(self, token):
        with self.store.transaction() as tx:
            tx.execute('DELETE FROM sessions WHERE digest=?', (token_digest(token),))
    def public_lobby(self):
        with self.store.transaction() as tx:
            gid = tx.meta('active_game')
            game = tx.game(gid) if gid else None
            return {'game_id': gid, 'name': game['name'] if game else None,
                    'status': game['status'] if game else 'empty'}
    def create_game(self, token, name='Partida VIRAL', seed=None, pins=None):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise RuleError('El nombre debe tener entre 1 y 80 caracteres.')
        pins = deepcopy(pins) if pins is not None else new_pins()
        if not valid_pins(pins):
            raise RuleError('Configura siete PIN distintos de exactamente 4 dígitos.')
        if seed is None:
            seed = secrets.randbelow(2**31)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
            raise RuleError('Semilla inválida.')
        with self.store.transaction() as tx:
            self._auth(tx, token, 'admin')
            current_id = tx.meta('active_game')
            current = tx.game(current_id) if current_id else None
            if current and current['status'] != 'finished':
                raise RuleError('Finaliza la partida vigente antes de preparar otra.')
            cfg = rules()
            game = {'id': uuid.uuid4().hex, 'name': name.strip(), 'seed': seed,
                    'created_at': self._now(tx), 'finished_at': None, 'status': 'ready', 'round': 0,
                    'rules': cfg, 'model_version': 1, 'companies': initial_companies(cfg),
                    'rounds': [], 'decisions': {}, 'alliances': [], 'market_history': []}
            self._save_pins(tx, game, pins)
            tx.save(game)
            tx.set_meta('active_game', game['id'])
            self._audit(tx, 'GAME_CREATED', 'admin', game['id'])
        return game['id'], pins
    def configure_pins(self, token, pins):
        if not valid_pins(pins):
            raise RuleError('Configura siete PIN distintos de exactamente 4 dígitos.')
        with self.store.transaction() as tx:
            self._auth(tx, token, 'admin')
            g = self._active(tx)
            if g['status'] != 'ready':
                raise RuleError('Solo puedes cambiar los PIN antes de iniciar.')
            self._save_pins(tx, g, pins, revoke=True)
            tx.save(g)
            self._audit(tx, 'PINS_CONFIGURED', 'admin', g['id'])
    def _save_pins(self, tx, game, pins, revoke=False):
        for company in game['companies']:
            company['pin_hash'] = hash_secret(pins[company['id']])
        tx.set_meta('pin_vault:' + game['id'], self.pin_vault.encrypt(game['id'], pins))
        if revoke:
            tx.execute("DELETE FROM sessions WHERE game_id=? AND role='player'", (game['id'],))
            tx.execute('DELETE FROM attempts WHERE principal LIKE ?', (f"player:{game['id']}:%",))
    def admin_pins(self, token, game_id=None):
        with self.store.transaction() as tx:
            self._auth(tx, token, 'admin')
            gid = game_id or tx.meta('active_game')
            if not gid or not tx.game(gid):
                raise RuleError('No se encontró la partida.')
            encrypted = tx.meta('pin_vault:' + gid)
            if not encrypted:
                return None  # Partidas antiguas: el hash no permite recuperar el PIN.
            pins = self.pin_vault.decrypt(gid, encrypted)
            self._audit(tx, 'PINS_VIEWED', 'admin', gid)
            return pins
    def regenerate_pins(self, token):
        with self.store.transaction() as tx:
            self._auth(tx, token, 'admin')
            game = self._active(tx)
            self._reconcile(tx, game)
            if game['status'] == 'finished':
                raise RuleError('La partida terminó. Prepara otra para generar nuevos PIN.')
            pins = new_pins()
            while any(verify_secret(pins[c['id']], c['pin_hash']) for c in game['companies']):
                pins = new_pins()
            self._save_pins(tx, game, pins, revoke=True)
            tx.save(game)
            self._audit(tx, 'PINS_REGENERATED', 'admin', game['id'])
            return pins
    def _active(self, tx):
        gid = tx.meta('active_game')
        g = tx.game(gid) if gid else None
        if not g:
            raise RuleError('Todavía no hay partida. El administrador debe prepararla.')
        return g
    def _open_round(self, g, number, start):
        g['round'], g['status'] = number, 'running'
        g['rounds'].append({'number': number, 'start': start,
                            'deadline': start + g['rules']['round_seconds'],
                            'scheduled_deadline': start + g['rules']['round_seconds'], 'processed': False})
    def start(self, token):
        with self.store.transaction() as tx:
            self._auth(tx, token, 'admin')
            g = self._active(tx)
            if g['status'] != 'ready':
                raise RuleError('La partida ya fue iniciada.')
            self._open_round(g, 1, self._now(tx))
            tx.save(g)
            self._audit(tx, 'GAME_STARTED', 'admin', g['id'])
    def resume(self, token):
        with self.store.transaction() as tx:
            self._auth(tx, token, 'admin')
            g = self._active(tx)
            if g['status'] != 'paused' or g['round'] != 6:
                raise RuleError('Solo se reanuda después de la pausa de la ronda 6.')
            self._open_round(g, 7, self._now(tx))
            tx.save(g)
            self._audit(tx, 'GAME_RESUMED', 'admin', g['id'])
    def _normalize_group_names(self, tx, game):
        changed = False
        for company in game['companies']:
            name = f"Grupo {int(company['id']) + 1}"
            if company['name'] != name:
                company['name'] = name
                changed = True
        if changed:
            tx.save(game)
    def _process_round(self, tx, g, now, finish=False):
        """Único cierre económico para reloj, cierre manual y final administrativo."""
        r = g['rounds'][-1]
        if r['processed']:
            raise RuleError('Esta ronda ya fue procesada.')
        n = r['number']
        effective = {}
        for company in g['companies']:
            if company['eliminated_round'] is not None:
                continue
            saved = g['decisions'].get(str(n), {}).get(company['id'])
            effective[company['id']] = deepcopy(saved) if saved else {
                'strategy': conservative(company), 'automatic': True, 'submitted_at': None}
        g['decisions'][str(n)] = effective
        for alliance in g['alliances']:
            if alliance['round'] == n and alliance['status'] == 'pending':
                alliance['status'] = 'expired'
        companies, totals = simulate(g['companies'], effective, g['alliances'], n, g['seed'], g['rules'])
        g['companies'] = companies
        r['processed'], r['processed_at'] = True, now
        r.setdefault('close_reason', 'timer')
        g['market_history'].append({'round': n, 'markets': totals})
        # Diario y agregado pertenecen a la misma transacción.
        tx.save(g)
        tx.execute('INSERT INTO rounds(game_id,round_no,payload) VALUES(?,?,?)',
                   (g['id'], n, json.dumps({'round': r, 'companies': companies, 'markets': totals}, ensure_ascii=False, allow_nan=False)))
        self._audit(tx, 'ROUND_CLOSED', 'system' if r['close_reason'] == 'timer' else 'admin', g['id'])
        alive = sum(c['eliminated_round'] is None for c in companies)
        if finish or n == 8 or alive == 0:
            g['status'], g['finished_at'] = 'finished', r['deadline']
            g['finish_reason'] = 'admin' if finish else 'completed' if n == 8 else 'all_eliminated'
        elif n == 6:
            g['status'] = 'paused'
        else:
            self._open_round(g, n + 1, r['deadline'])
        tx.save(g)
    def _reconcile(self, tx, g):
        self._normalize_group_names(tx, g)
        now = self._now(tx)
        while g['status'] == 'running' and g['rounds'][-1]['deadline'] <= now:
            self._process_round(tx, g, now)
        return g
    def close_round(self, token, round_no, game_id):
        self.view(token)  # Confirmar por separado cualquier cierre ya vencido.
        with self.store.transaction() as tx:
            self._auth(tx, token, 'admin')
            game = self._active(tx)
            self._reconcile(tx, game)
            if game['id'] != game_id or game['round'] != round_no or game['status'] != 'running':
                raise RuleError('La partida o la ronda cambió. Actualiza antes de cerrarla.')
            now = self._now(tx)
            current = game['rounds'][-1]
            current.setdefault('scheduled_deadline', current['deadline'])
            current['deadline'], current['close_reason'] = now, 'admin'
            self._process_round(tx, game, now)
            self._audit(tx, 'ROUND_CLOSED_MANUALLY', 'admin', game['id'])
    def finish_game(self, token, game_id, round_no):
        self.view(token)
        with self.store.transaction() as tx:
            self._auth(tx, token, 'admin')
            game = self._active(tx)
            self._reconcile(tx, game)
            if game['id'] != game_id or game['round'] != round_no:
                raise RuleError('La partida o la ronda cambió. Actualiza antes de finalizar.')
            if game['status'] == 'finished':
                return  # Reintento idempotente: nunca repetir resultados.
            now = self._now(tx)
            if game['status'] == 'running':
                current = game['rounds'][-1]
                current.setdefault('scheduled_deadline', current['deadline'])
                current['deadline'], current['close_reason'] = now, 'admin_finish'
                self._process_round(tx, game, now, finish=True)
            else:
                # En espera o pausa no se simula ninguna ronda adicional.
                game['status'], game['finished_at'], game['finish_reason'] = 'finished', now, 'admin'
                tx.save(game)
            self._audit(tx, 'GAME_FINISHED_MANUALLY', 'admin', game['id'])
    def _player_game(self, tx, token, expected_round=None):
        auth = self._auth(tx, token, 'player')
        g = tx.game(auth['game_id'])
        self._reconcile(tx, g)
        if g['status'] != 'running':
            raise RuleError('La partida no está recibiendo estrategias en este momento.')
        if expected_round is not None and expected_round != g['round']:
            raise RuleError('La ronda cambió. Actualiza la página antes de confirmar.')
        c = next(c for c in g['companies'] if c['id'] == auth['company_id'])
        if c['eliminated_round'] is not None:
            raise RuleError('Tu empresa fue eliminada y ya no puede invertir.')
        return g, c
    def _reserved(self, g, cid, ignore=None):
        return sum(g['rules']['alliance_cost'] for a in g['alliances']
                   if a['id'] != ignore and a['round'] == g['round'] and
                   ((a['status'] == 'pending' and a['from'] == cid) or
                    (a['status'] == 'accepted' and cid in (a['from'], a['to']))))
    def submit(self, token, round_no, decision):
        self.view(token)
        with self.store.transaction() as tx:
            g, c = self._player_game(tx, token, round_no)
            strategy = validate_strategy(c, decision, g['round'], g['rules'], self._reserved(g, c['id']))
            g['decisions'].setdefault(str(round_no), {})[c['id']] = {'strategy': strategy, 'automatic': False, 'submitted_at': self._now(tx)}
            tx.save(g)
            self._audit(tx, 'STRATEGY_CONFIRMED', c['id'], g['id'])
    def propose(self, token, round_no, other_id):
        self.view(token)
        with self.store.transaction() as tx:
            g, c = self._player_game(tx, token, round_no)
            other = next((x for x in g['companies'] if x['id'] == other_id), None)
            if g['round'] < 4 or not other or other_id == c['id'] or other['eliminated_round'] is not None:
                raise RuleError('Alianza no disponible.')
            if any(a['round'] == round_no and a['status'] in ('pending', 'accepted') and c['id'] in (a['from'], a['to']) for a in g['alliances']):
                raise RuleError('Solo puedes tener una alianza o propuesta activa por ronda.')
            saved = g['decisions'].get(str(round_no), {}).get(c['id'])
            # Proponer confirma también la estrategia conservadora si no había envío.
            # Así el proponente siempre asume y puede pagar el costo reservado.
            strategy = saved['strategy'] if saved else conservative(c)
            validate_strategy(c, strategy, round_no, g['rules'], g['rules']['alliance_cost'])
            aid = uuid.uuid4().hex
            g['alliances'].append({'id': aid, 'from': c['id'], 'to': other_id, 'round': round_no,
                                  'status': 'pending', 'created_at': self._now(tx)})
            if not saved:
                g['decisions'].setdefault(str(round_no), {})[c['id']] = {'strategy': strategy, 'automatic': False, 'submitted_at': self._now(tx)}
            tx.save(g)
            self._audit(tx, 'ALLIANCE_PROPOSED', c['id'], g['id'])
            return aid
    def respond(self, token, round_no, alliance_id, accept):
        if not isinstance(accept, bool):
            raise RuleError('Respuesta inválida.')
        self.view(token)
        with self.store.transaction() as tx:
            g, c = self._player_game(tx, token, round_no)
            a = next((a for a in g['alliances'] if a['id'] == alliance_id), None)
            if not a or a['round'] != round_no or a['to'] != c['id'] or a['status'] != 'pending':
                raise AccessError('No puedes responder esta propuesta.')
            if accept:
                if any(x['id'] != a['id'] and x['round'] == round_no and ((x['status'] == 'accepted' and c['id'] in (x['from'], x['to'])) or (x['status'] == 'pending' and x['from'] == c['id'])) for x in g['alliances']):
                    raise RuleError('Ya tienes una alianza o propuesta activa.')
                saved = g['decisions'].get(str(round_no), {}).get(c['id'])
                strategy = saved['strategy'] if saved else conservative(c)
                validate_strategy(c, strategy, round_no, g['rules'], g['rules']['alliance_cost'])
                if not saved:
                    g['decisions'].setdefault(str(round_no), {})[c['id']] = {'strategy': strategy, 'automatic': False, 'submitted_at': self._now(tx)}
            a['status'] = 'accepted' if accept else 'rejected'
            tx.save(g)
            self._audit(tx, 'ALLIANCE_ACCEPTED' if accept else 'ALLIANCE_REJECTED', c['id'], g['id'])
    def finish_early(self, token):
        with self.store.transaction() as tx:
            self._auth(tx, token, 'admin')
            g = self._active(tx)
            self._reconcile(tx, g)
            if g['status'] not in ('running', 'paused') or g['round'] < 1 or sum(c['eliminated_round'] is None for c in g['companies']) != 1:
                raise RuleError('El final anticipado requiere exactamente una empresa activa.')
            g['status'], g['finished_at'] = 'finished', self._now(tx)
            if g['rounds'] and not g['rounds'][-1]['processed']:
                g['rounds'][-1]['cancelled'] = True
            tx.save(g)
            self._audit(tx, 'EARLY_FINISH', 'admin', g['id'])
    def list_games(self, token):
        with self.store.transaction() as tx:
            self._auth(tx, token, 'admin')
            games = [json.loads(row[0]) for row in tx.all('SELECT payload FROM games')]
            return sorted([{'id': g['id'], 'name': g['name'], 'created_at': g['created_at'], 'status': g['status']} for g in games], key=lambda g: g['created_at'], reverse=True)
    def view(self, token, game_id=None):
        with self.store.transaction() as tx:
            auth = self._auth(tx, token)
            if auth['role'] == 'player':
                if game_id and game_id != auth['game_id']:
                    raise AccessError('No tienes acceso a esa partida.')
                gid = auth['game_id']
            else:
                gid = game_id or tx.meta('active_game')
            g = tx.game(gid) if gid else None
            if not g:
                return None
            self._reconcile(tx, g)
            safe = deepcopy(g)
            for c in safe['companies']:
                c.pop('pin_hash', None)
            safe['server_now'] = self._now(tx)
            if auth['role'] == 'admin':
                safe['ranking'] = ranking(g['companies'], g['rules'])
                return safe
            cid = auth['company_id']
            safe['company'] = next(c for c in safe['companies'] if c['id'] == cid)
            safe['reserved'] = self._reserved(g, cid)
            safe['my_decision'] = deepcopy(g['decisions'].get(str(g['round']), {}).get(cid))
            safe['my_indicators'] = indicators(safe['company'], g['companies'], g['rules']) if g['status'] == 'finished' else None
            safe['alliances'] = [a for a in safe['alliances'] if cid in (a['from'], a['to'])]
            if g['status'] == 'finished':
                safe['ranking'] = ranking(g['companies'], g['rules'])
            # Competiciones activas: ninguna estadística o estrategia ajena llega al cliente.
            for key in ('companies', 'decisions', 'seed', 'market_history'):
                safe.pop(key, None)
            return safe
