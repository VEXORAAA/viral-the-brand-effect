"""Reporte final de dos páginas, sin claves ni estrategias privadas."""
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from .engine import ranking

PURPLE = HexColor('#7850dd')
DARK = HexColor('#10152c')
MUTED = HexColor('#5c6578')
GREEN = HexColor('#008a73')

def money(n):
    return f'Bs {n:,.0f}'.replace(',', '.')

def final_pdf(game):
    if game['status'] != 'finished':
        raise ValueError('El reporte final está disponible cuando termina la partida.')
    rows = ranking(game['companies'], game['rules'])
    buff = BytesIO()
    cv = canvas.Canvas(buff, pagesize=A4, invariant=1)
    cv.setTitle('VIRAL - The Brand Effect | Reporte final')
    cv.setAuthor('VIRAL')
    W, H = A4
    def header(subtitle, page):
        cv.setFillColor(DARK)
        cv.rect(0, H-132, W, 132, fill=1, stroke=0)
        cv.setFillColor(HexColor('#b796ff'))
        cv.setFont('Helvetica-BoldOblique', 31)
        cv.drawString(36, H-49, 'VIRAL')
        cv.setFillColor(white)
        cv.setFont('Helvetica-Bold', 11)
        cv.drawString(37, H-69, 'THE BRAND EFFECT')
        cv.setFont('Helvetica', 10)
        cv.drawString(37, H-102, subtitle)
        cv.setFillColor(MUTED)
        cv.setFont('Helvetica', 8)
        cv.drawString(36, 26, 'Estrategia. Creatividad. Competencia.')
        cv.drawRightString(W-36, 26, f'{page} / 2')
    stamp = datetime.fromtimestamp(game['created_at'], ZoneInfo('America/La_Paz')).strftime('%d/%m/%Y %H:%M')
    header(f"REPORTE FINAL  |  {stamp} (Bolivia)", 1)
    winners = ', '.join(r['name'] for r in rows if r['position'] == 1)
    cv.setFillColor(DARK)
    cv.setFont('Helvetica-Bold', 11)
    cv.drawString(36, H-166, 'GRUPO GANADOR' if ',' not in winners else 'PRIMER PUESTO COMPARTIDO')
    cv.setFillColor(PURPLE)
    winner_font = min(17, (W-72) / max(cv.stringWidth(winners, 'Helvetica-Bold', 1), 1))
    cv.setFont('Helvetica-Bold', winner_font)
    cv.drawString(36, H-191, winners)
    cv.setFillColor(MUTED)
    cv.setFont('Helvetica', 10)
    cv.drawString(36, H-211, f"IDV {rows[0]['idv']:.2f} / 100  |  {game['name'][:65]}")
    closed = sum(r['processed'] for r in game['rounds'])
    ending = 'Cierre administrativo' if game.get('finish_reason') == 'admin' else 'Final de la partida'
    cv.setFont('Helvetica', 9)
    if game.get('flow_version') == 2:
        counts=[len(c['history']) for c in game['companies']]
        cv.drawString(36, H-228, f'Rondas jugadas por grupo: {min(counts)} a {max(counts)} de 8 | {ending}')
    else:
        cv.drawString(36, H-228, f'{closed} de 8 rondas procesadas | {ending}')
    y = H-251
    cv.setFillColor(DARK)
    cv.setFont('Helvetica-Bold', 9)
    columns = [(36, '#'), (59, 'Grupo'), (260, 'IDV'), (310, 'Capital'), (418, 'Beneficio acumulado')]
    for x, text in columns:
        cv.drawString(x, y, text)
    for r in rows:
        y -= 36
        cv.setFillColor(HexColor('#f3f0fc') if r['position'] == 1 else HexColor('#f5f6fa'))
        cv.roundRect(30, y-10, W-60, 31, 5, fill=1, stroke=0)
        cv.setFillColor(DARK)
        cv.setFont('Helvetica-Bold' if r['position'] == 1 else 'Helvetica', 9)
        cv.drawString(36, y, str(r['position']))
        cv.drawString(59, y, r['name'])
        cv.drawString(260, y, f"{r['idv']:.2f}")
        cv.drawString(310, y, money(r['capital']))
        cv.drawString(418, y, money(r['profit']))
    y -= 45
    cv.setFont('Helvetica-Bold', 11)
    cv.drawString(36, y, 'Situación de los grupos')
    cv.setFont('Helvetica', 9)
    eliminated = [r for r in rows if r['eliminated_round'] is not None]
    for r in eliminated:
        y -= 17
        cv.drawString(36, y, f"{r['name']} - eliminada en ronda {r['eliminated_round']}")
    if not eliminated:
        y -= 20
        cv.drawString(36, y, 'Todos los grupos permanecieron activos.')
    y -= 30
    cv.setFillColor(MUTED)
    cv.setFont('Helvetica', 8)
    for line in ['Las empresas activas preceden a las eliminadas; entre eliminadas prevalece la supervivencia.',
                 'Desempates: desempeño financiero, competitividad y valor de marca; luego posición compartida.',
                 'Los indicadores se normalizan entre 0 y 100. Los resultados son simulados con fines educativos.']:
        cv.drawString(36, y, line)
        y -= 14
    cv.showPage()
    header('DESEMPEÑO COMPARADO  |  INDICADORES FINALES', 2)
    y = H-169
    cv.setFont('Helvetica-Bold', 12)
    cv.setFillColor(DARK)
    cv.drawString(36, y, 'Índice de Desempeño VIRAL')
    for r in rows:
        y -= 31
        cv.setFillColor(DARK)
        cv.setFont('Helvetica', 9)
        cv.drawString(36, y+2, r['name'])
        cv.setFillColor(HexColor('#ece8f6'))
        cv.roundRect(156, y-3, 330, 14, 4, fill=1, stroke=0)
        cv.setFillColor(PURPLE)
        cv.roundRect(156, y-3, max(1, 330*r['idv']/100), 14, 4, fill=1, stroke=0)
        cv.setFont('Helvetica-Bold', 9)
        cv.drawString(497, y, f"{r['idv']:.2f}")
    y -= 43
    cv.setFillColor(DARK)
    cv.setFont('Helvetica-Bold', 10)
    cv.drawString(36, y, 'Grupo')
    for i, label in enumerate(['F 30%', 'C 20%', 'M 15%', 'V 15%', 'E 10%', 'D 10%']):
        cv.drawString(176+i*58, y, label)
    for r in rows:
        y -= 23
        cv.setFont('Helvetica', 9)
        cv.drawString(36, y, r['name'])
        for i, key in enumerate(['F', 'C', 'M', 'V', 'E', 'D']):
            cv.drawString(176+i*58, y, f'{r[key]:.1f}')
    y -= 37
    cv.setFont('Helvetica', 8)
    cv.setFillColor(MUTED)
    for line in ['F: financiero | C: competitividad | M: marca | V: viralidad | E: eficiencia | D: desarrollo',
                 'Viralidad y eficiencia miden resultados, no solamente inversión o número de seguidores.']:
        cv.drawString(36, y, line)
        y -= 15
    y -= 24
    cv.setFillColor(DARK)
    cv.setFont('Helvetica-Bold', 10)
    cv.drawString(36, y, 'Resultados globales de la partida')
    cv.setFont('Helvetica', 9)
    y -= 20
    cv.drawString(36, y, 'Ingresos acumulados: ' + money(sum(c['revenue'] for c in game['companies'])))
    y -= 17
    cv.drawString(36, y, 'Inversión acumulada en marketing: ' + money(sum(c['marketing'] for c in game['companies'])))
    cv.save()
    return buff.getvalue()


def activity_pdf(game):
    """Printable progress and per-round activity, available before and after closure."""
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet
    from xml.sax.saxutils import escape
    styles=getSampleStyleSheet(); out=BytesIO(); story=[]
    def text(value,style='BodyText'):
        story.append(Paragraph(escape(str(value)),styles[style]));story.append(Spacer(1,8))
    def table(rows):
        cells=[[Paragraph(escape(str(c)),styles['BodyText']) for c in row] for row in rows]
        t=Table(cells,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),HexColor('#eee8fa')),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),0.3,MUTED),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        story.append(t);story.append(Spacer(1,12))
    text('VIRAL - Actividades y resultados','Title');text(game['name'],'Heading2')
    states={'ready':'Preparada','running':'En curso','paused':'En pausa','finished':'Finalizada'}
    text('Estado: '+states.get(game['status'],game['status']))
    text('Clasificación '+('final' if game['status']=='finished' else 'provisional'),'Heading2')
    table([['Puesto','Grupo','IDV','Capital','Ganancia']]+[[r['position'],r['name'],f"{r['idv']:.2f}",money(r['capital']),money(r['profit'])] for r in ranking(game['companies'],game['rules'])])
    for company in game['companies']:
        story.append(PageBreak());text(company['name'],'Heading1')
        text(f"Rondas completadas: {len(company['history'])} de 8 | Capital: {money(company['capital'])}")
        if not company['history']:text('Este grupo todavía no tiene resultados de rondas completadas.')
        for result in company['history']:
            number=result.get('round',0)
            text(f"Ronda {number}",'Heading2')
            text('Cierre automático' if result.get('automatic') else 'Estrategia enviada por el grupo')
            table([['Ingresos','Ganancia','Capital']]+[[money(result.get('revenue',0)),money(result.get('profit',0)),money(result.get('capital',0))]])
            saved=game.get('decisions',{}).get(str(number),{}).get(company['id'],{})
            strategy=saved.get('strategy',{})
            text('Patrocinio: '+str(strategy.get('sponsor','Ninguno')))
            for brand in strategy.get('brands',[]):
                brand=dict(brand,name=next((b['name'] for b in company['brands'] if b['id']==brand['id']),brand['id']))
                text(' | '.join(f'{label}: {brand[key]}' for key,label in [('name','Marca'),('price','Precio'),('segment','Público'),('platform','Plataforma'),('budget','Anuncios'),('content_budget','Contenido'),('innovation','Innovación'),('influencer','Influencer'),('expand','Expansión')] if key in brand))
        skipped=company.get('progress',{}).get('skipped',[])
        if skipped:text('Rondas no jugadas: '+', '.join(map(str,skipped)))
    SimpleDocTemplate(out,pagesize=A4,rightMargin=36,leftMargin=36,topMargin=36,bottomMargin=36,title='VIRAL - Actividades y resultados').build(story)
    return out.getvalue()
