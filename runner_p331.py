"""
runner_p331.py
Procesa TODOS los JSONs de pendientes/ en GitHub en una sola ejecucion.
Para cada archivo: descarga → llena grilla en SAP → mueve a procesados/ o discrepancias/.
"""

import json
import logging
import os
import tempfile
from collections import defaultdict

import github_client as gh
from bot_p331_dryrun import procesar_pendiente


# ── Consolidacion cross-file ──────────────────────────────────────────────────

def consolidar_movimientos(archivos):
    """
    Descarga todos los JSONs de pendientes y consolida movimientos:
    - Elimina duplicados (mismo lote + mismo destino)
    - Detecta conflictos (mismo lote, destinos distintos)

    Retorna:
      unicos    — list de {'mov', 'path', 'sha', 'operario', 'bin_destino', 'timestamp', 'lote_norm'}
      conflictos — list de {'lote', 'descripcion', 'opciones': [...]}
      por_archivo — dict path -> sha de todos los archivos
    """
    por_lote = defaultdict(list)
    por_archivo = {}

    for item in archivos:
        path = item["path"]
        sha  = item["sha"]
        por_archivo[path] = sha

        try:
            data     = gh.descargar_json(path)
            operario = data.get("operario", "?")
            movs     = data.get("movimientos", [])

            seen_file = set()
            for m in movs:
                if m.get("huerfano") or (m.get("accion") or "") == "noop":
                    continue
                lote_raw   = (m.get("lote") or "").strip().upper()
                lote_norm  = lote_raw.lstrip("0") or lote_raw
                bin_destino = (m.get("bin_destino") or "").strip().upper()
                if not lote_norm or not bin_destino:
                    continue
                key = (lote_norm, bin_destino)
                if key in seen_file:
                    continue
                seen_file.add(key)
                por_lote[lote_norm].append({
                    "mov":        m,
                    "path":       path,
                    "sha":        sha,
                    "operario":   operario,
                    "bin_destino": bin_destino,
                    "timestamp":  m.get("timestamp", ""),
                    "lote_norm":  lote_norm,
                })
        except Exception as e:
            logging.warning(f"Error leyendo {path}: {e}")

    unicos     = []
    conflictos = []

    for lote_norm, entries in sorted(por_lote.items()):
        destinos = {e["bin_destino"] for e in entries}
        if len(destinos) == 1:
            unicos.append(entries[0])
        else:
            desc = next(
                (e["mov"].get("descripcion") or e["mov"].get("producto") or ""
                 for e in entries if e["mov"].get("descripcion") or e["mov"].get("producto")),
                ""
            )
            # Ordenar por timestamp desc; dedup por bin_destino
            opciones_all = sorted(entries, key=lambda x: x["timestamp"], reverse=True)
            seen_dest, opciones = set(), []
            for opt in opciones_all:
                if opt["bin_destino"] not in seen_dest:
                    seen_dest.add(opt["bin_destino"])
                    opciones.append(opt)
            conflictos.append({
                "lote":        lote_norm,
                "descripcion": str(desc)[:40],
                "opciones":    opciones,
            })

    return unicos, conflictos, por_archivo


# ── Ejecucion con lista explicita (post conflict-resolution) ─────────────────

def run_explicit(unicos, por_archivo, log_callback=None):
    """
    Ejecuta en SAP una lista ya deduplicada y con conflictos resueltos.
    Archiva TODOS los archivos de por_archivo al terminar.
    """
    def log(msg):
        logging.info(msg)
        if log_callback:
            log_callback(msg)

    if not unicos:
        log("Sin movimientos a procesar.")
        return {"procesados": 0, "con_discrepancias": 0, "errores": 0, "total_llenados": 0}

    log(f"{len(unicos)} movimiento(s) consolidado(s) — ejecutando en SAP...")

    data = {
        "schema":      "ejecutable_v1",
        "id":          "consolidado",
        "operario":    "CONSOLIDADO",
        "movimientos": [e["mov"] for e in unicos],
    }

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
    carpeta = "procesados" if n_err == 0 else "discrepancias"

    if n_err == 0:
        log(f"OK — {n_ok} rollo(s) registrado(s). Archivando {len(por_archivo)} archivo(s)...")
    else:
        log(f"AVISO — {n_ok} OK, {n_err} discrepancia(s). Archivando en discrepancias/...")

    errores = 0
    for path, sha in por_archivo.items():
        try:
            gh.archivar_pendiente(path, sha, carpeta)
        except Exception as e:
            errores += 1
            log(f"Error archivando {path}: {e}")

    log(f"Fin: {n_ok} rollo(s) registrado(s).")
    return {
        "procesados":        len(por_archivo),
        "con_discrepancias": 1 if n_err > 0 else 0,
        "errores":           errores,
        "total_llenados":    n_ok,
    }


# ── Ejecucion clasica por archivo (sin conflicts) ─────────────────────────────

def run_all(log_callback=None):
    """
    Itera todos los JSONs en pendientes/, los procesa en SAP y los archiva.
    Usa consolidar_movimientos para dedup cross-file. Si hay conflictos los omite
    (usar run_explicit cuando el admin ya los resolvio en el GUI).
    """
    def log(msg):
        logging.info(msg)
        if log_callback:
            log_callback(msg)

    pendientes = gh.listar_pendientes()
    if not pendientes:
        log("Sin movimientos pendientes en GitHub.")
        return {"procesados": 0, "con_discrepancias": 0, "errores": 0, "total_llenados": 0}

    log(f"{len(pendientes)} archivo(s) en pendientes/ — consolidando...")
    unicos, conflictos, por_archivo = consolidar_movimientos(pendientes)

    if conflictos:
        lotes = ", ".join(c["lote"] for c in conflictos)
        log(f"AVISO: {len(conflictos)} conflicto(s) omitidos (lotes: {lotes}). Resolver en la app.")

    return run_explicit(unicos, por_archivo, log_callback)
