"""Motor determinista sin dependencias de interfaz ni almacenamiento."""
from copy import deepcopy
import hashlib
import math
import random
from .config import (COMPANIES, SEGMENTS, ATTRIBUTES, CONTENTS, OBJECTIVES, PLATFORMS,
                     CONTENT_AFFINITY, INFLUENCERS, SPONSORS, STUDIES)

class RuleError(ValueError):
    pass

def clip(x, low=0, high=100):
    return max(low, min(high, x))

def numeric(value, label, low=0, high=1e9):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise RuleError(f'{label}: valor fuera de rango ({low}–{high}).')
    return float(value)

def initial_companies(cfg):
    result = []
    for i, (name, b1, b2, color) in enumerate(COMPANIES):
        result.append({
            'id': str(i), 'name': name, 'color': color, 'capital': cfg['initial_capital'],
            'profit': 0, 'revenue': 0, 'marketing': 0, 'innovation': 0,
            'eliminated_round': None, 'history': [],
            'brands': [{'id': str(j), 'name': b, 'quality': 50., 'awareness': 20.,
                        'reputation': 60., 'price': 15., 'segment': SEGMENTS[j * 2],
                        'attribute': ATTRIBUTES[j * 2], 'markets': ['VITAL'],
                        'campaign_key': '', 'repeats': 0, 'viral': 0.} for j, b in enumerate((b1, b2))],
        })
    return result

def conservative(company):
    return {'brands': [{'id': b['id'], 'price': b['price'], 'segment': b['segment'],
        'attribute': b['attribute'], 'platform': 'Facebook', 'content': 'Testimonios',
        'objective': 'Conversión', 'budget': 0, 'content_budget': 0, 'influencer': 'Ninguno',
        'innovation': 0, 'expand': 'Ninguna'} for b in company['brands']],
        'sponsor': 'Ninguno', 'studies': []}

def strategy_cost(decision, cfg):
    return round(sum(d['budget'] + d['content_budget'] + d['innovation'] + INFLUENCERS[d['influencer']]['cost']
                     + (cfg['markets'][d['expand']]['entry'] if d['expand'] != 'Ninguna' else 0)
                     for d in decision['brands']) + SPONSORS[decision['sponsor']]['cost']
                 + sum(STUDIES[s] for s in decision['studies']), 2)

def validate_strategy(company, decision, round_no, cfg, reserved=0):
    if company['eliminated_round'] is not None:
        raise RuleError('Esta empresa fue eliminada y conserva acceso solo a su historial.')
    if not isinstance(decision, dict) or set(decision) != {'brands', 'sponsor', 'studies'}:
        raise RuleError('Estrategia incompleta o con campos desconocidos.')
    ds = decision['brands']
    if not isinstance(ds, list) or len(ds) != 2 or any(not isinstance(d, dict) or not isinstance(d.get('id'), str) for d in ds) or {d['id'] for d in ds} != {'0', '1'}:
        raise RuleError('Debes configurar las dos marcas de tu empresa.')
    required = set(conservative(company)['brands'][0])
    for d in ds:
        if set(d) != required:
            raise RuleError('Campos de marca incorrectos.')
        b = next(b for b in company['brands'] if b['id'] == d['id'])
        numeric(d['price'], 'Precio', 5, 45)
        numeric(d['budget'], 'Publicidad', 0, 500000)
        numeric(d['content_budget'], 'Contenido', 0, 100000)
        numeric(d['innovation'], 'Innovación', 0, cfg['max_innovation'])
        for key, allowed in [('segment', SEGMENTS), ('attribute', ATTRIBUTES), ('platform', PLATFORMS),
                             ('content', CONTENTS), ('objective', OBJECTIVES), ('influencer', INFLUENCERS),
                             ('expand', ['Ninguna', 'ACTIVE', 'TECH'])]:
            if not isinstance(d[key], str) or d[key] not in allowed:
                raise RuleError(f'Opción inválida: {key}.')
        if round_no < 2 and (d['budget'] or d['content_budget']):
            raise RuleError('Las campañas se habilitan en la ronda 2.')
        if round_no < 3 and d['influencer'] != 'Ninguno':
            raise RuleError('Los influencers se habilitan en la ronda 3.')
        if round_no < 5 and (d['innovation'] or d['expand'] != 'Ninguna'):
            raise RuleError('Innovación y expansión se habilitan en la ronda 5.')
        if d['expand'] != 'Ninguna':
            market = cfg['markets'][d['expand']]
            if d['expand'] in b['markets']:
                raise RuleError('Esta marca ya participa en ese mercado.')
            # La calidad requerida debe existir al inicio, no se compra retroactivamente.
            if b['quality'] < market['min_quality']:
                raise RuleError(f"Necesitas calidad {market['min_quality']} para entrar en {d['expand']}.")
    if not isinstance(decision['sponsor'], str) or decision['sponsor'] not in SPONSORS or not isinstance(decision['studies'], list) or any(not isinstance(s, str) for s in decision['studies']):
        raise RuleError('Patrocinio o estudios inválidos.')
    if len(set(decision['studies'])) != len(decision['studies']) or any(s not in STUDIES for s in decision['studies']):
        raise RuleError('Estudios desconocidos o duplicados.')
    if round_no < 3 and decision['sponsor'] != 'Ninguno':
        raise RuleError('Los patrocinios se habilitan en la ronda 3.')
    cost = strategy_cost(decision, cfg)
    if cost + reserved > company['capital'] + .001:
        raise RuleError(f'Presupuesto insuficiente. Estrategia y alianzas: Bs {cost + reserved:,.0f}.')
    return deepcopy(decision)

def market_size(cfg, market, round_no):
    m = cfg['markets'][market]
    return int(m['size'] * (1 + m['growth']) ** (round_no - 1))

def round_rng(seed, round_no, cid, bid):
    h = hashlib.sha256(f'{seed}:{round_no}:{cid}:{bid}'.encode()).digest()
    return random.Random(int.from_bytes(h[:8], 'big'))

def simulate(companies, decisions, alliances, round_no, seed, cfg, target_id=None, sales_ledger=None):
    """Todas las empresas compiten juntas. No muta las entradas."""
    companies = deepcopy(companies)
    metrics = {}
    candidates = []
    alliance_by_company = {c['id']: [] for c in companies}
    for a in alliances:
        if a['round'] == round_no and a['status'] == 'accepted':
            alliance_by_company[a['from']].append(a)
            alliance_by_company[a['to']].append(a)
    for c in companies:
        if c['eliminated_round'] is not None:
            continue
        decision = decisions[c['id']]['strategy']
        sponsor = SPONSORS[decision['sponsor']]
        cost = strategy_cost(decision, cfg) + len(alliance_by_company[c['id']]) * cfg['alliance_cost']
        extra = set()
        cm = {'round': round_no, 'automatic': decisions[c['id']]['automatic'], 'brands': [],
              'revenue': 0., 'production': 0., 'spending': cost,
              'marketing': sum(d['budget'] + d['content_budget'] + INFLUENCERS[d['influencer']]['cost'] for d in decision['brands'])
                           + sponsor['cost'] + len(alliance_by_company[c['id']]) * cfg['alliance_cost'],
              'studies': deepcopy(decision['studies']), 'study_reports': {}, 'segment_units': {}, 'market_units': {},
              'innovation': sum(d['innovation'] for d in decision['brands'])}
        for b in c['brands']:
            d = next(d for d in decision['brands'] if d['id'] == b['id'])
            rng = round_rng(seed, round_no, c['id'], b['id'])
            seg = SEGMENTS.index(d['segment'])
            inf = INFLUENCERS[d['influencer']]
            platform = PLATFORMS[d['platform']]
            affinity = platform['affinity'][seg] * CONTENT_AFFINITY[d['content']][seg]
            campaign_key = f"{d['platform']}:{d['content']}:{d['segment']}"
            b['repeats'] = b['repeats'] + 1 if b['campaign_key'] == campaign_key and d['budget'] else 0
            b['campaign_key'] = campaign_key if d['budget'] else ''
            fatigue = 1 / (1 + .22 * b['repeats'])
            creativity = .45 + .55 * (1 - math.exp(-d['content_budget'] / 12000))
            paid = min(4200000., d['budget'] / platform['cpm'] * 1000) * fatigue
            creator_reach = inf['reach'] * inf['affinity'][seg]
            interactions = paid * .045 * creativity * affinity * b['reputation'] / 100
            interactions += creator_reach * inf['engagement'] * inf['credibility']
            organic = interactions * 4.5 * creativity * CONTENT_AFFINITY[d['content']][seg] * b['reputation'] / 100
            objective_reach = 1.15 if d['objective'] == 'Reconocimiento' else 1
            effective_reach = (paid * affinity + creator_reach * inf['credibility'] + organic) * objective_reach
            prior_awareness = b['awareness']
            b['awareness'] = clip(prior_awareness * cfg['awareness_decay'] + 24 * (1 - math.exp(-effective_reach / 800000))
                                  + 3 * sponsor['affinity'][seg] + 2 * len(alliance_by_company[c['id']]))
            b['quality'] = clip(b['quality'] + d['innovation'] / cfg['innovation_scale'])
            promised = 60 if d['attribute'] == 'Funcionalidad' else 45
            reputation_delta = .5 + (b['quality'] - promised) / 25
            reputation_delta += .8 if d['objective'] == 'Fidelización' and effective_reach > 0 else 0
            reputation_delta += .6 * inf['credibility'] * inf['affinity'][seg]
            # Pequeño riesgo reputacional acotado, no una lotería dominante.
            risk_loss = 2 if rng.random() < inf['risk'] else 0
            b['reputation'] = clip(b['reputation'] + reputation_delta - risk_loss)
            b.update(price=d['price'], segment=d['segment'], attribute=d['attribute'])
            if d['expand'] != 'Ninguna':
                b['markets'].append(d['expand'])
            extra.update(m for m in b['markets'] if m != 'VITAL')
            viral = clip(70 * organic / max(paid + creator_reach, 1) + 30 * interactions / max(paid + creator_reach, 1) / .08)
            b['viral'] = viral
            bm = {'id': b['id'], 'name': b['name'], 'units': 0, 'revenue': 0., 'production': 0.,
                  'paid_reach': round(paid), 'creator_reach': round(creator_reach), 'organic': round(organic),
                  'interactions': round(interactions), 'viral': viral, 'awareness': b['awareness'],
                  'reputation': b['reputation'], 'quality': b['quality'], 'fatigue': fatigue,
                  'market_units': {}, 'market_segment_units': {}, 'market_revenue': {}, 'market_production': {}, 'market_share': {}, 'segment_units': {}, 'price': d['price'], 'risk_loss': risk_loss}
            cm['brands'].append(bm)
            # Alianzas compatibles tienen mayor efecto; cada empresa mantiene su contabilidad.
            alliance_bonus = 0
            for a in alliance_by_company[c['id']]:
                other_id = a['to'] if a['from'] == c['id'] else a['from']
                other_d = decisions[other_id]['strategy']['brands']
                compatible = any(x['segment'] == d['segment'] for x in other_d)
                alliance_bonus += cfg['alliance_lift'] * (1 if compatible else .55)
            lift = 1 - math.exp(-effective_reach / 700000)
            conversion_boost = 1.10 if d['objective'] in ('Conversión', 'Intención de compra') and effective_reach else 1
            noise = rng.uniform(1 - cfg['random_variation'], 1 + cfg['random_variation'])
            candidates.append((c, b, d, bm, lift, conversion_boost, alliance_bonus, noise))
        cm['operating'] = cfg['operating_cost'] + cfg['extra_market_operating'] * len(extra)
        metrics[c['id']] = cm
    market_totals = {}
    target_used = {}
    for market in cfg['markets']:
        size = market_size(cfg, market, round_no)
        market_totals[market] = {'available': size, 'sold': 0}
        market_candidates = [x for x in candidates if market in x[1]['markets']]
        for s, fraction in enumerate(cfg['segment_weights']):
            demand = int(size * fraction)
            utilities = []
            for c, b, d, bm, lift, conversion_boost, alliance_bonus, noise in market_candidates:
                price_ratio = d['price'] / cfg['markets']['VITAL']['reference_price']
                price_fit = math.exp(-cfg['price_sensitivity'][s] * (price_ratio - 1))
                target = 1.30 if d['segment'] == SEGMENTS[s] else .70
                attribute_fit = 1.20 if d['attribute'] == ATTRIBUTES[s] else .85
                quality = .55 + b['quality'] / 100 * (1.0 if s in (0, 3) else .6)
                trust = .50 + b['reputation'] / 100
                visibility = .30 + b['awareness'] / 100 + .7 * lift
                utility = price_fit * target * attribute_fit * quality * trust * visibility * conversion_boost * (1 + alliance_bonus) * noise
                utilities.append(utility)
            denominator = sum(utilities) + cfg['outside_option']
            for x, utility in zip(market_candidates, utilities):
                c, b, d, bm, *_ = x
                units = int(demand * utility / denominator)
                if target_id == c['id']:
                    already = (sales_ledger or {}).get(market, {}).get(SEGMENTS[s], 0)
                    used = target_used.setdefault(market, {}).get(SEGMENTS[s], 0)
                    units = min(units, max(0, demand - already - used))
                    target_used[market][SEGMENTS[s]] = used + units
                bm['market_segment_units'].setdefault(market, {})[SEGMENTS[s]] = units
                mp = cfg['markets'][market]
                price = round(mp['reference_price'] * d['price'] / cfg['markets']['VITAL']['reference_price'], 2)
                unit_cost = mp['unit_cost'] * (1 + max(0, b['quality'] - 50) * .004)
                bm['units'] += units
                bm['revenue'] += units * price
                bm['production'] += units * unit_cost
                bm['market_revenue'][market] = bm['market_revenue'].get(market, 0) + units * price
                bm['market_production'][market] = bm['market_production'].get(market, 0) + units * unit_cost
                bm['market_units'][market] = bm['market_units'].get(market, 0) + units
                bm['segment_units'][SEGMENTS[s]] = bm['segment_units'].get(SEGMENTS[s], 0) + units
                metrics[c['id']]['segment_units'][SEGMENTS[s]] = metrics[c['id']]['segment_units'].get(SEGMENTS[s], 0) + units
                metrics[c['id']]['market_units'][market] = metrics[c['id']]['market_units'].get(market, 0) + units
                market_totals[market]['sold'] += units
    for c in companies:
        if c['id'] not in metrics:
            continue
        cm = metrics[c['id']]
        for bm in cm['brands']:
            for m, units in bm['market_units'].items():
                bm['market_share'][m] = 100 * units / max(market_totals[m]['sold'], 1)
            bm['revenue'] = round(bm['revenue'], 2)
            bm['production'] = round(bm['production'], 2)
            contacts = bm['paid_reach'] + bm['creator_reach'] + bm['organic']
            bm['conversion'] = min(1, bm['units'] / max(contacts, bm['units'], 1)) if contacts else 0
            cm['revenue'] += bm['revenue']
            cm['production'] += bm['production']
        cm['revenue'] = round(cm['revenue'], 2)
        cm['production'] = round(cm['production'], 2)
        cm['profit'] = round(cm['revenue'] - cm['production'] - cm['operating'] - cm['spending'], 2)
        cm['capital'] = round(c['capital'] + cm['profit'], 2)
        c['capital'] = cm['capital']
        for key in ('profit', 'revenue', 'marketing', 'innovation'):
            c[key] = round(c[key] + cm[key], 2)
        if c['capital'] <= 0:
            c['eliminated_round'] = round_no
        cm['market_share'] = {m: 100 * u / max(market_totals[m]['sold'], 1) for m, u in cm['market_units'].items()}
        for study in cm['studies']:
            if study == 'Encuesta de consumidores':
                report = {'mis_segmentos_unidades': cm['segment_units'], 'recuerdo_mis_marcas': {b['name']: round(b['awareness'], 1) for b in c['brands']}}
            elif study == 'Mapa de posicionamiento':
                report = {'mis_marcas': [{'marca': b['name'], 'segmento': b['segment'], 'atributo': b['attribute'], 'calidad': b['quality']} for b in c['brands']], 'ideales': dict(zip(SEGMENTS, ATTRIBUTES))}
            elif study == 'Pronóstico de mercado':
                report = {m: {'demanda_actual': market_size(cfg, m, round_no), 'crecimiento': v['growth']} for m, v in cfg['markets'].items()}
            elif study == 'Test de contenido':
                report = {s: {k: v[i] for k, v in CONTENT_AFFINITY.items()} for i, s in enumerate(SEGMENTS)}
            else:
                report = {m: {k: v for k, v in cfg['markets'][m].items() if k in ('entry', 'min_quality', 'reference_price', 'unit_cost', 'growth')} for m in ('ACTIVE', 'TECH')}
            cm['study_reports'][study] = report
        c['history'].append(cm)
    return companies, market_totals

def indicators(company, companies, cfg):
    initial = cfg['initial_capital']
    revenue_total = sum(c['revenue'] for c in companies)
    share = company['revenue'] / max(revenue_total, 1)
    bs = company['brands']
    history = company['history']
    positive_capital = max(0, company['capital'])
    F = 100 * positive_capital / (positive_capital + initial)
    C = clip(350 * share)
    M = sum(.6 * b['awareness'] + .4 * b['reputation'] for b in bs) / len(bs)
    V = sum(hb['viral'] for h in history for hb in h['brands']) / max(len(history) * len(bs), 1)
    # Piso de 20.000 para evitar infinito y premiar beneficios sin gasto artificial.
    efficiency_base = 3 * max(company['marketing'], 20000)
    E = 50 + 50 * company['profit'] / (abs(company['profit']) + efficiency_base) if history else 50
    quality_gain = sum(max(0, b['quality'] - 50) for b in bs) / len(bs)
    profitable_extra = 0
    for m in ('ACTIVE', 'TECH'):
        participating = sum(m in b['markets'] for b in bs)
        margin = sum(bh.get('market_revenue', {}).get(m, 0) - bh.get('market_production', {}).get(m, 0) for h in history for bh in h['brands'])
        operating = cfg['extra_market_operating'] * sum(m in h['market_units'] for h in history)
        if participating and margin > cfg['markets'][m]['entry'] * participating + operating:
            profitable_extra += 1
    D = clip(2 * quality_gain + 20 * profitable_extra)
    values = [F, C, M, V, E, D]
    score = sum(v * w for v, w in zip(values, cfg['idv_weights']))
    return dict(zip(('F', 'C', 'M', 'V', 'E', 'D'), values), idv=score)

def ranking(companies, cfg):
    rows = [dict(id=c['id'], name=c['name'], capital=c['capital'], profit=c['profit'],
                 eliminated_round=c['eliminated_round'], **indicators(c, companies, cfg)) for c in companies]
    def key(r):
        return (r['eliminated_round'] is None, r['eliminated_round'] or 99,
                round(r['idv'], 6), round(r['F'], 6), round(r['C'], 6), round(r['M'], 6))
    rows.sort(key=key, reverse=True)
    previous = None
    for i, row in enumerate(rows, 1):
        k = key(row)
        row['position'] = previous['position'] if previous and k == key(previous) else i
        previous = row
    return rows
