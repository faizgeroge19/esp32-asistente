"""Herramientas MCP de Alexa: fecha/hora, clima de Itagüí, Wikipedia, búsqueda web,
calendario de iCloud y notas/pendientes.

Se ejecuta como servidor MCP por stdio; conector.py lo une al punto de acceso de xiaozhi.me.
Prueba local sin conexión: python herramientas.py --probar
"""
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import caldav
import httpx
import psycopg
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ZONA = ZoneInfo("America/Bogota")
CIUDAD = "Itagüí"
LATITUD, LONGITUD = 6.172, -75.611
# Wikimedia exige un User-Agent con contacto (URL o correo); sin él responde 403
CONTACTO_WIKIPEDIA = os.environ.get("CONTACTO_WIKIPEDIA", "").strip()
USER_AGENT = f"AlexaESP32/1.0 ({CONTACTO_WIKIPEDIA}; asistente de voz personal)"
WIKIPEDIA_API = "https://es.wikipedia.org/w/api.php"
WIKIPEDIA_RESUMEN = "https://es.wikipedia.org/api/rest_v1/page/summary/"
TAVILY_URL = "https://api.tavily.com/search"
ICLOUD_CALDAV = "https://caldav.icloud.com"
# Calendario de iCloud donde se crean los eventos nuevos
CALENDARIO_PREDETERMINADO = os.environ.get("ICLOUD_CALENDARIO", "Home")
ARCHIVO_NOTAS = Path(__file__).with_name("datos") / "notas.json"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# Códigos meteorológicos WMO que usa Open-Meteo
CLIMA_WMO = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "niebla", 48: "niebla con escarcha",
    51: "llovizna ligera", 53: "llovizna", 55: "llovizna intensa",
    56: "llovizna helada", 57: "llovizna helada intensa",
    61: "lluvia ligera", 63: "lluvia", 65: "lluvia fuerte",
    66: "lluvia helada", 67: "lluvia helada fuerte",
    71: "nevada ligera", 73: "nevada", 75: "nevada fuerte", 77: "granizo fino",
    80: "chubascos ligeros", 81: "chubascos", 82: "aguaceros fuertes",
    85: "chubascos de nieve", 86: "chubascos de nieve fuertes",
    95: "tormenta eléctrica", 96: "tormenta con granizo", 99: "tormenta fuerte con granizo",
}

mcp = FastMCP("Alexa")
# stdout es el canal MCP: los logs van a stderr, que conector.py reenvía a su registro
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s HERRAMIENTA %(message)s")
log = logging.getLogger("herramientas")


def _fecha_en_palabras(momento: date) -> str:
    return f"{DIAS[momento.weekday()]} {momento.day} de {MESES[momento.month - 1]} de {momento.year}"


def _hora_en_palabras(momento: datetime) -> str:
    return momento.strftime("%I:%M %p").lstrip("0").replace("AM", "a. m.").replace("PM", "p. m.")


@mcp.tool()
def obtener_fecha_hora() -> dict:
    """Devuelve la fecha, el día de la semana y la hora actuales en Itagüí, Colombia (hora de Bogotá).
    Úsala SIEMPRE que pregunten qué día es, la fecha, la hora, o necesites saber el día actual
    (por ejemplo para calcular cuánto falta para algo). No adivines la fecha."""
    ahora = datetime.now(ZONA)
    log.info("obtener_fecha_hora -> %s", ahora.isoformat(timespec="minutes"))
    return {
        "fecha": _fecha_en_palabras(ahora),
        "hora": _hora_en_palabras(ahora),
        "iso": ahora.isoformat(timespec="minutes"),
        "zona_horaria": "America/Bogota (UTC-5)",
    }


@mcp.tool()
def consultar_clima() -> dict:
    """Devuelve el clima actual y el pronóstico de hoy, mañana y pasado mañana en Itagüí, Colombia
    (área metropolitana de Medellín), con temperaturas en grados Celsius y probabilidad de lluvia.
    Úsala SIEMPRE que pregunten por el clima, la temperatura, si va a llover o si llevar paraguas.
    No inventes datos del clima."""
    respuesta = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": LATITUD,
            "longitude": LONGITUD,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                       "precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max,precipitation_sum",
            "timezone": "America/Bogota",
            "forecast_days": 3,
        },
        timeout=10,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()

    actual = datos["current"]
    diario = datos["daily"]
    log.info("consultar_clima -> %s °C, código %s", actual["temperature_2m"], actual["weather_code"])
    nombres = ["hoy", "mañana", "pasado mañana"]
    pronostico = []
    for i, nombre in enumerate(nombres):
        dia = datetime.fromisoformat(diario["time"][i])
        pronostico.append({
            "dia": f"{nombre} ({_fecha_en_palabras(dia)})",
            "estado": CLIMA_WMO.get(diario["weather_code"][i], "desconocido"),
            "minima_c": round(diario["temperature_2m_min"][i]),
            "maxima_c": round(diario["temperature_2m_max"][i]),
            "probabilidad_lluvia_pct": diario["precipitation_probability_max"][i],
            "lluvia_mm": diario["precipitation_sum"][i],
        })

    return {
        "ciudad": CIUDAD,
        "actual": {
            "hora_medicion": actual["time"],
            "estado": CLIMA_WMO.get(actual["weather_code"], "desconocido"),
            "temperatura_c": round(actual["temperature_2m"]),
            "sensacion_termica_c": round(actual["apparent_temperature"]),
            "humedad_pct": actual["relative_humidity_2m"],
            "lloviendo_ahora_mm": actual["precipitation"],
            "viento_kmh": round(actual["wind_speed_10m"]),
        },
        "pronostico": pronostico,
        "fuente": "Open-Meteo",
    }


@mcp.tool()
def lluvia_por_horas(dia: str = "hoy") -> dict:
    """Devuelve, hora por hora, la probabilidad de lluvia y los milímetros esperados en Itagüí.
    Úsala cuando pregunten A QUÉ HORA va a llover, hasta qué hora llueve, o si puede salir
    a cierta hora sin mojarse. dia: "hoy" (desde la hora actual) o "mañana"."""
    manana = dia.strip().lower() in ("mañana", "manana", "tomorrow")
    respuesta = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": LATITUD,
            "longitude": LONGITUD,
            "hourly": "precipitation_probability,precipitation",
            "timezone": "America/Bogota",
            "forecast_days": 2,
        },
        timeout=10,
    )
    respuesta.raise_for_status()
    horario = respuesta.json()["hourly"]

    ahora = datetime.now(ZONA)
    fecha_objetivo = (ahora + timedelta(days=1) if manana else ahora).date()
    horas = []
    for momento_iso, probabilidad, milimetros in zip(
            horario["time"], horario["precipitation_probability"], horario["precipitation"]):
        momento = datetime.fromisoformat(momento_iso).replace(tzinfo=ZONA)
        if momento.date() != fecha_objetivo:
            continue
        if not manana and momento.hour < ahora.hour:
            continue
        horas.append(f"{_hora_en_palabras(momento)}: {probabilidad}% ({milimetros} mm)")

    log.info("lluvia_por_horas(%s) -> %d horas", "mañana" if manana else "hoy", len(horas))
    return {
        "ciudad": CIUDAD,
        "dia": f"{'mañana' if manana else 'hoy'} ({_fecha_en_palabras(ahora + timedelta(days=int(manana)))})",
        "horas": horas,
        "nota": "probabilidad de lluvia y milímetros por hora; 0.1 mm o menos es llovizna casi imperceptible",
    }


@mcp.tool()
def buscar_en_wikipedia(tema: str) -> dict:
    """Busca un tema en Wikipedia en español y devuelve su resumen.
    Úsala para datos enciclopédicos y estables: biografías, historia, geografía, ciencia,
    definiciones, obras, lugares. Para noticias recientes o resultados actuales usa buscar_en_internet."""
    if not CONTACTO_WIKIPEDIA:
        return {"error": "Wikipedia no está configurada (falta CONTACTO_WIKIPEDIA)."}
    cliente = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10)
    busqueda = cliente.get(WIKIPEDIA_API, params={
        "action": "query", "list": "search", "srsearch": tema,
        "srlimit": 1, "format": "json", "utf8": 1,
    })
    busqueda.raise_for_status()
    resultados = busqueda.json()["query"]["search"]
    if not resultados:
        log.info("buscar_en_wikipedia(%r) -> sin resultados", tema)
        return {"encontrado": False, "mensaje": f"Wikipedia no tiene un artículo sobre «{tema}»."}

    titulo = resultados[0]["title"]
    resumen = cliente.get(WIKIPEDIA_RESUMEN + titulo.replace(" ", "_"))
    resumen.raise_for_status()
    datos = resumen.json()
    log.info("buscar_en_wikipedia(%r) -> %s", tema, titulo)
    return {
        "encontrado": True,
        "titulo": datos.get("title", titulo),
        "resumen": datos.get("extract", "")[:1500],
        "fuente": datos.get("content_urls", {}).get("desktop", {}).get("page", "Wikipedia"),
    }


@mcp.tool()
def buscar_en_internet(consulta: str, solo_noticias: bool = False) -> dict:
    """Busca en internet información actual: noticias, resultados deportivos, eventos recientes,
    precios, lanzamientos, o cualquier dato que pueda haber cambiado recientemente.
    Úsala SIEMPRE antes de decir que no tienes información en tiempo real.
    consulta: la pregunta en palabras claras. solo_noticias: True para noticias de los últimos días."""
    clave = os.environ.get("TAVILY_API_KEY", "").strip()
    if not clave:
        return {"error": "La búsqueda web no está configurada (falta TAVILY_API_KEY)."}

    cuerpo = {
        "query": consulta,
        "search_depth": "basic",
        "max_results": 5,
        "include_answer": "basic",
    }
    if solo_noticias:
        cuerpo.update({"topic": "news", "time_range": "week"})
    else:
        # Sin esto "Nacional" devolvía el de Uruguay; Tavily solo admite country con topic general
        cuerpo["country"] = "colombia"
    respuesta = httpx.post(TAVILY_URL, json=cuerpo,
                           headers={"Authorization": f"Bearer {clave}"}, timeout=20)
    respuesta.raise_for_status()
    datos = respuesta.json()
    log.info("buscar_en_internet(%r, noticias=%s) -> %d resultados",
             consulta, solo_noticias, len(datos.get("results", [])))
    return {
        "respuesta_resumida": datos.get("answer"),
        "resultados": [
            {"titulo": r["title"], "contenido": r["content"][:400], "url": r["url"]}
            for r in datos.get("results", [])
        ],
    }


def _calendarios_icloud() -> list:
    usuario = os.environ.get("ICLOUD_USUARIO", "").strip()
    clave = os.environ.get("ICLOUD_CLAVE_APP", "").strip()
    if not usuario or not clave:
        raise RuntimeError("El calendario no está configurado (faltan ICLOUD_USUARIO o ICLOUD_CLAVE_APP).")
    cliente = caldav.DAVClient(url=ICLOUD_CALDAV, username=usuario, password=clave)
    # La lista "Reminders" es de tareas (VTODO), no de eventos
    return [c for c in cliente.principal().calendars()
            if "VEVENT" in c.get_supported_components()]


def _interpretar_dia(texto: str) -> date:
    texto = texto.strip().lower()
    hoy = datetime.now(ZONA).date()
    relativos = {"hoy": 0, "mañana": 1, "manana": 1, "pasado mañana": 2, "pasado manana": 2}
    if texto in relativos:
        return hoy + timedelta(days=relativos[texto])
    return date.fromisoformat(texto)


def _a_zona(valor):
    if isinstance(valor, datetime):
        return valor.replace(tzinfo=ZONA) if valor.tzinfo is None else valor.astimezone(ZONA)
    return valor  # evento de todo el día: es una fecha sin hora


@mcp.tool()
def ver_agenda(dia: str = "hoy", dias: int = 1) -> dict:
    """Lee los eventos del calendario de iCloud de Samuel (citas, gym, planes).
    Úsala cuando pregunte qué tiene hoy, mañana, un día concreto o esta semana.
    dia: "hoy", "mañana", "pasado mañana" o una fecha AAAA-MM-DD (calcúlala con obtener_fecha_hora).
    dias: cuántos días mostrar desde ese día (1 a 7).
    Sus clases de la universidad NO están aquí: están en la sección "Sobre Samuel" de tus instrucciones."""
    try:
        inicio = _interpretar_dia(dia)
    except ValueError:
        return {"error": f"No entendí el día «{dia}». Usa hoy, mañana o AAAA-MM-DD."}
    dias = max(1, min(dias, 7))
    desde = datetime.combine(inicio, datetime.min.time(), ZONA)
    hasta = desde + timedelta(days=dias)

    eventos = []
    for calendario in _calendarios_icloud():
        for evento in calendario.search(start=desde, end=hasta, event=True, expand=True):
            componente = evento.icalendar_component
            empieza = _a_zona(componente.get("dtstart").dt)
            termina = _a_zona(componente.get("dtend").dt) if componente.get("dtend") else None
            todo_el_dia = not isinstance(empieza, datetime)
            eventos.append({
                "orden": empieza.isoformat(),
                "titulo": str(componente.get("summary", "(sin título)")),
                "dia": _fecha_en_palabras(empieza),
                "hora": "todo el día" if todo_el_dia else (
                    _hora_en_palabras(empieza) + (f" a {_hora_en_palabras(termina)}" if termina else "")),
                "lugar": str(componente.get("location", "")) or None,
            })
    eventos.sort(key=lambda e: e.pop("orden"))
    log.info("ver_agenda(%s, %d días) -> %d eventos", inicio, dias, len(eventos))
    return {
        "desde": _fecha_en_palabras(desde),
        "dias": dias,
        "eventos": eventos,
        "nota": "Si no hay eventos, díselo; recuerda que sus clases están en tus instrucciones.",
    }


@mcp.tool()
def agendar_evento(titulo: str, fecha: str, hora_inicio: str = "",
                   duracion_minutos: int = 60, lugar: str = "") -> dict:
    """Crea un evento en el calendario de iCloud de Samuel (se ve en su iPhone).
    ANTES de usarla, confirma en voz alta con Samuel el título, el día y la hora, y úsala solo
    cuando diga que sí. fecha: AAAA-MM-DD, "hoy" o "mañana" (calcula las demás con
    obtener_fecha_hora). hora_inicio: HH:MM en formato de 24 horas, o vacío para todo el día."""
    try:
        dia = _interpretar_dia(fecha)
    except ValueError:
        return {"error": f"No entendí la fecha «{fecha}». Usa AAAA-MM-DD."}
    calendarios = _calendarios_icloud()
    destino = next((c for c in calendarios if c.get_display_name() == CALENDARIO_PREDETERMINADO),
                   calendarios[0])

    if hora_inicio:
        try:
            hora, minuto = (int(parte) for parte in hora_inicio.split(":"))
        except ValueError:
            return {"error": f"No entendí la hora «{hora_inicio}». Usa HH:MM, por ejemplo 16:30."}
        empieza = datetime.combine(dia, datetime.min.time(), ZONA).replace(hour=hora, minute=minuto)
        termina = empieza + timedelta(minutes=max(5, duracion_minutos))
        cuando = f"{_fecha_en_palabras(empieza)}, de {_hora_en_palabras(empieza)} a {_hora_en_palabras(termina)}"
    else:
        empieza, termina = dia, dia + timedelta(days=1)
        cuando = f"{_fecha_en_palabras(dia)}, todo el día"

    propiedades = {"dtstart": empieza, "dtend": termina, "summary": titulo}
    if lugar:
        propiedades["location"] = lugar
    destino.save_event(**propiedades)
    log.info("agendar_evento(%r, %s) -> calendario %s", titulo, cuando, destino.get_display_name())
    return {"creado": True, "titulo": titulo, "cuando": cuando,
            "calendario": destino.get_display_name()}


# Las notas viven en PostgreSQL (Neon) si hay DATABASE_URL; si no, en un archivo local.
# En Render no sirve el archivo: el plan gratis borra el disco en cada reinicio.
def _bd():
    conexion = psycopg.connect(DATABASE_URL, connect_timeout=15)
    conexion.execute("""
        CREATE TABLE IF NOT EXISTS notas (
            numero     SERIAL PRIMARY KEY,
            texto      TEXT NOT NULL,
            creada     TIMESTAMPTZ NOT NULL DEFAULT now(),
            hecha      BOOLEAN NOT NULL DEFAULT false,
            completada TIMESTAMPTZ
        )""")
    return conexion


def _leer_archivo() -> list:
    if not ARCHIVO_NOTAS.exists():
        return []
    return json.loads(ARCHIVO_NOTAS.read_text(encoding="utf-8"))


def _guardar_archivo(notas: list) -> None:
    ARCHIVO_NOTAS.parent.mkdir(exist_ok=True)
    ARCHIVO_NOTAS.write_text(json.dumps(notas, ensure_ascii=False, indent=2), encoding="utf-8")


@mcp.tool()
def anotar_pendiente(texto: str) -> dict:
    """Guarda una nota o pendiente de Samuel (compras, tareas, ideas, cosas por recordar).
    Úsala cuando diga "anota", "apunta", "recuérdame que debo...", "agrega a mi lista"."""
    texto = texto.strip()
    if DATABASE_URL:
        with _bd() as conexion:
            numero = conexion.execute(
                "INSERT INTO notas (texto) VALUES (%s) RETURNING numero", (texto,)).fetchone()[0]
    else:
        notas = _leer_archivo()
        numero = max((n["numero"] for n in notas), default=0) + 1
        notas.append({"numero": numero, "texto": texto,
                      "creada": datetime.now(ZONA).isoformat(timespec="minutes"), "hecha": False})
        _guardar_archivo(notas)
    log.info("anotar_pendiente(%r) -> #%d", texto, numero)
    return {"guardada": True, "numero": numero, "texto": texto}


@mcp.tool()
def ver_pendientes() -> dict:
    """Lista las notas y pendientes de Samuel que aún no ha marcado como hechos.
    Úsala cuando pregunte qué tiene pendiente, qué anotó o qué hay en su lista."""
    if DATABASE_URL:
        with _bd() as conexion:
            filas = conexion.execute(
                "SELECT numero, texto FROM notas WHERE NOT hecha ORDER BY numero").fetchall()
        pendientes = [{"numero": numero, "texto": texto} for numero, texto in filas]
    else:
        pendientes = [{"numero": n["numero"], "texto": n["texto"]}
                      for n in _leer_archivo() if not n["hecha"]]
    log.info("ver_pendientes -> %d", len(pendientes))
    return {"pendientes": pendientes, "total": len(pendientes)}


@mcp.tool()
def completar_pendiente(numero: int) -> dict:
    """Marca como hecho un pendiente (lo tacha de la lista). Usa el número que devuelve
    ver_pendientes; si no lo sabes, llama primero a ver_pendientes para encontrarlo."""
    texto = None
    if DATABASE_URL:
        with _bd() as conexion:
            fila = conexion.execute(
                "UPDATE notas SET hecha = true, completada = now() "
                "WHERE numero = %s AND NOT hecha RETURNING texto", (numero,)).fetchone()
        texto = fila[0] if fila else None
    else:
        notas = _leer_archivo()
        for nota in notas:
            if nota["numero"] == numero and not nota["hecha"]:
                nota["hecha"] = True
                nota["completada"] = datetime.now(ZONA).isoformat(timespec="minutes")
                _guardar_archivo(notas)
                texto = nota["texto"]
                break
    if texto is None:
        return {"completado": False, "mensaje": f"No hay un pendiente abierto con el número {numero}."}
    log.info("completar_pendiente(#%d) -> %r", numero, texto)
    return {"completado": True, "texto": texto}


if __name__ == "__main__":
    if "--probar" in sys.argv:
        import json
        print(json.dumps(obtener_fecha_hora(), ensure_ascii=False, indent=2))
        print(json.dumps(consultar_clima(), ensure_ascii=False, indent=2))
        print(json.dumps(lluvia_por_horas("hoy"), ensure_ascii=False, indent=2))
        print(json.dumps(buscar_en_wikipedia("Gabriel García Márquez"), ensure_ascii=False, indent=2))
        print(json.dumps(buscar_en_internet("¿Cuándo se retiró Messi de la selección?"),
                         ensure_ascii=False, indent=2))
    else:
        mcp.run(transport="stdio", show_banner=False)
