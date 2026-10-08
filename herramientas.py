"""Herramientas MCP de Alexa: fecha/hora, clima de Itagüí, Wikipedia y búsqueda web.

Se ejecuta como servidor MCP por stdio; conector.py lo une al punto de acceso de xiaozhi.me.
Prueba local sin conexión: python herramientas.py --probar
"""
import logging
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
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


def _fecha_en_palabras(momento: datetime) -> str:
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
