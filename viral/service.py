"""Seguimiento independiente: reloj por grupo y límite total por etapa."""
from copy import deepcopy
import json
import uuid
from .legacy_service import GameService as SharedGameService, AccessError
from .engine import RuleError,conservative,validate_strategy,simulate,ranking,indicators,initial_companies


def independent(game):
    return bool(game and game.get('flow_version') == 2)


def progress(round_no=1, status='waiting'):
    return {'round':round_no,'status':status,'start':None,'deadline':None,'events':[], 'skipped':[]}

class GameService(SharedGameService):
    def create_game(self,token,name='Partida VIRAL',seed=None,pins=None,independent=True):
        gid,created=super().create_game(token,name,seed,pins)
        if independent:
            with self.store.transaction() as tx:
                self._auth(tx,token,'admin')
                game=tx.game(gid)
                self._prepare_independent(game)
                tx.save(game)
        return gid,created
    def restart_game(self, token, expected_game_id):
        """Archive the current game and prepare a clean one atomically, retaining PINs."""
        from .config import rules
        import secrets
        with self.store.transaction() as tx:
            self._auth(tx,token,'admin')
            old=self._active(tx)
            if old['id']!=expected_game_id:
                raise RuleError('La partida cambió. Actualiza la pantalla antes de reiniciar.')
            encrypted=tx.meta('pin_vault:'+old['id'])
            if not encrypted:
                raise RuleError('Genera los PIN de los grupos antes de reiniciar.')
            pins=self.pin_vault.decrypt(old['id'],encrypted)
            now=self._now(tx)
            if old['status']!='finished':
                old.update(status='finished',finished_at=now,finish_reason='restart')
                tx.save(old)
            cfg=rules()
            fresh={'id':uuid.uuid4().hex,'name':old['name'],'seed':secrets.randbelow(2**31),
                   'created_at':now,'finished_at':None,'status':'ready','round':0,
                   'rules':cfg,'model_version':1,'companies':initial_companies(cfg),
                   'rounds':[],'decisions':{},'alliances':[],'market_history':[]}
            self._prepare_independent(fresh)
            self._save_pins(tx,fresh,pins)
            tx.save(fresh);tx.set_meta('active_game',fresh['id'])
            tx.execute("DELETE FROM sessions WHERE role='player'")
            self._audit(tx,'GAME_RESTARTED','admin',fresh['id'])
            return fresh['id']
    def _prepare_independent(self,game):
        game.update(flow_version=2,stage=1,stage_start=None,stage_deadline=None,
                    sales_ledger={},round_snapshots={},rounds=[],market_history=[])
        for company in game['companies']:
            company['progress']=progress()
    def _update_round(self,game):
        game['round']=max((c['progress']['round'] for c in game['companies']),default=1)
    def _begin(self,game,company,now):
        p=company['progress']
        if p['status'] not in ('waiting','between'):
            raise RuleError('Este grupo ya tiene una ronda en curso.')
        p.update(status='running',start=now,deadline=min(now+900,game['stage_deadline']))
        game.setdefault('round_snapshots',{}).setdefault(str(p['round']),{})[company['id']]=deepcopy(company)
    def start(self,token):
        current=self.view(token)
        if not independent(current):return super().start(token)
        with self.store.transaction() as tx:
            self._auth(tx,token,'admin');game=self._active(tx)
            if game['status']!='ready':raise RuleError('La partida ya fue iniciada.')
            now=self._now(tx)
            game.update(status='running',round=1,stage=1,stage_start=now,stage_deadline=now+5400)
            tx.save(game);self._audit(tx,'STAGE_STARTED','admin',game['id'])
    def resume(self,token):
        current=self.view(token)
        if not independent(current):return super().resume(token)
        with self.store.transaction() as tx:
            self._auth(tx,token,'admin');game=self._active(tx);self._reconcile(tx,game)
            all_done=all(c['progress']['status'] in ('paused','finished','eliminated') for c in game['companies'])
            if game['stage']!=1 or not (game['status']=='paused' or all_done):
                raise RuleError('La primera etapa todavía está en curso.')
            now=self._now(tx)
            game.update(status='running',stage=2,stage_start=now,stage_deadline=now+1800)
            for c in game['companies']:
                if c['eliminated_round'] is None and c['progress']['status']!='finished':
                    c['progress'].update(round=7,status='waiting',start=None,deadline=None)
            self._update_round(game);tx.save(game);self._audit(tx,'STAGE_RESUMED','admin',game['id'])
    def begin_round(self,token,round_no):
        self.view(token)
        with self.store.transaction() as tx:
            auth=self._auth(tx,token,'player');game=tx.game(auth['game_id']);self._reconcile(tx,game)
            c=next(c for c in game['companies'] if c['id']==auth['company_id'])
            if game['status']!='running' or c['progress']['round']!=round_no:
                raise RuleError('La etapa o tu ronda cambió. Actualiza la pantalla.')
            self._begin(game,c,self._now(tx));tx.save(game)
    def _scenario(self,game,company,number):
        snapshots=game['round_snapshots'].setdefault(str(number),{})
        snapshots.setdefault(company['id'],deepcopy(company))
        companies=[];decisions={}
        for rival in game['companies']:
            before=deepcopy(snapshots.get(rival['id'],rival))
            companies.append(before)
            if before['eliminated_round'] is not None:continue
            saved=game['decisions'].get(str(number),{}).get(rival['id'])
            strategy=deepcopy(saved['strategy']) if saved else conservative(before)
            decisions[rival['id']]={'strategy':strategy,'automatic':not bool(saved) or saved['automatic']}
        return companies,decisions
    def _complete_group(self,tx,game,company,now,automatic=False,advance=True):
        p=company['progress'];number=p['round'];cid=company['id']
        if p['status']!='running':raise RuleError('Tu ronda no está en curso.')
        company_before=deepcopy(company)
        scenarios,decisions=self._scenario(game,company,number)
        chosen=game['decisions'].setdefault(str(number),{}).get(cid)
        if not chosen:
            chosen={'strategy':conservative(company),'automatic':True,'submitted_at':None}
            game['decisions'][str(number)][cid]=chosen
        decisions[cid]=deepcopy(chosen)
        ledger=game['sales_ledger'].setdefault(str(number),{})
        simulated,_=simulate(scenarios,decisions,game['alliances'],number,game['seed'],game['rules'],target_id=cid,sales_ledger=ledger)
        updated=next(c for c in simulated if c['id']==cid)
        updated['pin_hash']=company['pin_hash']
        result=updated['history'][-1]
        for brand in result['brands']:
            for market,segments in brand['market_segment_units'].items():
                counts=ledger.setdefault(market,{})
                for segment,units in segments.items():counts[segment]=counts.get(segment,0)+units
        actual_totals={m:sum(ss.values()) for m,ss in ledger.items()}
        result['market_share']={m:100*u/max(actual_totals.get(m,0),1) for m,u in result['market_units'].items()}
        for brand in result['brands']:
            brand['market_share']={m:100*u/max(actual_totals.get(m,0),1) for m,u in brand['market_units'].items()}
        event={'number':number,'start':p['start'],'deadline':p['deadline'],'closed_at':now,
               'processed':True,'automatic':chosen['automatic'],'reason':'timer' if automatic else 'player'}
        updated['progress']=deepcopy(p)
        updated['progress']['events'].append(event)
        up=updated['progress']
        if updated['eliminated_round'] is not None:up.update(status='eliminated',start=None,deadline=None)
        elif not advance or number==8:up.update(status='finished',start=None,deadline=None)
        elif number==6:up.update(status='paused',start=None,deadline=None)
        else:up.update(round=number+1,status='between',start=None,deadline=None)
        game['companies'][next(i for i,c in enumerate(game['companies']) if c['id']==cid)]=updated
        for a in game['alliances']:
            if a['round']==number and cid in (a['from'],a['to']) and a['status']=='pending':a['status']='expired'
        tx.save(game)
        tx.execute('INSERT INTO group_rounds(game_id,company_id,round_no,payload) VALUES(?,?,?,?)',
                   (game['id'],cid,number,json.dumps({'event':event,'result':result,'before':company_before},ensure_ascii=False,allow_nan=False)))
        self._audit(tx,'GROUP_ROUND_CLOSED',cid,game['id'])
        self._update_round(game)
    def _end_stage(self,tx,game,now,finish=False):
        end=6 if game['stage']==1 else 8
        for c in list(game['companies']):
            p=c['progress']
            if p['status']=='running':
                self._complete_group(tx,game,c,now,automatic=True,advance=False)
                c=next(x for x in game['companies'] if x['id']==c['id']);p=c['progress']
            completed={h['round'] for h in c['history']}
            start=1 if game['stage']==1 else 7
            p['skipped']=sorted(set(p.get('skipped',[]))|{n for n in range(start,end+1) if n not in completed})
            if c['eliminated_round'] is None:
                p.update(status='finished' if finish or game['stage']==2 else 'paused',start=None,deadline=None)
        game['status']='finished' if finish or game['stage']==2 else 'paused'
        if game['status']=='finished':game['finished_at']=now
        tx.save(game)
    def _reconcile(self,tx,game):
        if not independent(game):return super()._reconcile(tx,game)
        self._normalize_group_names(tx,game)
        if game['status']!='running':return game
        now=self._now(tx)
        if now>=game['stage_deadline']:
            self._end_stage(tx,game,game['stage_deadline'])
        else:
            changed=False
            for c in list(game['companies']):
                p=c['progress']
                if p['status']=='running' and p['deadline']<=now:
                    self._complete_group(tx,game,c,p['deadline'],automatic=True);changed=True
            if game['stage']==2 and all(c['progress']['status'] in ('finished','eliminated') for c in game['companies']):
                game['status']='finished';game['finished_at']=now;changed=True
            if changed:tx.save(game)
        return game
    def _player_game(self,tx,token,expected_round=None):
        auth=self._auth(tx,token,'player');game=tx.game(auth['game_id'])
        if not independent(game):return super()._player_game(tx,token,expected_round)
        self._reconcile(tx,game)
        c=next(c for c in game['companies'] if c['id']==auth['company_id'])
        if game['status']!='running' or c['progress']['status']!='running':raise RuleError('Tu grupo no tiene una ronda abierta.')
        if expected_round is not None and c['progress']['round']!=expected_round:raise RuleError('Tu ronda cambió. Actualiza antes de confirmar.')
        if c['eliminated_round'] is not None:raise RuleError('Tu grupo fue eliminado.')
        return game,c
    def _reserved(self,game,cid,ignore=None):
        if not independent(game):return super()._reserved(game,cid,ignore)
        number=next(c for c in game['companies'] if c['id']==cid)['progress']['round']
        return sum(game['rules']['alliance_cost'] for a in game['alliances'] if a['id']!=ignore and a['round']==number
                   and ((a['status']=='pending' and a['from']==cid) or (a['status']=='accepted' and cid in (a['from'],a['to']))))
    def submit(self,token,round_no,decision):
        current=self.view(token)
        if not independent(current):return super().submit(token,round_no,decision)
        return self.complete_round(token,round_no,decision)
    def complete_round(self,token,round_no,decision):
        self.view(token)
        with self.store.transaction() as tx:
            game,c=self._player_game(tx,token,round_no)
            strategy=validate_strategy(c,decision,round_no,game['rules'],self._reserved(game,c['id']))
            game['decisions'].setdefault(str(round_no),{})[c['id']]={'strategy':strategy,'automatic':False,'submitted_at':self._now(tx)}
            self._complete_group(tx,game,c,self._now(tx))
            if game['stage']==2 and all(x['progress']['status'] in ('finished','eliminated') for x in game['companies']):
                game['status']='finished';game['finished_at']=self._now(tx)
            tx.save(game)
    def propose(self,token,round_no,other_id):
        current=self.view(token)
        if not independent(current):return super().propose(token,round_no,other_id)
        with self.store.transaction() as tx:
            game,c=self._player_game(tx,token,round_no)
            other=next((x for x in game['companies'] if x['id']==other_id),None)
            if round_no<4 or not other or other_id==c['id'] or other['progress']['round']!=round_no or other['progress']['status']!='running':
                raise RuleError('El otro grupo debe estar trabajando en tu misma ronda para colaborar.')
            if self._reserved(game,c['id']):raise RuleError('Ya tienes una colaboración en esta ronda.')
            saved=game['decisions'].get(str(round_no),{}).get(c['id'])
            strategy=saved['strategy'] if saved else conservative(c)
            validate_strategy(c,strategy,round_no,game['rules'],game['rules']['alliance_cost'])
            aid=uuid.uuid4().hex
            game['alliances'].append({'id':aid,'from':c['id'],'to':other_id,'round':round_no,'status':'pending','created_at':self._now(tx)})
            if not saved:game['decisions'].setdefault(str(round_no),{})[c['id']]={'strategy':strategy,'automatic':False,'submitted_at':self._now(tx)}
            tx.save(game);self._audit(tx,'ALLIANCE_PROPOSED',c['id'],game['id'])
            return aid
    def close_stage(self,token,game_id):
        self.view(token)
        with self.store.transaction() as tx:
            self._auth(tx,token,'admin');game=self._active(tx)
            if game['id']!=game_id or game['status']!='running':raise RuleError('La etapa ya no está en curso.')
            self._end_stage(tx,game,self._now(tx));self._audit(tx,'STAGE_CLOSED_MANUALLY','admin',game['id'])
    def finish_game(self,token,game_id,round_no):
        current=self.view(token,game_id)
        if not independent(current):return super().finish_game(token,game_id,round_no)
        with self.store.transaction() as tx:
            self._auth(tx,token,'admin');game=self._active(tx);self._reconcile(tx,game)
            if game['id']!=game_id:raise RuleError('La partida cambió.')
            if game['status']=='finished':return
            if game['status']=='running':self._end_stage(tx,game,self._now(tx),finish=True)
            else:
                game['status']='finished';game['finished_at']=self._now(tx)
                for c in game['companies']:
                    if c['eliminated_round'] is None:c['progress']['status']='finished'
            game['finish_reason']='admin';tx.save(game);self._audit(tx,'GAME_FINISHED_MANUALLY','admin',game['id'])
    def view(self,token,game_id=None):
        legacy=False
        with self.store.transaction() as tx:
            auth=self._auth(tx,token)
            if auth['role']=='player':
                if game_id and game_id!=auth['game_id']:raise AccessError('No tienes acceso a esa partida.')
                gid=auth['game_id']
            else:gid=game_id or tx.meta('active_game')
            game=tx.game(gid) if gid else None
            if not game:return None
            if not independent(game):legacy=True
            else:
                self._reconcile(tx,game)
                if auth['role']=='player':
                    c=next(c for c in game['companies'] if c['id']==auth['company_id'])
                    if game['status']=='running' and c['progress']['status']=='waiting':
                        self._begin(game,c,self._now(tx));tx.save(game)
                safe=deepcopy(game)
                for c in safe['companies']:c.pop('pin_hash',None)
                safe.pop('round_snapshots',None);safe.pop('sales_ledger',None)
                safe['server_now']=self._now(tx)
                if auth['role']=='admin':
                    safe['ranking']=ranking(game['companies'],game['rules'])
                    return safe
                cid=auth['company_id'];safe['company']=next(c for c in safe['companies'] if c['id']==cid)
                p=safe['company']['progress'];safe['round']=p['round']
                safe['group_status']=p['status'];safe['rounds']=deepcopy(p['events'])
                safe['reserved']=self._reserved(game,cid)
                safe['my_decision']=deepcopy(game['decisions'].get(str(p['round']),{}).get(cid))
                safe['my_indicators']=indicators(safe['company'],game['companies'],game['rules']) if game['status']=='finished' else None
                safe['alliances']=[a for a in safe['alliances'] if cid in (a['from'],a['to'])]
                safe['alliance_candidates']=[{'id':c['id'],'name':c['name']} for c in game['companies'] if c['id']!=cid and c['progress']['round']==p['round'] and c['progress']['status']=='running']
                if game['status']=='finished':safe['ranking']=ranking(game['companies'],game['rules'])
                for key in ('companies','decisions','seed','market_history'):safe.pop(key,None)
                return safe
        if legacy:return super().view(token,game_id)
    def migrate_active_game(self,token):
        """Conserva una copia íntegra y corrige los avances automáticos sin envío real."""
        with self.store.transaction() as tx:
            self._auth(tx,token,'admin');game=self._active(tx)
            if independent(game) or game['status']=='finished':return False
            archive=deepcopy(game);archive['id']=uuid.uuid4().hex
            archive['name']=game['name']+' · respaldo antes del seguimiento individual'
            archive['status']='finished';archive['finish_reason']='migration_backup';archive['finished_at']=self._now(tx)
            tx.save(archive)
            encrypted=tx.meta('pin_vault:'+game['id'])
            if encrypted:
                pins=self.pin_vault.decrypt(game['id'],encrypted)
                tx.set_meta('pin_vault:'+archive['id'],self.pin_vault.encrypt(archive['id'],pins))
            originals=deepcopy(game['companies']);decisions=deepcopy(game['decisions'])
            self._prepare_independent(game)
            initial=initial_companies(game['rules'])
            retained_decisions={}
            for i,c in enumerate(originals):
                completed={h['round'] for h in c['history']}
                real=[int(n) for n,ds in decisions.items() if int(n) in completed and c['id'] in ds and not ds[c['id']]['automatic']]
                last=max(real,default=0)
                current=game['companies'][i]
                if not last:
                    h=current['pin_hash'];game['companies'][i]=initial[i];current=game['companies'][i];current['pin_hash']=h
                    current['progress']=progress()
                else:
                    saved=tx.one('SELECT payload FROM rounds WHERE game_id=? AND round_no=?',(game['id'],last))
                    if saved:
                        snapshot=json.loads(saved[0])
                        restored=next(x for x in snapshot['companies'] if x['id']==c['id'])
                        restored['pin_hash']=c['pin_hash'];game['companies'][i]=current=deepcopy(restored)
                    current['history']=[h for h in current['history'] if h['round']<=last]
                    current['progress']=progress(min(last+1,8),'finished' if last==8 else 'paused' if last>=6 else 'waiting')
                    current['progress']['events']=[{'number':h['round'],'processed':True,'automatic':h['automatic'],'start':None,'deadline':None,'closed_at':None,'reason':'imported'} for h in current['history']]
                    for h in current['history']:
                        number=h['round']
                        before=deepcopy(initial[i])
                        if number>1:
                            row=tx.one('SELECT payload FROM rounds WHERE game_id=? AND round_no=?',(game['id'],number-1))
                            if row:before=deepcopy(next(x for x in json.loads(row[0])['companies'] if x['id']==c['id']))
                        game['round_snapshots'].setdefault(str(number),{})[c['id']]=before
                        if c['id'] in decisions.get(str(number),{}):retained_decisions.setdefault(str(number),{})[c['id']]=deepcopy(decisions[str(number)][c['id']])
                        ledger=game['sales_ledger'].setdefault(str(number),{})
                        for brand in h['brands']:
                            for market,total in brand['market_units'].items():
                                segments=brand.get('market_segment_units',{}).get(market)
                                if segments is None:
                                    segments=brand['segment_units'] if len(brand['market_units'])==1 else {s:int(total*w) for s,w in zip(('Rendimiento','Sensible al precio','Tendencia','Bienestar y rutina'),game['rules']['segment_weights'])}
                                    gap=total-sum(segments.values())
                                    if gap:segments=dict(segments);segments['Rendimiento']=segments.get('Rendimiento',0)+gap
                                counts=ledger.setdefault(market,{})
                                for segment,units in segments.items():counts[segment]=counts.get(segment,0)+units
            game['decisions']=retained_decisions
            now=self._now(tx)
            game.update(status='running',stage=1,stage_start=now,stage_deadline=now+5400,migration_backup_id=archive['id'])
            # Los envíos anteriores quedan en el respaldo; no se aplican de nuevo.
            self._update_round(game);tx.save(game)
            self._audit(tx,'GROUP_PROGRESS_MIGRATED','admin',game['id'])
            return True
