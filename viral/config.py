"""Parámetros de diseño. Se copian en cada partida para fijar sus reglas."""
from copy import deepcopy

COMPANIES = [
    ("Grupo 1", "FULL", "CHISPA", "#b68aff"),
    ("Grupo 2", "RITMO", "FLOW", "#4ce5da"),
    ("Grupo 3", "PULSO", "DESCARGA", "#ffca5f"),
    ("Grupo 4", "ACTIVA", "BRAVA", "#ff7da7"),
    ("Grupo 5", "FUEGO", "FRESCA", "#a8e76c"),
    ("Grupo 6", "META", "BOOST", "#68baff"),
    ("Grupo 7", "POWER", "IMPARABLE", "#ff9770"),
]
MISSIONS = [
    ("Encuentra tu lugar", "Elige un segmento y una promesa distinta para cada marca."),
    ("Haz que te escuchen", "Conecta plataforma, contenido y objetivo. Cuida tu margen."),
    ("Construye comunidad", "Elige creadores por afinidad y credibilidad, no solo alcance."),
    ("Suma fuerzas", "Propón una alianza compatible y reserva su costo antes del cierre."),
    ("Da el siguiente salto", "Mejora tus productos o evalúa una expansión con caja suficiente."),
    ("Lee la jugada", "Revisa tus resultados y responde sin perder tu identidad."),
    ("Haz rendir cada boliviano", "Renueva campañas fatigadas y elimina inversiones ineficientes."),
    ("Deja tu huella", "Consolida rentabilidad, marcas y crecimiento para cerrar tu IDV."),
]
SEGMENTS = ["Rendimiento", "Sensible al precio", "Tendencia", "Bienestar y rutina"]
ATTRIBUTES = ["Funcionalidad", "Ahorro", "Originalidad", "Confianza"]
CONTENTS = ["Demostraciones", "Historias de marca", "Humor", "Desafíos", "Testimonios", "Educativo", "Comparaciones", "Lanzamientos"]
OBJECTIVES = ["Reconocimiento", "Interacción", "Intención de compra", "Conversión", "Fidelización"]
PLATFORMS = {
    "TikTok": {"cpm": 35, "affinity": [.70, .60, 1.0, .65]},
    "Instagram": {"cpm": 40, "affinity": [.75, .60, .95, .90]},
    "Facebook": {"cpm": 25, "affinity": [.60, 1.0, .55, .85]},
    "YouTube": {"cpm": 45, "affinity": [1.0, .70, .60, .80]},
    "Twitch": {"cpm": 38, "affinity": [.90, .55, .90, .50]},
    "X": {"cpm": 28, "affinity": [.65, .65, .90, .55]},
}
CONTENT_AFFINITY = {
    "Demostraciones": [1.0, .75, .60, .85], "Historias de marca": [.70, .60, .80, 1.0],
    "Humor": [.60, .80, 1.0, .65], "Desafíos": [.85, .60, 1.0, .65],
    "Testimonios": [.90, .80, .65, 1.0], "Educativo": [1.0, .80, .55, .95],
    "Comparaciones": [.95, 1.0, .55, .75], "Lanzamientos": [.85, .65, 1.0, .70],
}
INFLUENCERS = {
    "Ninguno": {"cost": 0, "reach": 0, "credibility": 0, "engagement": 0, "affinity": [0, 0, 0, 0], "risk": 0},
    "Camila Fit": {"cost": 24000, "reach": 280000, "credibility": .94, "engagement": .08, "affinity": [1, .5, .65, .85], "risk": .01},
    "Nico Calle": {"cost": 18000, "reach": 210000, "credibility": .82, "engagement": .10, "affinity": [.6, .8, 1, .5], "risk": .03},
    "Vale Cotidiana": {"cost": 14000, "reach": 150000, "credibility": .96, "engagement": .09, "affinity": [.65, .85, .65, 1], "risk": .01},
    "Diego Tech": {"cost": 28000, "reach": 320000, "credibility": .90, "engagement": .07, "affinity": [.95, .65, .9, .6], "risk": .02},
    "Luna Live": {"cost": 32000, "reach": 450000, "credibility": .76, "engagement": .06, "affinity": [.7, .55, 1, .5], "risk": .04},
}
SPONSORS = {
    "Ninguno": {"cost": 0, "affinity": [0, 0, 0, 0]},
    "Copa universitaria": {"cost": 20000, "affinity": [1, .7, .6, .5]},
    "Festival urbano": {"cost": 26000, "affinity": [.5, .7, 1, .6]},
    "Feria de bienestar": {"cost": 16000, "affinity": [.7, .7, .5, 1]},
    "Encuentro tecnológico": {"cost": 24000, "affinity": [.9, .5, .9, .6]},
}
# Los nombres son reales; costos, alcance y afinidades son parámetros educativos.
# Los perfiles anteriores se conservan para leer decisiones históricas.
LEGACY_INFLUENCERS = tuple(k for k in INFLUENCERS if k != 'Ninguno')
INFLUENCERS.update({
    'Albertina Sacaca': {'cost':24000,'reach':280000,'credibility':.9,'engagement':.08,'affinity':[.65,.85,.75,1.0],'risk':.02,'topic':'Vida cotidiana y cocina'},
    'Juandy': {'cost':18000,'reach':210000,'credibility':.9,'engagement':.08,'affinity':[.65,.85,1.0,.60],'risk':.02,'topic':'Humor y entretenimiento'},
    'Ale Pinedo': {'cost':28000,'reach':320000,'credibility':.9,'engagement':.08,'affinity':[.70,.80,1.0,.55],'risk':.02,'topic':'Comedia'},
    'Anabel Angus': {'cost':32000,'reach':450000,'credibility':.9,'engagement':.08,'affinity':[.60,.65,.90,1.0],'risk':.02,'topic':'Estilo de vida y entretenimiento'},
    'Leonel Fransezze': {'cost':26000,'reach':300000,'credibility':.9,'engagement':.08,'affinity':[.70,.80,1.0,.60],'risk':.02,'topic':'Comedia y entretenimiento'},
    'Mama Lucy': {'cost':14000,'reach':150000,'credibility':.9,'engagement':.08,'affinity':[.60,1.0,.55,1.0],'risk':.02,'topic':'Cocina y emprendimiento'},
    'Kaplex': {'cost':22000,'reach':260000,'credibility':.9,'engagement':.08,'affinity':[1.0,.60,.85,.70],'risk':.02,'topic':'Viajes y experiencias'},
})
SPONSORS.update({
    'Entel': {'cost':30000,'affinity':[.90,.80,1.0,.65],'topic':'Campaña de conectividad'},
    'Tigo Bolivia': {'cost':32000,'affinity':[1.0,.65,1.0,.55],'topic':'Activación deportiva y digital'},
    'PIL Andina': {'cost':22000,'affinity':[.85,.80,.60,1.0],'topic':'Campaña de nutrición'},
    'Sofía': {'cost':24000,'affinity':[.75,.90,.60,1.0],'topic':'Feria de alimentación'},
    'BNB': {'cost':28000,'affinity':[.80,.85,.65,.90],'topic':'Encuentro de emprendimiento'},
    'BancoSol': {'cost':18000,'affinity':[.65,1.0,.65,.85],'topic':'Feria de emprendedores'},
    'BoA': {'cost':34000,'affinity':[.80,.55,1.0,.80],'topic':'Activación de turismo'},
})

def influencer_options(selected='Ninguno'):
    return [k for k in INFLUENCERS if k not in LEGACY_INFLUENCERS or k == selected]

STUDIES = {
    "Encuesta de consumidores": 6000, "Mapa de posicionamiento": 8000,
    "Pronóstico de mercado": 5000, "Test de contenido": 5000, "Estudio de expansión": 7000,
}
DEFAULT_RULES = {
    "initial_capital": 1000000, "round_seconds": 900, "rounds": 8,
    "markets": {
        "VITAL": {"size": 700000, "growth": .02, "reference_price": 15, "unit_cost": 6.5, "entry": 0, "min_quality": 0},
        "ACTIVE": {"size": 70000, "growth": .03, "reference_price": 150, "unit_cost": 72, "entry": 180000, "min_quality": 55},
        "TECH": {"size": 20000, "growth": .04, "reference_price": 450, "unit_cost": 240, "entry": 280000, "min_quality": 60},
    },
    "segment_weights": [.28, .30, .24, .18], "price_sensitivity": [1.5, 3.0, 1.1, 1.8],
    "operating_cost": 22000, "extra_market_operating": 12000,
    "outside_option": 3.0, "random_variation": .02, "awareness_decay": .94,
    "innovation_scale": 6000, "max_innovation": 150000,
    "alliance_cost": 18000, "alliance_lift": .16,
    "idv_weights": [.30, .20, .15, .15, .10, .10],
}

def rules():
    return deepcopy(DEFAULT_RULES)
