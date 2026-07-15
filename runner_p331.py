"""
runner_p331.py
Procesa TODOS los JSONs de pendientes/ en GitHub en una sola ejecucion.
Para cada archivo: descarga → llena grilla en SAP (dry-run) → mueve a procesados/ o discrepancias/.
"""

import json
import logging
import os
import tempfile

import github_client as gh
from bot_p331_dryrun import procesar_pendiente


def run_all(log_callback=None):
    """
    Itera todos los JSONs en pendientes/, los procesa en SAP y los archiva.
    log_callback(str): funcion opcional para emitir mensajes al GUI en tiempo real.
    Devuelve {"procesados": N, "con_discrepancias": M, "errores": K}.
    """
    def log(msg):
        logging.info(msg)
        if log_callback:
            log_callback(msg)

    pendientes = gh.listar_pendientes()
    if not pendientes:
        log("Sin movimientos pendientes en GitHub.")
        return {"procesados": 0, "con_discrepancias": 0, "errores": 0, "total_llenados": 0}

    log(f"{len(pendientes)} archivo(s) encontrado(s) en pendientes/.")
    procesados = con_discrepancias = errores = total_llenados = 0

    for item in pendientes:
        nombre  = item["name"]
        path_gh = item["path"]
        sha     = item["sha"]
        log(f"Procesando {nombre}...")

        try:
            data = gh.descargar_json(path_gh)

            # Guarda en archivo temporal para reutilizar procesar_pendiente()
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as tmp:
                json.dump(data, tmp, ensure_ascii=False)
                tmp_path = tmp.name

            try:
                resultado = procesar_pendiente(tmp_path) or {}
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

            n_ok  = len(resultado.get("llenados", []))
            n_err = len(resultado.get("discrepancias", []))
            total_llenados += n_ok

            if n_err == 0:
                carpeta = "procesados"
                procesados += 1
                log(f"  OK — {n_ok} rollo(s) registrado(s). Archivado en procesados/.")
            else:
                carpeta = "discrepancias"
                con_discrepancias += 1
                log(f"  AVISO — {n_ok} OK, {n_err} discrepancia(s). Archivado en discrepancias/.")

            gh.archivar_pendiente(path_gh, sha, carpeta)

        except Exception as e:
            errores += 1
            log(f"  ERROR — {e}")
            logging.exception(f"Error procesando {nombre}")

    log(f"Fin: {total_llenados} rollo(s) · {con_discrepancias} archivo(s) con discrepancias · {errores} errores.")
    return {"procesados": procesados, "con_discrepancias": con_discrepancias, "errores": errores, "total_llenados": total_llenados}
