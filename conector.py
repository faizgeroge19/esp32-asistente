"""Une herramientas.py (servidor MCP por stdio) con el punto de acceso MCP de xiaozhi.me.

- Lee MCP_ENDPOINT del entorno o de un archivo .env (nunca lo escribas en el código).
- Si la conexión se cae, reconecta con espera creciente (1 s, 2 s, 4 s... hasta 60 s).
- Si existe la variable PORT (Render la define), responde "ok" en http://.../salud
  para que UptimeRobot mantenga el servicio despierto.

Uso: python conector.py
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

import websockets
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("conector")

SERVIDOR = [sys.executable, str(Path(__file__).with_name("herramientas.py"))]
ESPERA_MAXIMA = 60


async def _de_websocket_a_proceso(ws, proceso):
    async for mensaje in ws:
        if isinstance(mensaje, bytes):
            mensaje = mensaje.decode("utf-8")
        proceso.stdin.write(mensaje.encode("utf-8") + b"\n")
        await proceso.stdin.drain()


async def _de_proceso_a_websocket(proceso, ws):
    while linea := await proceso.stdout.readline():
        await ws.send(linea.decode("utf-8"))
    raise ConnectionError("el servidor de herramientas terminó")


async def _reenviar_errores(proceso):
    while linea := await proceso.stderr.readline():
        sys.stderr.write(linea.decode("utf-8", errors="replace"))


async def _sesion(endpoint):
    async with websockets.connect(endpoint, ping_interval=30) as ws:
        log.info("Conectado al punto de acceso MCP de xiaozhi.me")
        proceso = await asyncio.create_subprocess_exec(
            *SERVIDOR,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        tareas = [
            asyncio.create_task(_de_websocket_a_proceso(ws, proceso)),
            asyncio.create_task(_de_proceso_a_websocket(proceso, ws)),
            asyncio.create_task(_reenviar_errores(proceso)),
        ]
        try:
            hechas, _ = await asyncio.wait(tareas[:2], return_when=asyncio.FIRST_COMPLETED)
            for tarea in hechas:
                tarea.result()  # propaga el error que cortó la sesión
            raise ConnectionError("xiaozhi.me cerró la conexión")
        finally:
            for tarea in tareas:
                tarea.cancel()
            if proceso.returncode is None:
                proceso.kill()
                await proceso.wait()


async def conectar_siempre(endpoint):
    espera = 1
    while True:
        try:
            await _sesion(endpoint)
        except Exception as error:
            log.warning("Conexión perdida (%s). Reintento en %d s", error, espera)
            await asyncio.sleep(espera)
            espera = min(espera * 2, ESPERA_MAXIMA)
        else:
            espera = 1


async def servidor_salud(puerto):
    async def atender(lector, escritor):
        await lector.read(1024)
        escritor.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n"
                       b"Connection: close\r\n\r\nok")
        await escritor.drain()
        escritor.close()

    servidor = await asyncio.start_server(atender, "0.0.0.0", puerto)
    log.info("Ruta de salud escuchando en el puerto %d", puerto)
    async with servidor:
        await servidor.serve_forever()


async def main():
    endpoint = os.environ.get("MCP_ENDPOINT", "").strip()
    if not endpoint.startswith("wss://"):
        log.error("Falta MCP_ENDPOINT (debe empezar por wss://). Ponlo en el archivo .env")
        sys.exit(1)

    tareas = [conectar_siempre(endpoint)]
    if puerto := os.environ.get("PORT"):
        tareas.append(servidor_salud(int(puerto)))
    await asyncio.gather(*tareas)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Detenido por el usuario")

##hola