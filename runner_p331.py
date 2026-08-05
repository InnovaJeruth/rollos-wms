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

def consolidar_movimientos(archivos, desde=None):
    """
    Descarga todos los JSONs de pendientes y consolida movimientos:
    - Elimina duplicados (mismo lote + mismo destino)
    - Detecta conflictos (mismo lote, destinos distintos)

    desde: str opcional "YYYY-MM-DD". Si se indica, se ignoran archivos cuya
           fecha de sesion sea anterior a ese dia (para evitar rollos obsoletos).

    Retorna:
      unicos          — list de {'mov', 'path', 'sha', 'operario', 'bin_destino', 'timestamp', 'lote_norm'}
      conflictos      — list de {'lote', 'descripcion', 'opciones': [...]}
      por_archivo     — dict path -> sha de todos los archivos
      datos_por_archivo — dict path -> data dict (cache para evitar re-descarga al archivar)
    """
    por_lote = defaultdict(list)
    por_archivo = {}
    datos_por_archivo = {}
    omitidos_por_fecha = 0

    for item in archivos:
        path = item["path"]
        sha  = item["sha"]
        por_archivo[path] = sha

        try:
            data     = gh.descargar_json(path)
            datos_por_archivo[path] = data

            # Filtro por fecha: omitir archivos de sesiones anteriores a `desde`
            if desde:
                fecha_archivo = str(data.get("fecha") or "")[:10]
                if fecha_archivo and fecha_archivo < desde:
                    omitidos_por_fecha += 1
                    logging.info(f"Omitido por fecha ({fecha_archivo} < {desde}): {path}")
                    continue

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

    if omitidos_por_fecha:
        logging.info(f"Filtro fecha: {omitidos_por_fecha} archivo(s) omitido(s) (anteriores a {desde}).")

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

    return unicos, conflictos, por_archivo, datos_por_archivo


# ── Ejecucion con lista explicita (post conflict-resolution) ─────────────────

def run_explicit(unicos, por_archivo, datos_por_archivo=None, log_callback=None):
    """
    Ejecuta en SAP una lista ya deduplicada y con conflictos resueltos.
    Archiva TODOS los archivos de por_archivo al terminar, anotando cada
    movimiento con resultado_sap: 'ok' | 'error' antes de subir a procesados/.
    """
    def log(msg):
        logging.info(msg)
        if log_callback:
            log_callback(msg)

    if not unicos:
        log("Sin movimientos a procesar.")
        return {"procesados": 0, "con_discrepancias": 0, "errores": 0, "total_llenados": 0}

    log(f"{len(unicos)} movimiento(s) consolidado(s) — ejecutando en SAP...")

    tmp_data = {
        "schema":      "ejecutable_v1",
        "id":          "consolidado",
        "operario":    "CONSOLIDADO",
        "movimientos": [e["mov"] for e in unicos],
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(tmp_data, tmp, ensure_ascii=False)
        tmp_path = tmp.name

    try:
        resultado = procesar_pendiente(tmp_path) or {}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Lookup: lote_norm → {resultado_sap, fila_sap?, motivo_sap?}
    resultado_por_lote = {}
    for item in resultado.get("llenados", []):
        lraw  = str(item.get("lote") or "").strip().upper()
        lnorm = lraw.lstrip("0") or lraw
        if lnorm:
            resultado_por_lote[lnorm] = {
                "resultado_sap": "ok",
                "fila_sap": item.get("fila_sap"),
            }
    for item in resultado.get("discrepancias", []):
        lraw  = str(item.get("lote") or "").strip().upper()
        lnorm = lraw.lstrip("0") or lraw
        if lnorm and lnorm not in resultado_por_lote:
            resultado_por_lote[lnorm] = {
                "resultado_sap": "error",
                "motivo_sap":    str(item.get("motivo") or "desconocido"),
            }

    n_ok    = len(resultado.get("llenados", []))
    n_err   = len(resultado.get("discrepancias", []))
    n_ya_ok = len(resultado.get("ya_en_destino", []))
    carpeta = "procesados" if n_err == 0 else "discrepancias"

    if n_err == 0 and n_ya_ok == 0:
        log(f"OK — {n_ok} rollo(s) registrado(s). Archivando {len(por_archivo)} archivo(s)...")
    elif n_err == 0:
        log(f"OK — {n_ok} registrado(s), {n_ya_ok} ya estaban en destino "
            f"(inventario desactualizado). Archivando {len(por_archivo)} archivo(s)...")
    else:
        log(f"AVISO — {n_ok} OK, {n_ya_ok} ya en destino, {n_err} discrepancia(s). "
            f"Archivando en discrepancias/...")

    errores = 0
    for path, sha in por_archivo.items():
        try:
            # Usar cache si está disponible, evitar re-descarga
            if datos_por_archivo and path in datos_por_archivo:
                orig = datos_por_archivo[path]
            else:
                orig = gh.descargar_json(path)

            # Anotar cada movimiento con el resultado SAP
            movs_enriq = []
            for m in orig.get("movimientos", []):
                m     = dict(m)
                lraw  = str(m.get("lote") or "").strip().upper()
                lnorm = lraw.lstrip("0") or lraw
                res   = resultado_por_lote.get(lnorm)
                if res:
                    m["resultado_sap"] = res["resultado_sap"]
                    if res.get("fila_sap") is not None:
                        m["fila_sap"] = res["fila_sap"]
                    if res.get("motivo_sap"):
                        m["motivo_sap"] = res["motivo_sap"]
                movs_enriq.append(m)

            data_enriq = {**orig, "movimientos": movs_enriq}
            nombre     = os.path.basename(path)
            path_dst   = f"{carpeta}/{nombre}"
            gh.subir_archivo(
                path_dst,
                json.dumps(data_enriq, ensure_ascii=False),
                f"bot: {carpeta} — {nombre}",
            )
            gh.eliminar_archivo(path, sha=sha,
                                mensaje_commit=f"bot: mover a {carpeta} — {nombre}")
        except Exception as e:
            errores += 1
            log(f"Error archivando {path}: {e}")

    ya_ok_txt = f", {n_ya_ok} ya en destino" if n_ya_ok else ""
    log(f"Fin: {n_ok} rollo(s) registrado(s){ya_ok_txt}.")
    return {
        "procesados":        len(por_archivo),
        "con_discrepancias": 1 if n_err > 0 else 0,
        "n_discrepancias":   n_err,
        "errores":           errores,
        "total_llenados":    n_ok,
        "ya_en_destino":     n_ya_ok,
    }


# ── Ejecucion clasica por archivo (sin conflicts) ─────────────────────────────

def run_all(log_callback=None, desde=None):
    """
    Itera todos los JSONs en pendientes/, los procesa en SAP y los archiva.
    Usa consolidar_movimientos para dedup cross-file. Si hay conflictos los omite
    (usar run_explicit cuando el admin ya los resolvio en el GUI).

    desde: str "YYYY-MM-DD" opcional — ignora sesiones anteriores a esa fecha.
    """
    def log(msg):
        logging.info(msg)
        if log_callback:
            log_callback(msg)

    pendientes = gh.listar_pendientes()
    if not pendientes:
        log("Sin movimientos pendientes en GitHub.")
        return {"procesados": 0, "con_discrepancias": 0, "errores": 0, "total_llenados": 0}

    log(f"{len(pendientes)} archivo(s) en pendientes/ — consolidando{' (desde ' + desde + ')' if desde else ''}...")
    unicos, conflictos, por_archivo, datos_por_archivo = consolidar_movimientos(pendientes, desde=desde)

    if conflictos:
        lotes = ", ".join(c["lote"] for c in conflictos)
        log(f"AVISO: {len(conflictos)} conflicto(s) omitidos (lotes: {lotes}). Resolver en la app.")

    return run_explicit(unicos, por_archivo, datos_por_archivo, log_callback)
