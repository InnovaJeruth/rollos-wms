"""
bot_p331_dryrun.py

Bot de preparacion de tareas de almacen (P331) en /SCWM/ADPROD, a partir
de los JSONs ejecutables generados por la PWA WMS Rollos (carpeta pendientes/).

Traducido 1:1 del flujo grabado por el usuario en UiPath (Main.xaml):
busca TODOS los lotes de una vez usando la ventana de "Seleccion multiple"
del campo Lote, pegando la lista via portapapeles (igual que el boton
"Upload del portapapeles" del workflow original) en vez de buscar lote
por lote.

*** MODO DRY-RUN — NO CREA TAREAS EN SAP ***
Este script llena la grilla de /SCWM/ADPROD (cantidad, tipo de proceso,
ubicacion destino) y valida que cada fila corresponda al lote/bin esperado,
pero SE DETIENE antes de presionar el boton que efectivamente crea/graba
la tarea de almacen. Esa linea esta comentada explicitamente mas abajo
(buscar "NO DESCOMENTAR").

Tampoco cierra la sesion de SAP al finalizar: se deja abierta para que
el usuario revise la grilla manualmente antes de decidir si crear la
tarea de verdad (agregando la linea comentada) o cancelar.

Uso:
    python bot_p331_dryrun.py                              # usa el primer JSON de pendientes/
    python bot_p331_dryrun.py -f pendientes/movimientos_x.json
    python bot_p331_dryrun.py -f pendientes/movimientos_x.json --batch bmfofw   # solo ese batch_id
"""

import argparse
import glob
import json
import os
import time

import win32clipboard

from sap_login import obtener_sesion_sap


# =========================================================================
# IDs de pantalla /SCWM/ADPROD (tomados del macro/XAML grabado por el usuario)
# =========================================================================
SUB_BASE = "wnd[0]/usr/subSUB_COMPLETE_OIP:/SCWM/SAPLUI_ADMA:2000"

BTN_TOGGLE_BUSQUEDA = f"{SUB_BASE}/btnGV_BUTTON_TEXT"

# Boton de "Seleccion multiple" (F4) al lado del campo Lote -> abre wnd[1]
BTN_MULTI_VALOR_LOTE = (f"{SUB_BASE}/subSUB_ADVANCED_SEARCH:/SCWM/SAPLUI_ADMA:2300/"
                        f"subSUB_SELECTION_SCREEN:/SCWM/SAPLUI_ADMA:2500/"
                        f"btn%_P_BATCH_%_APP_%-VALU_PUSH")

BTN_START_ADVANCED  = (f"{SUB_BASE}/subSUB_ADVANCED_SEARCH:/SCWM/SAPLUI_ADMA:2300/"
                       f"subSUB_AS_BUTTONS:/SCMB/SAPLSERVICES:1000/btnCMD_START_ADVANCED")

GRID_ID = (f"{SUB_BASE}/subSUB_OIP_DATA_AREA:/SCWM/SAPLUI_ADMA:2210/"
           f"subSUB_OIP_1_DATA:/SCWM/SAPLUI_ADMA:2211/cntlCONTAINER_ALV_OIP_1/shellcont/shell")

TOOLBAR_ID = (f"{SUB_BASE}/subSUB_OIP_DATA_AREA:/SCWM/SAPLUI_ADMA:2210/"
              f"cntlCONTAINER_TB_OIP_1/shellcont/shell")

# Columnas confirmadas por el macro grabado (ESCRIBIR)
COL_CANTIDAD    = "VSOLA"
COL_TIPO_PROC   = "PROCTY"
COL_BIN_DESTINO = "NLPLA"
PROCESO_P331    = "P331"

# Columnas confirmadas por diagnostico piloto 2026-07-13 (LEER para matching)
COL_LOTE        = "CHARG"   # Lote
COL_BIN_ORIGEN  = "VLPLA"   # Ubic. procedencia
COL_DISP        = "AVAIL_QUAN"  # Cantidad disponible (auto-relleno si JSON no trae cantidad)


# =========================================================================
# Espera robusta de elementos (SAP puede tardar en pintar ventanas modales)
# =========================================================================
def _esperar_elemento(session, element_id, timeout=15.0, interval=0.3):
    fin = time.time() + timeout
    ultimo_error = None
    while time.time() < fin:
        try:
            return session.findById(element_id)
        except Exception as e:
            ultimo_error = e
            time.sleep(interval)
    raise TimeoutError(
        f"Elemento no aparecio en {timeout}s: {element_id}\n"
        f"Ultimo error: {ultimo_error}"
    )


# =========================================================================
# Normalizacion del JSON de pendientes (soporta ambos schemas encontrados
# en el repo: el viejo -pre-split- con bin_sap/bin_real, y ejecutable_v1
# con bin_origen ya resuelto)
# =========================================================================
def normalizar_movimiento(m):
    """Devuelve {lote, producto, bin_origen, bin_destino, cantidad, unidad, batch_id}."""
    bin_origen = m.get("bin_origen") or m.get("bin_sap") or m.get("bin_real")
    return {
        "lote": str(m["lote"]).strip(),
        "producto": m.get("producto", ""),
        "bin_origen": str(bin_origen or "").strip().upper(),
        "bin_destino": str(m.get("bin_destino", "")).strip().upper(),
        "cantidad": str(m.get("cantidad", "")).strip(),
        "unidad": m.get("unidad", ""),
        "batch_id": m.get("batch_id"),
        "huerfano": bool(m.get("huerfano", False)),
    }


def cargar_movimientos(ruta_json, solo_batch_id=None):
    with open(ruta_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    movs = [normalizar_movimiento(m) for m in data.get("movimientos", [])]
    # Los huerfanos no tienen bin_origen valido en SAP -> P331 no puede ejecutarlos
    movs = [m for m in movs if not m["huerfano"] and m["bin_origen"] and m["bin_destino"]]
    if solo_batch_id:
        movs = [m for m in movs if m["batch_id"] == solo_batch_id]
    return movs


# =========================================================================
# Portapapeles (equivalente a "Set Clipboard" + "Upload del portapapeles"
# del workflow de UiPath)
# =========================================================================
def _set_clipboard(texto):
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(texto, win32clipboard.CF_TEXT)
    finally:
        win32clipboard.CloseClipboard()


# =========================================================================
# Busqueda MULTIPLE por lote (igual que el macro/XAML grabado):
# abre la ventana de "Seleccion multiple" del campo Lote, pega la lista
# de lotes via portapapeles, confirma y ejecuta la busqueda ampliada.
# =========================================================================
def buscar_lotes_multiple(session, lotes):
    """
    Ejecuta /SCWM/ADPROD y busca TODOS los lotes de una vez usando el
    popup de seleccion multiple (Ctrl+V de una lista, igual que un
    usuario lo haria a mano). Devuelve el grid ya poblado con los
    resultados de todos los lotes encontrados.
    """
    session.findById("wnd[0]/tbar[0]/okcd").text = "/n/SCWM/ADPROD"
    session.findById("wnd[0]/tbar[0]/btn[0]").press()

    _esperar_elemento(session, BTN_TOGGLE_BUSQUEDA).press()
    _esperar_elemento(session, BTN_MULTI_VALOR_LOTE).press()

    # Pegar la lista de lotes (uno por linea, como en el macro grabado)
    _set_clipboard("\r\n".join(lotes))
    _esperar_elemento(session, "wnd[1]/tbar[0]/btn[24]").press()  # Upload del portapapeles
    session.findById("wnd[1]/tbar[0]/btn[8]").press()             # Tomar (F8)

    session.findById(BTN_START_ADVANCED).press()  # Busq. ampliada

    return _esperar_elemento(session, GRID_ID, timeout=20)


# =========================================================================
# Matching generico por VALOR (no por nombre tecnico de columna)
# =========================================================================
# No tenemos confirmado si esta grilla expone nombres tecnicos como CHARG
# (lote) o VLPLA (ubic. procedencia) via GetCellValue — a diferencia de
# UiPath, que extrae la tabla usando los headers VISIBLES en pantalla
# ("Lote", "Ubic.procedencia") gracias a su motor de UI Automation.
#
# Para no depender de adivinar el nombre tecnico correcto, escaneamos
# TODAS las columnas de cada fila y comparamos por VALOR literal contra
# lo que ya sabemos que estamos buscando (el lote) o esperando (el bin
# origen). Mas lento, pero no puede fallar por un nombre de campo mal
# supuesto.
def _valores_de_fila(grid, fila, columnas):
    valores = []
    for col in columnas:
        try:
            val = grid.GetCellValue(fila, col)
        except Exception:
            continue
        if val:
            valores.append(val.strip())
    return valores


def _fila_contiene_valor(valores_fila, valor_buscado):
    if not valor_buscado:
        return False
    objetivo = valor_buscado.strip().upper()
    return any(v.upper() == objetivo for v in valores_fila)


# =========================================================================
# Diagnostico de columnas (solo lectura, no modifica nada)
# =========================================================================
# Intenta obtener el nombre TECNICO junto con su TITULO visible (si el API
# de scripting de esta grilla lo expone) y el valor de la fila 0, para que
# cada corrida real vaya dejando evidencia de que campo es cual. Si mas
# adelante confirmamos, por ejemplo, que "CHARG" siempre es el Lote, se
# podria usar lectura directa por columna en vez de escanear toda la fila
# (mas rapido) — pero solo una vez confirmado, no antes.
def imprimir_diagnostico_columnas(grid):
    columnas = list(grid.ColumnOrder)
    total_filas = grid.RowCount
    print(f"\n[DIAGNOSTICO] {len(columnas)} columna(s) tecnica(s), {total_filas} fila(s).")
    if total_filas == 0:
        print("[DIAGNOSTICO] Sin filas, no hay valores de ejemplo para mostrar.")
        return

    for i, col in enumerate(columnas):
        titulo = None
        for metodo in ("GetColumnTitle", "GetColumnTitles"):
            try:
                raw = getattr(grid, metodo)(i)
                titulo = str(raw)
                break
            except Exception:
                continue
        try:
            ejemplo = grid.GetCellValue(0, col)
        except Exception:
            ejemplo = "(no legible)"
        titulo_txt = f" | titulo: '{titulo}'" if titulo is not None else " | titulo: (no soportado por este grid)"
        print(f"    {col:20s} = '{ejemplo}'{titulo_txt}")


# =========================================================================
# Flujo principal
# =========================================================================
def procesar_pendiente(ruta_json, solo_batch_id=None):
    movimientos = cargar_movimientos(ruta_json, solo_batch_id)
    if not movimientos:
        print(f"[AVISO] No hay movimientos ejecutables en {ruta_json}"
              f"{' para el batch ' + solo_batch_id if solo_batch_id else ''}.")
        return

    # Agrupar los movimientos esperados por lote. Normalmente hay uno solo
    # por lote, pero si el mismo lote aparece 2 veces en el JSON (o SAP
    # tiene el stock partido en 2 bines), se desambigua mas abajo por bin_origen.
    esperados_por_lote = {}
    for mov in movimientos:
        esperados_por_lote.setdefault(mov["lote"].upper(), []).append(mov)

    lotes = sorted(esperados_por_lote.keys())
    print(f"[INFO] {len(movimientos)} movimiento(s) / {len(lotes)} lote(s) unico(s) "
          f"a preparar desde {ruta_json}")

    session = obtener_sesion_sap()

    print(f"[INFO] Buscando los {len(lotes)} lote(s) en /SCWM/ADPROD (seleccion multiple)...")
    t0 = time.perf_counter()
    grid = buscar_lotes_multiple(session, lotes)
    t_busqueda = time.perf_counter() - t0

    columnas = list(grid.ColumnOrder)
    total_filas = grid.RowCount
    print(f"[INFO] SAP devolvio {total_filas} fila(s) en {t_busqueda:.2f}s.")

    imprimir_diagnostico_columnas(grid)

    llenados, discrepancias = [], []
    lotes_identificados = set()

    t1 = time.perf_counter()
    for fila in range(total_filas):
        # Lectura directa por nombre tecnico confirmado (CHARG / VLPLA).
        # 2 lecturas por fila en vez de 49 — ~12x mas rapido que el scan completo.
        try:
            lote_de_fila = grid.GetCellValue(fila, COL_LOTE).strip().upper()
            bin_de_fila  = grid.GetCellValue(fila, COL_BIN_ORIGEN).strip().upper()
        except Exception as e:
            print(f"  [AVISO] Fila {fila}: no se pudo leer CHARG/VLPLA ({e}). Se ignora.")
            continue

        if lote_de_fila not in esperados_por_lote:
            print(f"  [AVISO] Fila {fila}: lote '{lote_de_fila}' no esperado. Se ignora.")
            continue

        lotes_identificados.add(lote_de_fila)
        candidatos = esperados_por_lote[lote_de_fila]

        # Elegir movimiento correcto dentro del lote (normalmente solo uno;
        # si hay varios, se desambigua por bin_origen).
        if len(candidatos) == 1:
            mov = candidatos[0]
            if bin_de_fila != mov["bin_origen"].upper():
                print(f"  [DISCREPANCIA] Lote {lote_de_fila}: bin_origen SAP='{bin_de_fila}' "
                      f"!= esperado='{mov['bin_origen']}'.")
                discrepancias.append({**mov, "motivo": "bin_origen_no_coincide"})
                continue
        else:
            coincidencias = [m for m in candidatos if bin_de_fila == m["bin_origen"].upper()]
            if len(coincidencias) == 0:
                print(f"  [DISCREPANCIA] Lote {lote_de_fila}: bin '{bin_de_fila}' no coincide "
                      f"con ninguno de los {len(candidatos)} bin_origen esperados.")
                discrepancias.append({"lote": lote_de_fila, "motivo": "bin_origen_no_coincide_multiple"})
                continue
            if len(coincidencias) > 1:
                print(f"  [DISCREPANCIA] Lote {lote_de_fila}: match ambiguo. Requiere revision manual.")
                discrepancias.append({"lote": lote_de_fila, "motivo": "match_ambiguo"})
                continue
            mov = coincidencias[0]

        # Cantidad: usar la del JSON si viene, si no leer AVAIL_QUAN del grid
        # (mover todo el stock disponible de esa ubicacion).
        cantidad = mov["cantidad"]
        if not cantidad:
            try:
                cantidad = grid.GetCellValue(fila, COL_DISP).strip()
            except Exception:
                cantidad = ""

        if cantidad:
            grid.modifyCell(fila, COL_CANTIDAD, cantidad)
        grid.modifyCell(fila, COL_TIPO_PROC, PROCESO_P331)
        grid.modifyCell(fila, COL_BIN_DESTINO, mov["bin_destino"])
        grid.pressEnter()

        # Cerrar popup de validacion si SAP abre alguno (no confirma la tarea).
        try:
            session.findById("wnd[1]/tbar[0]/btn[0]").press()
        except Exception:
            pass

        origen_cantidad = "JSON" if mov["cantidad"] else "SAP(AVAIL_QUAN)"
        aviso_cantidad = "" if cantidad else "  [!] Cantidad no obtenida — completar a mano."
        print(f"  [OK] Fila {fila} (lote {lote_de_fila}): "
              f"{mov['bin_origen']} -> {mov['bin_destino']}, "
              f"{cantidad or '(sin cantidad)'} {mov['unidad']}  [qty: {origen_cantidad}]{aviso_cantidad}")
        llenados.append({**mov, "fila_sap": fila, "cantidad_usada": cantidad,
                         "origen_cantidad": origen_cantidad})

    t_matching_y_escritura = time.perf_counter() - t1

    # Lotes que esperabamos pero SAP nunca devolvio en ninguna fila
    for lote in set(lotes) - lotes_identificados:
        for mov in esperados_por_lote[lote]:
            print(f"  [DISCREPANCIA] Lote {lote}: SAP no lo devolvio en la busqueda "
                  f"(¿ya fue movido, no existe, o esta en otro almacen?)")
            discrepancias.append({**mov, "motivo": "lote_no_encontrado_en_sap"})

    # =====================================================================
    # RESUMEN — el script termina aca. NO se crea ninguna tarea de almacen.
    # =====================================================================
    print("\n" + "=" * 70)
    print(f"RESUMEN DRY-RUN — {ruta_json}")
    print("=" * 70)
    print(f"  Tiempo busqueda en SAP        : {t_busqueda:.2f}s")
    print(f"  Tiempo matching + escritura   : {t_matching_y_escritura:.2f}s "
          f"({total_filas} fila(s) x {len(columnas)} columna(s) escaneadas)")
    print(f"  Tiempo total                  : {t_busqueda + t_matching_y_escritura:.2f}s")
    print(f"  Filas llenadas y verificadas : {len(llenados)}")
    print(f"  Discrepancias (sin llenar)   : {len(discrepancias)}")
    if discrepancias:
        print("\n  Detalle de discrepancias:")
        for d in discrepancias:
            print(f"    - Lote {d['lote']}: {d['motivo']}")

    sin_cantidad = [m for m in llenados if not m["cantidad_usada"]]
    if sin_cantidad:
        print(f"\n  [!] {len(sin_cantidad)} fila(s) quedaron con cantidad SIN completar "
              f"(columna VSOLA). Antes de crear la tarea real, revisa y completa "
              f"esos valores a mano en la pantalla de SAP:")
        for m in sin_cantidad:
            print(f"      - Lote {m['lote']} (fila {m['fila_sap']})")

    print("\n[IMPORTANTE] Las tareas de almacen NO fueron creadas ni grabadas.")
    print("La sesion de SAP queda ABIERTA en la ultima pantalla de /SCWM/ADPROD")
    print("para que puedas revisar la grilla manualmente.")
    print("Si todo se ve correcto, el boton de creacion real en SAP GUI es:")
    print(f'    session.findById("{TOOLBAR_ID}").pressButton "OK_OIP_CREATE_POST_MAT_TO"')
    print("(Esa linea esta comentada mas abajo en el codigo — NO se ejecuta automaticamente.)")

    # -------------------------------------------------------------------
    # NO DESCOMENTAR sin validar manualmente la grilla primero.
    # Esta es la linea que efectivamente CREA/GRABA la tarea de almacen
    # en SAP (equivalente al boton final del macro grabado). Se deja
    # comentada a proposito: este script es solo de preparacion/verificacion.
    #
    # session.findById(TOOLBAR_ID).pressButton("OK_OIP_CREATE_POST_MAT_TO")
    # -------------------------------------------------------------------

    # No se cierra la sesion ni la ventana de SAP: se deja tal cual quedo
    # para revision manual del usuario.
    return {"llenados": llenados, "discrepancias": discrepancias}


def _elegir_json_por_defecto():
    candidatos = sorted(glob.glob(os.path.join("pendientes", "*.json")))
    if not candidatos:
        raise FileNotFoundError("No hay archivos en pendientes/. Indica uno con -f.")
    return candidatos[0]


def _parse_args():
    p = argparse.ArgumentParser(
        description="Prepara (dry-run) tareas P331 en /SCWM/ADPROD desde un JSON de pendientes/. "
                    "No crea tareas en SAP ni cierra la sesion."
    )
    p.add_argument("-f", "--archivo", default=None,
                   help="Ruta al JSON de pendientes/. Default: el primero alfabeticamente.")
    p.add_argument("--batch", default=None,
                   help="Procesar solo los movimientos de este batch_id.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    ruta = args.archivo or _elegir_json_por_defecto()
    procesar_pendiente(ruta, solo_batch_id=args.batch)
