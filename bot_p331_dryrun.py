"""
bot_p331_dryrun.py

Bot de tareas de almacen (P331) en /SCWM/ADPROD, a partir de los JSONs
ejecutables generados por la PWA WMS Rollos (carpeta pendientes/).

Traducido 1:1 del flujo grabado por el usuario en UiPath (Main.xaml):
busca TODOS los lotes de una vez usando la ventana de "Seleccion multiple"
del campo Lote, pegando la lista via portapapeles (igual que el boton
"Upload del portapapeles" del workflow original) en vez de buscar lote
por lote.

Flujo completo:
  1. Abre /SCWM/ADPROD y busca los lotes por seleccion multiple
  2. Llena la grilla (cantidad, tipo proceso P331, bin destino) por cada fila
  3. Valida con pressEnter y cierra popups SAP
  4. Selecciona todas las filas y presiona "Crear OA + Grabar" (OK_OIP_CREATE_POST_MAT_TO)
  5. La sesion de SAP queda abierta para revision (NO se cierra)

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


def _existe(session, element_id):
    try:
        session.findById(element_id)
        return True
    except Exception:
        return False


def _cerrar_popup_si_existe(session):
    """
    Si SAP abre un popup modal (wnd[1]) despues de pressEnter en la grilla,
    lo cierra y devuelve el mensaje que contenia (para loguearlo).
    Retorna None si no habia popup.
    """
    if not _existe(session, "wnd[1]"):
        return None

    # Intentar leer el texto del popup para loguear
    mensaje = ""
    for id_txt in ("wnd[1]/usr/txtMESSTXT1", "wnd[1]/usr/txtV-MESSAGE",
                   "wnd[1]/usr/lblMESSAGE", "wnd[1]/usr/lbl[1,2]"):
        try:
            mensaje = str(session.findById(id_txt).text).strip()
            if mensaje:
                break
        except Exception:
            pass

    titulo = ""
    try:
        titulo = str(session.findById("wnd[1]").text).strip()
    except Exception:
        pass

    # Cerrar: btn SPOP-OPTION1 = "Si" en dialogo "¿Desea grabar?", luego fallbacks
    cerrado = False
    for metodo in (
        lambda: session.findById("wnd[1]/usr/btnSPOP-OPTION1").press(),
        lambda: session.findById("wnd[1]/tbar[0]/btn[0]").press(),
        lambda: session.findById("wnd[1]").sendVKey(0),
        lambda: session.findById("wnd[1]").sendVKey(13),
    ):
        try:
            metodo()
            cerrado = True
            break
        except Exception:
            pass

    etiqueta = f'"{titulo}"' if titulo else "(sin titulo)"
    texto = f': "{mensaje}"' if mensaje else ""
    print(f"  [POPUP] {etiqueta}{texto} — {'cerrado OK' if cerrado else 'NO SE PUDO CERRAR'}")
    return mensaje or titulo or "(popup sin texto)"


def _formatear_cantidad_sap(v) -> str:
    """
    Formatea la cantidad para el campo VSOLA de SAP.
    SAP EWM en locale ES/DE usa punto como separador de miles y coma como decimal.
    Ej: 88800 -> "88.800"  |  88800.5 -> "88.800,500"
    """
    if v is None or v == "":
        return ""
    try:
        f = float(str(v).replace(",", "."))
        if f == int(f):
            # Entero: separador de miles con punto (88800 -> "88.800")
            return f"{int(f):,}".replace(",", ".")
        # Con decimales: miles con punto, decimal con coma
        partes = f"{f:,.3f}".split(".")
        return partes[0].replace(",", ".") + "," + partes[1]
    except (ValueError, TypeError):
        return str(v)


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
    movs = [m for m in movs if not m["huerfano"] and m["bin_origen"] and m["bin_destino"]]
    if solo_batch_id:
        movs = [m for m in movs if m["batch_id"] == solo_batch_id]
    # Eliminar duplicados exactos (mismo lote + bin_origen + bin_destino)
    seen, deduped = set(), []
    for m in movs:
        key = (m["lote"].upper(), m["bin_origen"], m["bin_destino"])
        if key not in seen:
            seen.add(key)
            deduped.append(m)
    if len(deduped) < len(movs):
        print(f"[INFO] {len(movs) - len(deduped)} movimiento(s) duplicado(s) eliminado(s).")
    return deduped


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

    # Pegar la lista de lotes (uno por linea, como en el macro grabado).
    # SAP almacena CHARG con ceros a la izquierda (10 chars); los lotes numericos
    # llegan sin ceros desde la PWA (normLote los strip) — se vuelven a agregar aqui.
    lotes_sap = [l.zfill(10) if l.isdigit() else l for l in lotes]
    _set_clipboard("\r\n".join(lotes_sap))
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

    # Intentar llenar la columna PROCTY completa con P331 de una sola vez.
    # Algunos grids SAP soportan fillColumn; si no, se llenara fila a fila abajo.
    _col_proc_prefilled = False
    try:
        grid.selectedRows = f"0,{total_filas - 1}" if total_filas > 1 else "0"
        grid.fillColumn(COL_TIPO_PROC, PROCESO_P331)
        _col_proc_prefilled = True
        print(f"[INFO] Columna {COL_TIPO_PROC} (P331) llenada en bloque.")
    except Exception:
        print(f"[INFO] fillColumn no soportado; {COL_TIPO_PROC} se llenara por fila.")

    llenados, discrepancias, ya_en_destino = [], [], []
    lotes_identificados = set()

    t1 = time.perf_counter()
    for fila in range(total_filas):
        # Lectura directa por nombre tecnico confirmado (CHARG / VLPLA).
        # 2 lecturas por fila en vez de 49 — ~12x mas rapido que el scan completo.
        try:
            lote_raw     = grid.GetCellValue(fila, COL_LOTE).strip().upper()
            # SAP devuelve CHARG con ceros ("0000018113"); normalizamos igual que la PWA
            lote_de_fila = lote_raw.lstrip("0") or lote_raw
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
                if mov["bin_destino"] and bin_de_fila == mov["bin_destino"].upper():
                    print(f"  [YA OK] Lote {lote_de_fila}: ya en destino '{bin_de_fila}' "
                          f"(inventario PWA desactualizado, sin accion).")
                    ya_en_destino.append({**mov, "fila_sap": fila, "motivo": "ya_en_destino"})
                else:
                    print(f"  [DISCREPANCIA] Lote {lote_de_fila}: bin_origen SAP='{bin_de_fila}' "
                          f"!= esperado='{mov['bin_origen']}' "
                          f"(destino esperado: '{mov['bin_destino']}').")
                    discrepancias.append({**mov, "motivo": "bin_origen_no_coincide",
                                          "bin_sap_actual": bin_de_fila})
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

        cantidad_sap = _formatear_cantidad_sap(cantidad)
        if cantidad_sap:
            grid.modifyCell(fila, COL_CANTIDAD, cantidad_sap)
        if not _col_proc_prefilled:
            grid.modifyCell(fila, COL_TIPO_PROC, PROCESO_P331)
        grid.modifyCell(fila, COL_BIN_DESTINO, mov["bin_destino"])
        # NO pressEnter() por fila — evita el popup de validacion por cada registro.
        # SAP acepta modifyCell sin confirmacion inmediata; la validacion ocurre
        # cuando el usuario presiona Crear+Grabar al final.

        origen_cantidad = "JSON" if mov["cantidad"] else "SAP(AVAIL_QUAN)"
        aviso_cantidad = "" if cantidad else "  [!] Cantidad no obtenida — completar a mano."
        print(f"  [OK] Fila {fila} (lote {lote_de_fila}): "
              f"{mov['bin_origen']} -> {mov['bin_destino']}, "
              f"{cantidad or '(sin cantidad)'} {mov['unidad']}  [qty: {origen_cantidad}]{aviso_cantidad}")
        llenados.append({**mov, "fila_sap": fila, "cantidad_usada": cantidad,
                         "origen_cantidad": origen_cantidad})

    t_matching_y_escritura = time.perf_counter() - t1

    # Un solo Enter al final para que SAP valide todas las filas de una vez
    # (un popup unico, no uno por fila).
    grid.pressEnter()
    _cerrar_popup_si_existe(session)

    # Lotes que esperabamos pero SAP nunca devolvio en ninguna fila
    for lote in set(lotes) - lotes_identificados:
        for mov in esperados_por_lote[lote]:
            print(f"  [DISCREPANCIA] Lote {lote}: SAP no lo devolvio en la busqueda "
                  f"(¿ya fue movido, no existe, o esta en otro almacen?)")
            discrepancias.append({**mov, "motivo": "lote_no_encontrado_en_sap"})

    # =====================================================================
    # CREAR Y GRABAR ORDENES DE ALMACEN P331
    # Equivalente al selectColumn (x todas las columnas) + pressButton del
    # macro grabado por el usuario en UiPath / SAP GUI VBScript.
    # =====================================================================
    t_crear = 0.0
    if llenados:
        sin_cantidad = [m for m in llenados if not m["cantidad_usada"]]
        if sin_cantidad:
            print(f"\n  [!] {len(sin_cantidad)} fila(s) con cantidad SIN completar (VSOLA):")
            for m in sin_cantidad:
                print(f"      - Lote {m['lote']} (fila {m['fila_sap']})")

        print(f"\n[INFO] Seleccionando filas y creando {len(llenados)} orden(es) de almacen P331...")
        t2 = time.perf_counter()

        # Seleccionar todas las filas de la grilla (equivalente al selectColumn multiple del VBScript)
        try:
            grid.selectAll()
        except Exception:
            # Fallback: asignar rango de filas directamente
            try:
                grid.selectedRows = ",".join(str(i) for i in range(total_filas))
            except Exception as e:
                print(f"  [AVISO] No se pudo seleccionar filas automaticamente: {e}")

        # Boton "Crear OA + Grabar movimiento de material" — OK_OIP_CREATE_POST_MAT_TO
        session.findById(TOOLBAR_ID).pressButton("OK_OIP_CREATE_POST_MAT_TO")

        # SAP puede tardar hasta 2s en mostrar el popup (confirmacion de OAs o "¿Desea grabar?")
        time.sleep(2.0)
        msg_confirmacion = _cerrar_popup_si_existe(session)
        if msg_confirmacion:
            print(f"  [SAP] {msg_confirmacion}")
        # Puede aparecer un segundo popup encadenado
        time.sleep(0.5)
        msg2 = _cerrar_popup_si_existe(session)
        if msg2:
            print(f"  [SAP] (popup 2) {msg2}")

        t_crear = time.perf_counter() - t2
        print(f"[OK] Ordenes de almacen creadas y grabadas en {t_crear:.2f}s.")
    else:
        print("\n[AVISO] Sin filas llenadas — no se creo ninguna orden de almacen.")

    # =====================================================================
    # RESUMEN
    # =====================================================================
    print("\n" + "=" * 70)
    print(f"RESUMEN — {ruta_json}")
    print("=" * 70)
    print(f"  Tiempo busqueda en SAP        : {t_busqueda:.2f}s")
    print(f"  Tiempo matching + escritura   : {t_matching_y_escritura:.2f}s "
          f"({total_filas} fila(s) x {len(columnas)} columna(s) escaneadas)")
    if llenados:
        print(f"  Tiempo creacion OAs           : {t_crear:.2f}s")
    print(f"  Tiempo total                  : {t_busqueda + t_matching_y_escritura + t_crear:.2f}s")
    print(f"  Ordenes de almacen creadas   : {len(llenados)}")
    print(f"  Ya en destino (sin accion)   : {len(ya_en_destino)}")
    print(f"  Discrepancias (no procesadas): {len(discrepancias)}")
    if ya_en_destino:
        print(f"\n  [INFO] {len(ya_en_destino)} rollo(s) ya estaban en la ubicacion destino")
        print(f"         en SAP — el inventario PWA estaba desactualizado para esos lotes.")
        print(f"         Actualizar el inventario en el admin para que no aparezcan")
        print(f"         como mal ubicados en el proximo escaneo.")
    if discrepancias:
        print("\n  Detalle de discrepancias:")
        for d in discrepancias:
            extra = f" | SAP actual: '{d.get('bin_sap_actual', '?')}'" if d.get("bin_sap_actual") else ""
            print(f"    - Lote {d['lote']}: {d['motivo']}{extra}")

    print("\nLa sesion de SAP queda ABIERTA para revision.")
    return {"llenados": llenados, "discrepancias": discrepancias, "ya_en_destino": ya_en_destino}


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
