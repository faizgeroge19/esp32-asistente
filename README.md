# Herramientas MCP de Alexa (asistente de voz ESP32)

Herramientas que el asistente de voz (firmware XiaoZhi en un ESP32-S3) puede usar a través del
"punto de acceso MCP" de xiaozhi.me:

| Herramienta | Para qué |
|---|---|
| `obtener_fecha_hora` | Fecha y hora actuales (Bogotá) |
| `consultar_clima` | Clima actual y pronóstico de 3 días en Itagüí (Open-Meteo) |
| `lluvia_por_horas` | Probabilidad de lluvia hora por hora, hoy o mañana |
| `buscar_en_wikipedia` | Resumen de Wikipedia en español |
| `buscar_en_internet` | Búsqueda web actual (Tavily) |
| `ver_agenda` / `agendar_evento` | Calendario de iCloud (CalDAV) |
| `anotar_pendiente` / `ver_pendientes` / `completar_pendiente` | Notas en PostgreSQL (Neon) |

- `herramientas.py`: el servidor MCP (FastMCP, por stdio).
- `conector.py`: lo une por WebSocket al punto de acceso de xiaozhi.me, reconecta solo y, si existe
  la variable `PORT`, responde `ok` en `/salud` (para Render + UptimeRobot).

Ninguna clave va en el código: todas son variables de entorno (ver `.env.example`).

## Probar en local

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      # y llenar los valores
.\.venv\Scripts\python.exe herramientas.py --probar   # prueba las herramientas sin conectarse
.\.venv\Scripts\python.exe conector.py                # conecta con xiaozhi.me
```

## Desplegar en Render (plan Free)

1. Render → **New** → **Web Service** → conectar este repositorio.
2. Configuración:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python conector.py`
   - **Instance Type:** Free
   - **Health Check Path:** `/salud`
3. **Environment** → agregar las variables de `.env.example` con sus valores reales:
   `MCP_ENDPOINT`, `CONTACTO_WIKIPEDIA`, `TAVILY_API_KEY`, `ICLOUD_USUARIO`, `ICLOUD_CLAVE_APP`,
   `ICLOUD_CALENDARIO`, `DATABASE_URL`, y además `PYTHON_VERSION` = `3.12.7`.
4. Desplegar y revisar en **Logs** que aparezca `Conectado al punto de acceso MCP de xiaozhi.me`.
5. En **UptimeRobot**: monitor HTTP(s) a `https://<nombre-del-servicio>.onrender.com/salud`
   cada 5 minutos, para que el plan Free no se duerma.

Notas del plan Free de Render: 750 horas al mes por workspace (un solo servicio 24/7 las consume
casi todas), el disco se borra en cada reinicio (por eso las notas van en Neon) y Render puede
reiniciar el servicio en cualquier momento (el conector reconecta solo).
