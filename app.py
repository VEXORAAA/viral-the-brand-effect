"""VIRAL — The Brand Effect. Entrada de Streamlit."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
import os
import json
import logging
from copy import deepcopy
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from dotenv import load_dotenv
from viral.config import (COMPANIES, MISSIONS, SEGMENTS, ATTRIBUTES, CONTENTS,
                          OBJECTIVES, PLATFORMS, INFLUENCERS, SPONSORS, STUDIES, influencer_options)
from viral.engine import RuleError, conservative, strategy_cost
from viral.storage import Store
from viral.service import GameService, AccessError, independent
from viral.report import final_pdf, activity_pdf

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
st.set_page_config(page_title='VIRAL · The Brand Effect', page_icon='⚡', layout='wide', initial_sidebar_state='collapsed')
st.markdown('<style>' + (ROOT / 'assets/style.css').read_text(encoding='utf-8-sig') + '</style>', unsafe_allow_html=True)

def money(value):
    return f'Bs {value:,.0f}'.replace(',', '.')

def local_date(value):
    return datetime.fromtimestamp(value, ZoneInfo('America/La_Paz')).strftime('%d/%m/%Y %H:%M')

def setting(name, default=''):
    value = os.getenv(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, default))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return default

@st.cache_resource
def service(path, url, password, pin_key, revision='history-view-v8'):
    return GameService(Store(path, url), password, pin_key=pin_key or None)

try:
    url = setting('DATABASE_URL')
    if setting('VIRAL_ENV', 'local') == 'production' and not url:
        raise RuleError('En producción configura DATABASE_URL para conservar la partida en Supabase.')
    db_path = Path(setting('VIRAL_DB_PATH', 'data/viral.sqlite3'))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    svc = service(str(db_path), url, setting('VIRAL_ADMIN_PASSWORD'), setting('VIRAL_PIN_ENCRYPTION_KEY'))
except RuleError as exc:
    st.title('⚡ VIRAL')
    st.info(str(exc))
    st.code('python scripts/preparar_local.py\nstreamlit run app.py', language='bash')
    st.caption('En local, la clave se guarda en data/ACCESO_LOCAL.txt. En Cloud usa Secrets. Consulta README.md.')
    st.stop()
except Exception:
    st.title('⚡ VIRAL')
    st.error('No se pudo conectar al almacenamiento. Revisa DATABASE_URL y ejecuta sql/schema.sql en Supabase.')
    st.stop()

def do(action, success=None):
    try:
        value = action()
        if success:
            st.session_state['flash'] = success
        return value
    except (RuleError, AccessError, ValueError) as exc:
        st.error(str(exc))
    except Exception:
        st.error('No se pudo guardar la operación. Revisa la conexión y vuelve a intentarlo; no se repetirá el cierre de ronda.')
    return None

def header(tag):
    st.markdown(f'<div class="topline"><div class="wordmark">VIRAL<small>THE BRAND EFFECT</small></div><div class="pill">{escape(tag)}</div></div>', unsafe_allow_html=True)

def signature(g):
    decisions = g.get('decisions', {}).get(str(g['round']), {})
    own = g.get('company', {}).get('progress', {})
    groups = tuple((c['id'],c.get('progress',{}).get('round'),c.get('progress',{}).get('status'),len(c['history'])) for c in g.get('companies',[]))
    return (g['status'],g['round'],len(decisions),g.get('stage'),own.get('status'),groups,tuple((a['id'],a['status']) for a in g['alliances']))

@st.fragment(run_every='2s')
def ticker(token,gid,initial):
    try:
        fresh=svc.view(token,gid)
        if signature(fresh)!=initial:st.rerun()
        status=fresh['status']
        if independent(fresh):
            remaining=max(0,int((fresh.get('stage_deadline') or fresh['server_now'])-fresh['server_now']))
            if 'company' in fresh:
                p=fresh['company']['progress']
                if status=='running' and p['status']=='running':
                    seconds=max(0,int(p['deadline']-fresh['server_now']))
                    text,time_text=f"Tu ronda {p['round']} de 8",f'{seconds//60:02}:{seconds%60:02}'
                else:
                    text={'between':'Ronda terminada. Puedes continuar con la siguiente.', 'paused':'Terminaste esta etapa.', 'finished':'Tu recorrido terminó.', 'eliminated':'Puedes revisar tus resultados.', 'waiting':'Tu grupo está listo para empezar.'}.get(p['status'],'Tu grupo')
                    time_text='PAUSA' if status=='paused' else 'LISTO'
            else:
                text,time_text=(f"Etapa {fresh['stage']} · límite total",f'{remaining//60:02}:{remaining%60:02}') if status!='ready' else ('Primera etapa · 90 minutos','SIN INICIAR')
            st.markdown(f'<div class="timer"><span>{text}</span><strong>{time_text}</strong></div>',unsafe_allow_html=True)
            if status=='running':st.caption(f"Etapa {fresh['stage']}: quedan {remaining//60} min {remaining%60:02} s del bloque total. Cada grupo tiene su propio avance.")
            elif status=='paused':st.info('La primera etapa está cerrada. El administrador dará inicio a la segunda.')
            return
        if status=='running':
            seconds=max(0,int(fresh['rounds'][-1]['deadline']-fresh['server_now']))
            text,time_text=f"RONDA {fresh['round']} / 8",f'{seconds//60:02}:{seconds%60:02}'
        else:
            text={'ready':'Sala lista · esperando el inicio','paused':'Primera etapa terminada','finished':'Partida finalizada'}[status]
            time_text={'ready':'EN ESPERA','paused':'PAUSA','finished':'FINAL'}[status]
        st.markdown(f'<div class="timer"><span>{text}</span><strong>{time_text}</strong></div>',unsafe_allow_html=True)
    except AccessError:
        st.session_state.pop('token',None);st.rerun()
    except Exception:st.warning('Reconectando… Tus decisiones guardadas siguen disponibles.')


def lobby():
    header('7 GRUPOS / 8 RONDAS / UNA HUELLA')
    st.markdown('<div class="hero"><div class="eyebrow">ESTRATEGIA · CREATIVIDAD · COMPETENCIA</div><h1>TU PRÓXIMA JUGADA<br>PUEDE <em>CAMBIARLO TODO.</em></h1><p>Construye marcas que conectan. Toma decisiones que cuentan.<br>Bienvenido al mercado: tu historia empieza aquí.</p></div>', unsafe_allow_html=True)
    player, admin = st.tabs(['⚡ Entrar a jugar', 'Administración'])
    with player:
        info = svc.public_lobby()
        if info['status'] == 'empty':
            st.info('El administrador está preparando la partida. Aquí aparecerán tus empresas.')
        else:
            st.caption(f"{info['name']} · Selecciona tu grupo e ingresa con tu PIN.")
        with st.form('player_login'):
            selected=st.radio('Tu grupo',list(map(str,range(7))),format_func=lambda x:COMPANIES[int(x)][0],horizontal=True,key='group_picker')
            pin=st.text_input('PIN del grupo',type='password',max_chars=4,placeholder='4 dígitos')
            if st.form_submit_button('Entrar a mi grupo',type='primary',use_container_width=True,disabled=info['status']=='empty'):
                token=do(lambda:svc.login('player',pin,selected))
                if token:
                    st.session_state.update(token=token,role='player');st.rerun()
    with admin:
        st.caption('Controla los tiempos, supervisa las empresas y descarga el reporte final.')
        with st.form('admin_login'):
            password = st.text_input('Clave de administración', type='password', max_chars=128)
            if st.form_submit_button('Abrir panel administrativo', type='primary'):
                token = do(lambda: svc.login('admin', password))
                if token:
                    st.session_state.update(token=token, role='admin')
                    st.rerun()
    if not url:
        st.caption('Modo local · la partida se guarda en este equipo. Para jugar desde distintas redes, publica con Supabase y Streamlit Cloud.')


def show_ranking(g):
    rows = g['ranking']
    winners = ', '.join(r['name'] for r in rows if r['position'] == 1)
    st.markdown(f'<div class="mission"><div class="eyebrow">LA HUELLA QUE DEJARON</div><h2>{escape(winners)}</h2><p>Primer puesto · IDV {rows[0]["idv"]:.2f} / 100</p></div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([{'Puesto': r['position'], 'Grupo': r['name'], 'IDV': round(r['idv'],2), 'Capital': money(r['capital']), 'Estado': f"Eliminada R{r['eliminated_round']}" if r['eliminated_round'] else 'Activa'} for r in rows]), hide_index=True, use_container_width=True)


def show_study(title,data):
    st.markdown('**'+title+'**')
    if title=='Encuesta de consumidores':
        st.caption('Compara a qué públicos llegaste y cuánto recuerdan tus marcas.')
        st.dataframe(pd.DataFrame([{'Público':k,'Unidades vendidas':v} for k,v in data['mis_segmentos_unidades'].items()]),hide_index=True,use_container_width=True)
        st.dataframe(pd.DataFrame([{'Marca':k,'Recuerdo %':v} for k,v in data['recuerdo_mis_marcas'].items()]),hide_index=True,use_container_width=True)
    elif title=='Mapa de posicionamiento':
        st.caption('Revisa cómo se diferencia cada una de tus marcas.')
        st.dataframe(pd.DataFrame(data['mis_marcas']).rename(columns={'marca':'Marca','segmento':'Público','atributo':'Promesa','calidad':'Calidad'}),hide_index=True,use_container_width=True)
    elif title=='Pronóstico de mercado':
        st.caption('Estos valores simulados te ayudan a anticipar el tamaño de cada mercado.')
        st.dataframe(pd.DataFrame([{'Mercado':k,'Demanda actual':v['demanda_actual'],'Crecimiento esperado %':round(v['crecimiento']*100,1)} for k,v in data.items()]),hide_index=True,use_container_width=True)
    elif title=='Test de contenido':
        st.caption('Un porcentaje mayor indica que el contenido encaja mejor con ese público.')
        table=pd.DataFrame(data)*100;table.index.name='Contenido'
        st.dataframe(table.reset_index(),hide_index=True,use_container_width=True)
    elif title=='Estudio de expansión':
        st.caption('Compara el costo de entrada y la calidad necesaria antes de crecer.')
        st.dataframe(pd.DataFrame([{'Mercado':k,'Entrada Bs':v['entry'],'Calidad mínima':v['min_quality'],'Precio de referencia Bs':v['reference_price'],'Costo por producto Bs':v['unit_cost']} for k,v in data.items()]),hide_index=True,use_container_width=True)

def history(company):
    st.subheader(f"Resultados de {company['name']}")
    if not company['history']:
        st.info(f"{company['name']} todavía no tiene rondas completadas. Los resultados aparecerán al terminar su primera ronda.")
        return
    hist = sorted(company['history'],key=lambda h:h['round'])
    latest = hist[-1]
    st.caption(f"{len(hist)} rondas completadas · Último cierre: ronda {latest['round']} · " + ('Estrategia automática por falta de envío' if latest['automatic'] else 'Estrategia confirmada'))
    st.caption('Cada fila corresponde a una ronda terminada de este grupo. Los datos se actualizan al cerrar su ronda.')
    table=pd.DataFrame([{'Ronda': h['round'], 'Ingresos': h['revenue'], 'Producción': h['production'], 'Operación': h['operating'], 'Inversiones': h['spending'], 'Ganancia de la ronda': h['profit'], 'Dinero al cierre': h['capital'], 'Envío': 'Automático' if h['automatic'] else 'Confirmado'} for h in hist])
    st.dataframe(table,hide_index=True,use_container_width=True,column_config={name:st.column_config.NumberColumn(name,format='localized',help='Importe en bolivianos') for name in ['Ingresos','Producción','Operación','Inversiones','Ganancia de la ronda','Dinero al cierre']},key=f"history_table_{company['id']}")
    metric=st.selectbox('Qué quieres ver en la gráfica',['Dinero disponible','Ganancia por ronda','Ingresos por ventas'],key=f"history_metric_{company['id']}",filter_mode=None)
    field={'Dinero disponible':'capital','Ganancia por ronda':'profit','Ingresos por ventas':'revenue'}[metric]
    x=[h['round'] for h in hist];y=[h[field] for h in hist]
    if field=='capital':
        x=[0]+x;y=[hist[0]['capital']-hist[0]['profit']]+y
    fig=go.Figure(go.Scatter(x=x,y=y,mode='lines+markers',line=dict(color=company.get('color','#b58aff'),width=3),name=metric,hovertemplate='Ronda %{x}<br>Bs %{y:,.2f}<extra></extra>'))
    fig.update_layout(title=f"{company['name']} · {metric}",template='plotly_dark',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',height=300,margin=dict(l=0,r=10,t=45,b=10),xaxis=dict(title='Ronda · 0 = inicio',tickmode='array',tickvals=x) if field=='capital' else dict(title='Ronda',tickmode='array',tickvals=x),yaxis=dict(title='Bolivianos (Bs)',tickformat=',.0f'),showlegend=False)
    st.plotly_chart(fig,use_container_width=True,key=f"history_chart_{company['id']}_{field}",config={'displayModeBar':True,'displaylogo':False})
    st.caption('Dinero disponible muestra tu saldo total. Ganancia por ronda muestra lo que quedó de las ventas después de pagar productos, operación e inversiones.')
    with st.expander('Métricas de mis marcas'):
        st.dataframe(pd.DataFrame([{'Marca': b['name'], 'Unidades': b['units'], 'Ingresos': money(b['revenue']), 'Recuerdo %': round(b['awareness'],1), 'Reputación': round(b['reputation'],1), 'Viralidad': round(b['viral'],1), 'Alcance pagado': b['paid_reach'], 'Orgánico': b['organic'], 'Interacciones': b['interactions'], 'Conversión observada %': round(b['conversion']*100,2), 'Efectividad por fatiga %': round(b['fatigue']*100,1)} for b in latest['brands']]), hide_index=True, use_container_width=True)
    for h in hist:
        if h['study_reports']:
            with st.expander(f"VIRAL Insights · estudios de la ronda {h['round']}"):
                for title, data in h['study_reports'].items():
                    show_study(title,data)


def alliance_ui(g, token):
    n, cid = g['round'], g['company']['id']
    if n < 4 or g['status'] != 'running' or g['company']['eliminated_round']:
        return
    with st.expander('🤝 Alianzas · una colaboración por ronda'):
        st.caption(f"Costo por empresa: {money(g['rules']['alliance_cost'])}. Se reserva al proponer y se cobra solo si aceptan. Contrato de una ronda; sin exclusividad de influencers.")
        active = [a for a in g['alliances'] if a['round'] == n and a['status'] in ('pending', 'accepted')]
        names = {str(i): c[0] for i,c in enumerate(COMPANIES)}
        for a in active:
            st.write(f"{names[a['from']]} + {names[a['to']]} · " + ('Aceptada' if a['status']=='accepted' else 'Pendiente'))
            if a['to'] == cid and a['status'] == 'pending':
                choice = st.radio('Tu respuesta', ['Aceptar', 'Rechazar'], key=f"reply_{a['id']}", horizontal=True)
                if st.button('Responder propuesta', key=f"respond_{a['id']}"):
                    result = do(lambda: (svc.respond(token,n,a['id'],choice=='Aceptar'),True)[1], 'Respuesta guardada.')
                    if result:
                        st.rerun()
        if not any(a['from'] == cid or a['status'] == 'accepted' for a in active):
            candidates=[x['id'] for x in g.get('alliance_candidates',[])] if independent(g) else [x for x in names if x!=cid]
            if not candidates:
                st.caption('Todavía no hay otro grupo trabajando en tu misma ronda para colaborar.');return
            other = st.selectbox('Grupo con el que quieres colaborar',candidates,format_func=lambda x:names[x])
            if st.button('Proponer colaboración'):
                if do(lambda:svc.propose(token,n,other), 'Propuesta enviada; el presupuesto quedó reservado.'):
                    st.rerun()
        st.caption('Si no hay una estrategia enviada, proponer o aceptar confirma una estrategia conservadora. Puedes editarla antes del cierre.')


def strategy_ui(g,token):
    c,n=g['company'],g['round']
    saved=g['my_decision'];decision=saved['strategy'] if saved else conservative(c)
    personal=independent(g)
    if not personal and saved:st.success('Estrategia guardada. Puedes ajustarla hasta el cierre.')
    st.caption('Elige tus decisiones y termina esta ronda. Solo avanzará tu grupo.' if personal else 'Elige tus decisiones y confirma para guardarlas.')
    if n>=4:alliance_ui(g,token)
    st.caption(f"Puedes invertir {money(c['capital']-g['reserved'])}. Las colaboraciones ya acordadas reservan {money(g['reserved'])}.")
    core={1:{'position'},2:{'campaign'},3:{'influencer'},4:set(),5:{'innovation'},6:{'position','campaign'},7:{'campaign','influencer'},8:{'position'}}[n]
    unlocked={'position'}|({'campaign'} if n>=2 else set())|({'influencer'} if n>=3 else set())|({'innovation'} if n>=5 else set())
    titles={'position':'Precio y público','campaign':'Tu campaña','influencer':'Una voz para tu marca','innovation':'Mejora y crecimiento'}
    edited=[]
    def fields(d,b,prefix,features):
        if 'position' in features:
            st.caption('Decide a quién vender, qué ofrecer y cuánto cobrar.')
            d['segment']=st.selectbox('Público al que quieres llegar',SEGMENTS,index=SEGMENTS.index(d['segment']),key=prefix+'_segment')
            d['attribute']=st.selectbox('Lo que ofrece tu marca',ATTRIBUTES,index=ATTRIBUTES.index(d['attribute']),key=prefix+'_attribute')
            d['price']=st.number_input('Precio de venta (Bs)',5.,45.,float(d['price']),.5,key=prefix+'_price',help='Un precio mayor deja más margen, pero puede alejar a tus compradores.')
        if 'campaign' in features:
            st.caption('Elige dónde anunciarte y cuánto gastar para llegar a tu público.')
            d['platform']=st.selectbox('Dónde aparecerá tu anuncio',list(PLATFORMS),index=list(PLATFORMS).index(d['platform']),key=prefix+'_platform')
            d['content']=st.selectbox('Tipo de publicación',CONTENTS,index=CONTENTS.index(d['content']),key=prefix+'_content')
            d['objective']=st.selectbox('Qué quieres conseguir',OBJECTIVES,index=OBJECTIVES.index(d['objective']),key=prefix+'_objective')
            d['budget']=st.number_input('Dinero para anuncios (Bs)',0.,500000.,float(d['budget']),100.,key=prefix+'_budget',help='Puedes escribir el monto exacto. Los botones suman o restan Bs 100; no hay inversión mínima.')
            d['content_budget']=st.number_input('Dinero para crear contenido (Bs)',0.,100000.,float(d['content_budget']),100.,key=prefix+'_creative',help='Ayuda a crear publicaciones más atractivas. Es un gasto adicional a los anuncios.')
        if 'influencer' in features:
            st.caption('Nombres reales; costos y alcance simulados para esta actividad, sin vínculo comercial.')
            st.caption('Un creador puede recomendar tu marca. Elige por afinidad con tu público, no solo por seguidores.')
            options=influencer_options(d['influencer'])
            d['influencer']=st.selectbox('Quién recomendará tu marca',options,index=options.index(d['influencer']),format_func=lambda x:f'{x} · {money(INFLUENCERS[x]["cost"])}',key=prefix+'_creator')
        if 'innovation' in features:
            st.caption(f"Calidad actual: {b['quality']:.2f} de 100. La mejora se aplica al terminar tu ronda.")
            d['innovation']=st.number_input('Mejorar el producto (Bs)',0.,float(g['rules']['max_innovation']),float(d['innovation']),100.,key=prefix+'_innovation',help='Puedes escribir el monto exacto. Bs 6.000 mejoran un punto de calidad; una cantidad menor mejora una fracción.')
            options=['Ninguna']+[m for m in ('ACTIVE','TECH') if m not in b['markets'] and b['quality']>=g['rules']['markets'][m]['min_quality']]
            d['expand']=st.selectbox('Vender también en otro mercado',options,index=options.index(d['expand']) if d['expand'] in options else 0,format_func=lambda x:x if x=='Ninguna' else f'{x} · {money(g["rules"]["markets"][x]["entry"])}',key=prefix+'_expand',disabled=len(options)==1,help='Es opcional. Puedes seguir vendiendo en tu mercado actual. La expansión requiere calidad suficiente al comenzar la ronda y dinero para pagar la entrada.')
            st.caption('La expansión es opcional: puedes dejar «Ninguna» y seguir vendiendo en tu mercado actual.')
            for market in ('ACTIVE','TECH'):
                rule=g['rules']['markets'][market]
                if market in b['markets']:
                    st.caption(f'✓ {market}: tu marca ya vende en este mercado.')
                elif b['quality'] < rule['min_quality']:
                    from math import ceil
                    needed=ceil((rule['min_quality']-b['quality'])*g['rules']['innovation_scale'])
                    timing='Podrás elegirlo en una ronda posterior, después de aplicar la mejora.' if n<8 else 'Esta es la última ronda: ya no habrá otra para expandirte después de mejorar.'
                    st.caption(f"🔒 {market}: requiere calidad {rule['min_quality']}. Mejora pendiente: {money(needed)}. {timing} Entrada adicional: {money(rule['entry'])} por marca.")
                else:
                    st.caption(f"✓ {market} disponible · entrada: {money(rule['entry'])} por marca. El gasto se valida con tu presupuesto al terminar.")
        return d
    with st.form(f'strategy_{g["id"]}_{c["id"]}_{n}'):
        for i,b in enumerate(c['brands']):
            d=deepcopy(next(x for x in decision['brands'] if x['id']==b['id']))
            prefix=f'{g["id"]}_{c["id"]}_{n}_{b["id"]}'
            if core:
                with st.expander(f"{b['name']} · {' / '.join(titles[k] for k in sorted(core))}",expanded=i==0):
                    d=fields(d,b,prefix,core)
                    if 'position' not in core:st.caption(f"Mantienes el precio de {money(d['price'])} y el público {d['segment']}.")
            else:st.caption(f"{b['name']} · precio {money(d['price'])} · público {d['segment']}")
            edited.append(d)
        optional=unlocked-core
        if optional:
            with st.expander('Ajustes de rondas anteriores · opcional'):
                st.caption('Estas decisiones siguen disponibles. Modifícalas solo si ayudan a tu estrategia actual.')
                for i,b in enumerate(c['brands']):
                    st.markdown('**'+b['name']+'**')
                    edited[i]=fields(edited[i],b,f'{g["id"]}_{c["id"]}_{n}_{b["id"]}',optional)
        sponsor='Ninguno';studies=decision['studies']
        with st.expander('Apoyo para tu estrategia · opcional'):
            if n<3:st.info('🔒 El patrocinio se habilitará a partir de la ronda 3.')
            else:st.caption('Elige un evento o una campaña conjunta con una empresa presente en Bolivia. Pagas el costo mostrado para dar a conocer tus marcas.')
            st.caption('Las campañas con empresas son ficticias; los costos y efectos son educativos.')
            sponsor=st.selectbox('Patrocinio',list(SPONSORS),index=list(SPONSORS).index(decision['sponsor']),disabled=n<3,format_func=lambda x:f'{x} · {money(SPONSORS[x]["cost"])}',key=f'{g["id"]}_{c["id"]}_{n}_sponsor')
            st.caption('Comprar un estudio te ayuda a decidir. Lo recibirás al terminar tu ronda.')
            studies=st.multiselect('Información de mercado',list(STUDIES),default=studies,format_func=lambda x:f'{x} · {money(STUDIES[x])}',key=f'{g["id"]}_{c["id"]}_{n}_studies')
        st.caption('Revisa el gasto antes de terminar. Las decisiones confirmadas se aplican una sola vez.' if personal else 'Confirmar guarda tus decisiones. Puedes modificarlas hasta el cierre.')
        if st.form_submit_button('Terminar mi ronda →' if personal else 'Confirmar estrategia →',type='primary',use_container_width=True):
            new=dict(brands=edited,sponsor=sponsor,studies=studies)
            action=lambda:(svc.complete_round(token,n,new),True)[1] if personal else (svc.submit(token,n,new),True)[1]
            if do(action,'Tu ronda terminó. Los resultados están guardados.' if personal else 'Estrategia guardada.'):st.rerun()
    future=[('Campañas',2),('Creadores y patrocinio',3),('Alianzas',4),('Mejoras y nuevos mercados',5)]
    locked=[f'<div>🔒 <b>{label}</b><br><span>Se habilita en tu ronda {unlock}</span></div>' for label,unlock in future if n<unlock]
    if locked:st.markdown('<div class="unlock-strip">'+''.join(locked)+'</div>',unsafe_allow_html=True)


def help_panel(g):
    st.markdown('**Tu objetivo:** construye una empresa rentable y marcas relevantes durante ocho rondas. No gana necesariamente quien más vende o más invierte.')
    with st.expander('Reglas de la partida'):
        st.write('Cada grupo tiene 15 minutos por ronda. El reloj comienza al entrar a esa ronda. Los demás grupos no avanzan por tus acciones. La primera etapa tiene un límite total de 90 minutos y la segunda de 30 minutos. Al terminar el tiempo de una ronda iniciada, se aplica una estrategia conservadora si faltó tu envío. Las rondas que nunca empezaste no avanzan solas durante la etapa.')
        st.write('El ranking se publica al finalizar. IDV: finanzas 30%, competitividad 20%, marca 15%, viralidad 15%, eficiencia 10%, desarrollo 10%.')
        st.write('Los contratos de influencers no son exclusivos, duran una ronda y pueden renovarse. Cada alianza cuesta Bs 18.000 por empresa, requiere aceptación y dura una ronda.')
        st.write('Las ventas están limitadas por la demanda. La inversión creativa favorece la interacción, pero no garantiza ventas. Repetir plataforma, segmento y contenido causa fatiga.')
    with st.expander('Catálogos para decidir'):
        st.write('**Dónde anunciarte** · compara el costo y qué público encaja mejor con cada plataforma.')
        st.dataframe(pd.DataFrame([{'Plataforma':k,'Precio por 1.000 vistas (Bs)':v['cpm'],**dict(zip(SEGMENTS,v['affinity']))} for k,v in PLATFORMS.items()]),hide_index=True,use_container_width=True)
        st.write('**Creadores reales** · nombres consultados en fuentes públicas. Costos, alcance, afinidades e interacción son valores simulados; no representan tarifas, seguidores ni evaluaciones personales. El riesgo es un evento aleatorio del juego, igual para todos los perfiles reales.')
        st.dataframe(pd.DataFrame([{'Perfil':k,'Costo Bs':v['cost'],'Alcance':v['reach'],'Credibilidad':v['credibility'],'Interacción':v['engagement'],'Riesgo':v['risk'],**dict(zip(SEGMENTS,v['affinity']))} for k,v in INFLUENCERS.items() if k!='Ninguno' and k in influencer_options()]),hide_index=True,use_container_width=True)
        st.write('**Patrocinios** · campañas hipotéticas; no hay acuerdos comerciales con las empresas mencionadas.')
        st.dataframe(pd.DataFrame([{'Opción':k,'Costo simulado Bs':v['cost'],'Actividad':v.get('topic','Evento temático'),**dict(zip(SEGMENTS,v['affinity']))} for k,v in SPONSORS.items() if k!='Ninguno']),hide_index=True,use_container_width=True)
    with st.expander('Boletín de la ronda'):
        st.write('Los tamaños y afinidades son parámetros estables de esta partida. El crecimiento es simulado, sin conexión a mercados reales.')
        st.dataframe(pd.DataFrame([{'Mercado':m,'Demanda inicial':v['size'],'Crecimiento por ronda %':v['growth']*100,'Precio referencia Bs':v['reference_price'],'Costo unitario base Bs':v['unit_cost'],'Entrada por marca Bs':v['entry']} for m,v in g['rules']['markets'].items()]),hide_index=True,use_container_width=True)
        st.caption('El costo unitario aumenta 0,4% por punto de calidad superior a 50. Operación: Bs 22.000 por ronda + Bs 12.000 por mercado adicional. Se produce contra ventas, sin inventario ni deuda.')
    st.download_button('Descargar manual del participante',data=(ROOT/'referencias/Manual_VIRAL_The_Brand_Effect.pdf').read_bytes(),file_name='Manual_VIRAL.pdf',mime='application/pdf')


def player_dashboard(token):
    g=svc.view(token);c=g['company'];personal=independent(g)
    header(c['name']);ticker(token,g['id'],signature(g))
    own=c.get('progress',{})
    if g['status']=='running' and (not personal or own['status']=='running'):
        title,mission=MISSIONS[g['round']-1]
        st.markdown(f'<div class="mission"><div class="eyebrow">TU RONDA {g["round"]} / 8</div><h2>{title}</h2><p>{mission}</p></div>',unsafe_allow_html=True)
    if personal:st.caption(f"Tu grupo completó {len(c['history'])} de 8 rondas. Los demás grupos tienen su propio avance.")
    left,right=st.columns(2);left.metric('Dinero disponible',money(c['capital']));right.metric('Ganancia acumulada',money(c['profit']))
    if c['eliminated_round']:st.warning(f"Tu grupo fue eliminado en la ronda {c['eliminated_round']}. Puedes consultar tus resultados.")
    if g['status']=='finished':show_ranking(g)
    strategy,results,guide=st.tabs(['Mi ronda','Mis resultados','Cómo jugar'])
    with strategy:
        if personal:
            if g['status']=='ready':st.info('El administrador todavía no inició la partida.')
            elif g['status']=='paused':st.info('La primera etapa terminó. Tus resultados se conservaron; espera el inicio de la segunda.')
            elif own['status']=='between' and g['status']=='running':
                st.success(f"Tu ronda anterior está terminada. La siguiente es tu ronda {own['round']}.")
                st.caption('Al continuar empezará tu reloj de 15 minutos. El límite total de la etapa sigue corriendo.')
                if st.button(f"Empezar mi ronda {own['round']} →",type='primary',use_container_width=True):
                    if do(lambda:(svc.begin_round(token,own['round']),True)[1]):st.rerun()
            elif own['status']=='paused':st.success('Terminaste las seis rondas de la primera etapa. Puedes revisar tus resultados.')
            elif own['status']=='finished':st.success('Tu recorrido terminó. El ranking se publicará al finalizar la partida para todos.')
            elif own['status']=='running' and g['status']=='running' and not c['eliminated_round']:strategy_ui(g,token)
            if own.get('skipped'):st.caption('Rondas que no se jugaron antes del cierre de etapa: '+', '.join(map(str,own['skipped']))+'. No se inventaron decisiones ni resultados.')
        elif g['status']=='running' and not c['eliminated_round']:strategy_ui(g,token)
        else:st.info('Las decisiones estarán disponibles cuando comience tu ronda.')
    with results:history(c)
    with guide:help_panel(g)


def prepare_game(token):
    with st.form('new_game'):
        name=st.text_input('Nombre de la partida',value='VIRAL · Clase de marketing',max_chars=80)
        st.caption('Se generarán siete PIN únicos de 4 dígitos. Podrás verlos y descargarlos desde Administración cuando lo necesites.')
        if st.form_submit_button('Preparar nueva partida',type='primary'):
            result=do(lambda:svc.create_game(token,name))
            if result:
                st.rerun()


def individual_admin(token,games,g):
    with st.expander('Partidas anteriores'):
        chosen=st.selectbox('Consultar partida',[x['id'] for x in games],format_func=lambda x:next(f"{a['name']} · {local_date(a['created_at'])}" for a in games if a['id']==x))
        if chosen!=g['id']:
            old=svc.view(token,chosen)
            st.write(old['name'])
            if old['status']=='finished':
                show_ranking(old)
                st.download_button('Descargar reporte de esta partida',data=activity_pdf(old),file_name='VIRAL_historial.pdf',mime='application/pdf')
    st.subheader(g['name']);ticker(token,g['id'],signature(g))
    st.download_button('Descargar reporte de actividades y resultados · PDF',
                       data=activity_pdf(g),file_name=f'VIRAL_actividades_{g["id"][:8]}.pdf',mime='application/pdf')
    st.caption('Disponible en cualquier momento. Abre el PDF descargado para imprimirlo.')
    if st.button('Reiniciar juego',key='restart_game'):
        st.session_state['restart_requested']=g['id']
    if st.session_state.get('restart_requested')==g['id']:
        st.warning('Los siete grupos volverán a la ronda 1, con su dinero inicial y los mismos PIN. La partida anterior quedará en el historial. Después pulsa Iniciar juego.')
        yes,no=st.columns(2)
        if yes.button('Confirmar reinicio',type='primary'):
            if do(lambda:svc.restart_game(token,g['id'])):
                st.session_state.pop('restart_requested',None);st.rerun()
        if no.button('Cancelar reinicio'):
            st.session_state.pop('restart_requested',None);st.rerun()

    if g['status']=='ready':
        st.caption('Primera etapa: 90 minutos. El reloj individual de cada grupo empieza cuando entra a su ronda.')
        if st.button('Iniciar juego',type='primary',use_container_width=True):
            if do(lambda:(svc.start(token),True)[1]):st.rerun()
    elif g['status']=='finished':
        show_ranking(g)
        st.download_button('Descargar reporte final PDF',data=final_pdf(g),file_name=f'VIRAL_reporte_{g["id"][:8]}.pdf',mime='application/pdf')
        with st.expander('Preparar otra partida'):prepare_game(token)
    else:
        all_wait=all(c['progress']['status'] in ('paused','finished','eliminated') for c in g['companies'])
        if g['stage']==1 and (g['status']=='paused' or all_wait):
            if st.button('Iniciar segunda etapa · 30 minutos',type='primary',use_container_width=True):
                if do(lambda:(svc.resume(token),True)[1]):st.rerun()
        with st.expander('Cerrar etapa o finalizar la partida'):
            st.caption('Cerrar la etapa termina solo las rondas que estén en curso. Las rondas que no se jugaron se marcan pendientes, sin inventar resultados.')
            if g['status']=='running' and st.button('Cerrar esta etapa'):
                if do(lambda:(svc.close_stage(token,g['id']),True)[1]):st.rerun()
            if st.button('Finalizar partida y publicar resultados'):
                if do(lambda:(svc.finish_game(token,g['id'],g['round']),True)[1]):st.rerun()
    st.markdown('### Los siete grupos')
    names={'waiting':'Sin empezar','running':'Trabajando','between':'Listo para continuar','paused':'En pausa','finished':'Terminó','eliminated':'Eliminado'}
    st.dataframe(pd.DataFrame([{'Grupo':c['name'],'Ronda del grupo':c['progress']['round'],'Completadas':f"{len(c['history'])}/8",'Estado':names[c['progress']['status']],'Dinero':money(c['capital'])} for c in g['companies']]),hide_index=True,use_container_width=True)
    with st.expander('🔐 PIN de los grupos · solo administración'):
        pins=do(lambda:svc.admin_pins(token,g['id']))
        if pins:
            st.dataframe(pd.DataFrame([{'Grupo':COMPANIES[int(cid)][0],'PIN':pin} for cid,pin in pins.items()]),hide_index=True,use_container_width=True)
            st.download_button('Guardar hoja de accesos',data='\n'.join(f'{COMPANIES[int(cid)][0]}: {pin}' for cid,pin in pins.items()),file_name='PIN_PRIVADOS.txt')
        if g['status']!='finished' and st.button('Generar nuevos PIN de 4 dígitos'):
            if do(lambda:svc.regenerate_pins(token),'PIN actualizados. Los grupos deben volver a ingresar.'):st.rerun()
        if g['status']=='ready':
            with st.form('individual_custom_pins'):
                custom={str(i):st.text_input(name,value=(pins or {}).get(str(i),''),max_chars=4,key=f'individual_pin_{g["id"]}_{i}') for i,(name,*_) in enumerate(COMPANIES)}
                if st.form_submit_button('Guardar PIN propios'):
                    if do(lambda:(svc.configure_pins(token,custom),True)[1]):st.rerun()
    with st.expander('Revisar el avance de un grupo'):
        companies={c['id']:c for c in g['companies']}
        selected=st.selectbox('Grupo',list(companies),format_func=lambda cid:companies[cid]['name'],key=f'admin_history_{g["id"]}',filter_mode=None)
        company=companies[selected]
        history(company)
        if company['progress']['skipped']:st.caption('Rondas no jugadas antes del límite: '+', '.join(map(str,company['progress']['skipped'])))

def admin_dashboard(token):
    header('CENTRO DE CONTROL / ADMINISTRACIÓN')
    games=svc.list_games(token)
    current=svc.view(token)
    if independent(current):
        individual_admin(token,games,current);return
    if not current:
        st.markdown('## Prepara el primer desafío')
        prepare_game(token)
        return
    g=current
    with st.expander('Historial de partidas'):
        ids=[x['id'] for x in games]
        chosen=st.selectbox('Consultar partida',ids,format_func=lambda x:next(f"{a['name']} · {local_date(a['created_at'])}" for a in games if a['id']==x))
        if chosen!=current['id']:
            g=svc.view(token,chosen)
    ticker(token,g['id'],signature(g))
    st.subheader(g['name'])
    with st.expander('🔐 PIN de los grupos · acceso del administrador', expanded=True):
        saved_pins = None
        try:
            saved_pins = svc.admin_pins(token, g['id'])
        except RuleError as exc:
            st.warning(str(exc))
        if saved_pins:
            rows = [{'Grupo': COMPANIES[int(cid)][0], 'PIN': pin} for cid, pin in saved_pins.items()]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.download_button('Guardar hoja de accesos', data='\n'.join(f"{r['Grupo']}: {r['PIN']}" for r in rows), file_name=f'PIN_PRIVADOS_{g["id"][:8]}.txt', mime='text/plain')
            st.caption('PIN de exactamente 4 dígitos. Solo el administrador puede consultar esta lista, incluso después de iniciar la partida o volver a ingresar.')
        else:
            st.info('Los PIN de esta partida aún no se pueden consultar. Genera nuevos PIN de 4 dígitos para verlos aquí; se conservará todo el avance.')
        if g['id'] == current['id'] and g['status'] != 'finished':
            st.caption('Generar nuevos PIN reemplaza los accesos anteriores. Los jugadores deberán volver a ingresar; las decisiones y los resultados se conservan.')
            if st.button('Generar nuevos PIN de 4 dígitos'):
                if do(lambda: svc.regenerate_pins(token), 'Nuevos PIN de 4 dígitos guardados. Ya puedes consultarlos y descargarlos.'):
                    for key in list(st.session_state):
                        if key.startswith('pin_'):
                            del st.session_state[key]
                    st.rerun()
    if g['id']==current['id'] and g['status']=='ready':
        with st.expander('Configurar PIN propios antes del inicio'):
            with st.form('pins'):
                pins={str(i):st.text_input(c[0],value=(saved_pins or {}).get(str(i), ''),max_chars=4,key=f'pin_{g["id"]}_{i}',help='Exactamente 4 dígitos; deben ser distintos. Se conservan los ceros iniciales.') for i,c in enumerate(COMPANIES)}
                if st.form_submit_button('Guardar PIN propios'):
                    result=do(lambda:(svc.configure_pins(token,pins),True)[1],'PIN actualizados; las sesiones previas fueron revocadas.')
                    if result:
                        st.rerun()
        if st.button('Iniciar juego',type='primary',use_container_width=True):
            if do(lambda:(svc.start(token),True)[1]):
                st.rerun()
    elif g['id']==current['id'] and g['status']=='paused':
        st.info('Las rondas 1–6 están cerradas. Reanudar inicia la ronda 7 con 15 minutos completos.')
        if st.button('Reanudar partida →',type='primary',use_container_width=True):
            if do(lambda:(svc.resume(token),True)[1]):
                st.rerun()
    elif g['status']=='finished':
        show_ranking(g)
        st.download_button('Descargar reporte final PDF',data=final_pdf(g),file_name=f'VIRAL_reporte_{g["id"][:8]}.pdf',mime='application/pdf',type='primary')
        if g['id']==current['id']:
            with st.expander('Preparar la próxima partida · conserva todo el historial'):
                prepare_game(token)
    if g['id'] == current['id'] and g['status'] != 'finished':
        st.markdown('### Control de la partida')
        if g['status'] == 'running':
            active_ids = {c['id'] for c in g['companies'] if c['eliminated_round'] is None}
            sent = g['decisions'].get(str(g['round']), {})
            confirmed = sum(cid in sent and not sent[cid]['automatic'] for cid in active_ids)
            st.info(f"{confirmed} de {len(active_ids)} grupos activos confirmaron su estrategia. Puedes cerrar antes de los 15 minutos; quienes no enviaron usarán la estrategia conservadora.")
            if st.button('Cerrar ronda y continuar →', type='primary', use_container_width=True):
                if do(lambda: (svc.close_round(token, g['round'], g['id']), True)[1], 'Ronda cerrada y resultados guardados.'):
                    st.rerun()
        with st.expander('Finalizar la partida y publicar resultados'):
            st.caption('Si hay una ronda abierta, se procesan sus estrategias una sola vez. Después se publica el ranking y queda disponible el PDF. No se generan rondas futuras.')
            if st.button('Finalizar partida y publicar resultados', use_container_width=True):
                if do(lambda: (svc.finish_game(token, g['id'], g['round']), True)[1], 'Partida finalizada. Ranking y PDF disponibles.'):
                    st.rerun()
    submitted=g['decisions'].get(str(g['round']),{})
    rows=[]
    for c in g['companies']:
        d=submitted.get(c['id'])
        rows.append({'Grupo':c['name'],'Capital':money(c['capital']),'Estado':f"Eliminada R{c['eliminated_round']}" if c['eliminated_round'] else 'Activa','Estrategia':'Automática' if d and d['automatic'] else 'Confirmada' if d else 'Sin envío','Beneficio':money(c['profit'])})
    st.markdown('### Los siete grupos')
    st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
    if g['status']!='finished' and g['round']>0:
        with st.expander('Ranking provisional · solo administración'):
            st.dataframe(pd.DataFrame([{'Posición':r['position'],'Grupo':r['name'],'IDV':round(r['idv'],2)} for r in g['ranking']]),hide_index=True,use_container_width=True)
    with st.expander('Historial financiero y decisiones automáticas'):
        companies={c['id']:c for c in g['companies']}
        selected=st.selectbox('Grupo',list(companies),format_func=lambda cid:companies[cid]['name'],key=f'admin_history_{g["id"]}',filter_mode=None)
        company=companies[selected]
        history(company)
    with st.expander('Horarios persistidos · Bolivia'):
        st.dataframe(pd.DataFrame([{'Ronda':r['number'],'Inicio':local_date(r['start']),'Cierre':local_date(r['deadline']),'Procesada':r['processed']} for r in g['rounds']]),hide_index=True,use_container_width=True)

if 'flash' in st.session_state:
    st.success(st.session_state.pop('flash'))
if 'token' not in st.session_state:
    lobby()
else:
    try:
        token=st.session_state['token']
        if st.session_state['role']=='admin':
            admin_dashboard(token)
        else:
            player_dashboard(token)
        st.divider()
        if st.button('Salir de mi sesión'):
            svc.logout(token)
            st.session_state.clear()
            st.rerun()
    except AccessError as exc:
        st.session_state.clear()
        st.warning(str(exc))
        st.rerun()
    except (RuleError,ValueError) as exc:
        st.error(str(exc))
    except Exception:
        st.error('La conexión está temporalmente interrumpida. Recarga para recuperar tu partida.')
st.markdown('<div class="footer"><span>VIRAL — THE BRAND EFFECT</span><span>La viralidad también se planea. La rentabilidad se construye.</span></div>',unsafe_allow_html=True)
