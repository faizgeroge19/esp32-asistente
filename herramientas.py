"""Herramientas MCP de Alexa: fecha/hora y clima de Itagüí.

Se ejecuta como servidor MCP por stdio; conector.py lo une al punto de acceso de xiaozhi.me.
Prueba local sin conexión: python herramientas.py --probar
"""
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastmcp import FastMCP

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ZONA = ZoneInfo("America/Bogota")
CIUDAD = "Itagüí"
LATITUD, LONGITUD = 6.172, -75.611

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


@mcp.tool()
def obtener_fecha_hora() -> dict:
    """Devuelve la fecha, el día de la semana y la hora actuales en Itagüí, Colombia (hora de Bogotá).
    Úsala SIEMPRE que pregunten qué día es, la fecha, la hora, o necesites saber el día actual
    (por ejemplo para calcular cuánto falta para algo). No adivines la fecha."""
    ahora = datetime.now(ZONA)
    log.info("obtener_fecha_hora -> %s", ahora.isoformat(timespec="minutes"))
    return {
        "fecha": _fecha_en_palabras(ahora),
        "hora": ahora.strftime("%I:%M %p").lstrip("0").replace("AM", "a. m.").replace("PM", "p. m."),
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


if __name__ == "__main__":
    if "--probar" in sys.argv:
        import json
        print(json.dumps(obtener_fecha_hora(), ensure_ascii=False, indent=2))
        print(json.dumps(consultar_clima(), ensure_ascii=False, indent=2))
    else:
        mcp.run(transport="stdio", show_banner=False)
