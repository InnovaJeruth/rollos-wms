"""
descargar_inventario.py

Descarga el inventario desde la transaccion /SCWM/MON en SAP GUI
y lo guarda como archivo local .txt.

Reutiliza sap_login.obtener_sesion_sap() para la conexion.

Uso:
    python descargar_inventario.py                              # carpeta y nombre por defecto
    python descargar_inventario.py -c "C:\\ruta\\destino"
    python descargar_inventario.py -c "C:\\ruta" -n "INV.txt"
    python descargar_inventario.py --almacen PD30 --tipo-desde A001 --tipo-hasta A007
"""

import argparse
import os
import threading
import time
from datetime import datetime

import win32con
import win32gui

from sap_login import obtener_sesion_sap


# =========================================================================
# Constantes del arbol de /SCWM/MON (obtenidas del macro grabado)
# =========================================================================
# El monitor "SAP" del almacen tiene un arbol. Necesitamos:
#   - expandir el nodo padre C000000011
#   - hacer doble click en el nodo hoja N000000139 ("Ubicaciones" o similar)
# Si en el futuro SAP renumera los nodos, actualizar aca.
NODO_PADRE_UBICACIONES = "C000000011"
NODO_HOJA_UBICACIONES  = "N000000139"


def _monitorear_seguridad_sap(stop_event: threading.Event) -> None:
    """
    Hilo que acepta automaticamente el dialogo 'Seguridad SAP GUI'.
    Ese dialogo es una ventana Windows nativa — no es accesible via SAP GUI
    Scripting, hay que encontrarlo con win32gui y hacer clic en 'Permitir'.
    """
    def _click_permitir(child_hwnd, _):
        if win32gui.GetWindowText(child_hwnd) in ("Permitir", "Allow"):
            win32gui.PostMessage(child_hwnd, win32con.BM_CLICK, 0, 0)
        return True

    def _buscar_y_aceptar(hwnd, _):
        titulo = win32gui.GetWindowText(hwnd)
        if win32gui.IsWindowVisible(hwnd) and (
            "Seguridad SAP" in titulo or "SAP GUI Security" in titulo
        ):
            win32gui.EnumChildWindows(hwnd, _click_permitir, None)
        return True

    while not stop_event.is_set():
        try:
            win32gui.EnumWindows(_buscar_y_aceptar, None)
        except Exception:
            pass
        time.sleep(0.3)


def _esperar_elemento(session, element_id: str, timeout: float = 15.0, interval: float = 0.3):
    """
    Espera hasta que findById(element_id) resuelva, o timeout.
    SAP GUI puede tardar en mostrar diálogos modales tras un press().
    """
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
        f"Ultimo error: {ultimo_error}\n"
        f"Estado actual: transaccion={getattr(session.info, 'transaction', '?')}"
    )


def _nombre_por_defecto() -> str:
    """INVENTARIO_DD_MM_YYYY.txt (mismo formato del macro original)."""
    return f"INVENTARIO_{datetime.now().strftime('%d_%m_%Y')}.txt"


def descargar_inventario(
    carpeta: str,
    nombre_archivo: str,
    almacen: str = "PD30",
    monitor: str = "SAP",
    tipo_desde: str = "A001",
    tipo_hasta: str = "A007",
) -> str:
    """
    Ejecuta /SCWM/MON, filtra por almacen + rango de tipos, exporta a PC.

    Args:
        carpeta: ruta absoluta destino (ej: r"C:\\Users\\...\\rollos-wms").
        nombre_archivo: nombre con extension (.txt).
        almacen: numero de almacen SAP (P_LGNUM). Default "PD30".
        monitor: nombre del monitor a ejecutar (P_MONIT). Default "SAP".
        tipo_desde / tipo_hasta: rango de tipos de almacen (S_LGTYP-LOW/HIGH).

    Returns:
        Ruta absoluta del archivo generado.
    """
    if not os.path.isabs(carpeta):
        carpeta = os.path.abspath(carpeta)
    os.makedirs(carpeta, exist_ok=True)

    # Hilo que acepta automaticamente el dialogo "Seguridad SAP GUI" si aparece.
    # Ese dialogo es una ventana Windows nativa, no accesible via SAP GUI Scripting.
    _stop_monitor = threading.Event()
    _monitor = threading.Thread(
        target=_monitorear_seguridad_sap, args=(_stop_monitor,), daemon=True
    )
    _monitor.start()

    try:
        session = obtener_sesion_sap()

        # 1) Abrir transaccion /SCWM/MON
        print(f"[SCWM/MON] Abriendo transaccion en almacen {almacen}...")
        session.findById("wnd[0]/tbar[0]/okcd").text = "/n/SCWM/MON"
        session.findById("wnd[0]/tbar[0]/btn[0]").press()

        # 2) Filtro inicial (almacen + monitor)
        # Tres variantes segun configuracion SAP del usuario:
        #   A) Popup modal en wnd[1]     — ctxtP_LGNUM en wnd[1]
        #   B) Pantalla inline en wnd[0] — ctxtP_LGNUM en wnd[0]
        #   C) Variante guardada: SAP salta el filtro y va directo al monitor
        time.sleep(0.5)
        _filtro_aplicado = False
        for wnd_filtro in ("wnd[1]", "wnd[0]"):
            try:
                campo_lgnum = _esperar_elemento(session, f"{wnd_filtro}/usr/ctxtP_LGNUM", timeout=5)
                campo_lgnum.text = almacen
                session.findById(f"{wnd_filtro}/usr/ctxtP_MONIT").text = monitor
                session.findById(f"{wnd_filtro}/tbar[0]/btn[8]").press()  # F8 = ejecutar
                _filtro_aplicado = True
                print(f"[SCWM/MON] Filtro inicial aplicado via {wnd_filtro}.")
                break
            except TimeoutError:
                continue

        if not _filtro_aplicado:
            print("[SCWM/MON] Pantalla de filtro no encontrada — monitor ya visible (variante guardada).")

        # 3) Arbol lateral: esperar a que se dibuje y navegar
        arbol = _esperar_elemento(session, "wnd[0]/usr/shell/shellcont[0]/shell")
        arbol.expandNode(NODO_PADRE_UBICACIONES)
        arbol.selectedNode = NODO_HOJA_UBICACIONES
        arbol.doubleClickNode(NODO_HOJA_UBICACIONES)

        # 4) Filtro rango de tipos de almacen (A001..A007)
        print(f"[SCWM/MON] Filtrando tipos {tipo_desde}..{tipo_hasta}...")
        time.sleep(0.5)
        _rango_aplicado = False
        for wnd_rango in ("wnd[1]", "wnd[0]"):
            try:
                campo_lgtyp = _esperar_elemento(session, f"{wnd_rango}/usr/ctxtS_LGTYP-LOW", timeout=5)
                campo_lgtyp.text = tipo_desde
                session.findById(f"{wnd_rango}/usr/ctxtS_LGTYP-HIGH").text = tipo_hasta
                session.findById(f"{wnd_rango}/tbar[0]/btn[8]").press()
                _rango_aplicado = True
                print(f"[SCWM/MON] Filtro de tipos aplicado via {wnd_rango}.")
                break
            except TimeoutError:
                continue

        if not _rango_aplicado:
            print("[SCWM/MON] Filtro de tipos no encontrado — usando datos ya cargados en el monitor.")

        # 5) Menu contextual del grid: Exportar -> PC (archivo local)
        print("[SCWM/MON] Exportando a archivo local...")
        grid = _esperar_elemento(
            session, "wnd[0]/usr/shell/shellcont[1]/shell/shellcont[0]/shell", timeout=30
        )
        grid.pressToolbarContextButton("&MB_EXPORT")
        grid.selectContextMenuItem("&PC")

        # 6) Aceptar formato por defecto (Sin conversion / texto plano)
        _esperar_elemento(session, "wnd[1]/tbar[0]/btn[0]").press()

        # 7) Dialogo de guardar: replica el flujo del macro (3 niveles anidados)
        _esperar_elemento(session, "wnd[1]/usr/ctxtDY_PATH").setFocus()
        session.findById("wnd[1]").sendVKey(4)  # F4

        _esperar_elemento(session, "wnd[2]/usr/ctxtDY_PATH").setFocus()
        session.findById("wnd[2]").sendVKey(4)

        _esperar_elemento(session, "wnd[3]/usr/ctxtDY_PATH").text = carpeta
        session.findById("wnd[3]/usr/ctxtDY_FILENAME").text = nombre_archivo
        session.findById("wnd[3]/tbar[0]/btn[11]").press()  # guardar
        session.findById("wnd[2]/tbar[0]/btn[11]").press()
        session.findById("wnd[1]/tbar[0]/btn[11]").press()

        # 8) Popup opcional "Sobrescribir archivo" (el dialogo de Seguridad SAP GUI
        #    lo maneja el hilo _monitor en paralelo, no hace falta capturarlo aqui)
        time.sleep(0.5)
        try:
            session.findById("wnd[1]/tbar[0]/btn[0]").press()
        except Exception:
            pass

        ruta_final = os.path.join(carpeta, nombre_archivo)
        print(f"[OK] Inventario exportado: {ruta_final}")
        return ruta_final

    finally:
        _stop_monitor.set()
        _monitor.join(timeout=2)


def _parse_args() -> argparse.Namespace:
    default_folder = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(
        description="Descarga inventario desde /SCWM/MON a archivo local .txt"
    )
    parser.add_argument(
        "-c", "--carpeta", default=default_folder,
        help="Carpeta destino (default: carpeta del script)"
    )
    parser.add_argument(
        "-n", "--nombre", default=_nombre_por_defecto(),
        help="Nombre del archivo (default: INVENTARIO_DD_MM_YYYY.txt)"
    )
    parser.add_argument("--almacen",     default="PD30", help="P_LGNUM (default PD30)")
    parser.add_argument("--monitor",     default="SAP",  help="P_MONIT (default SAP)")
    parser.add_argument("--tipo-desde",  default="A001", help="S_LGTYP-LOW (default A001)")
    parser.add_argument("--tipo-hasta",  default="A007", help="S_LGTYP-HIGH (default A007)")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    descargar_inventario(
        carpeta=args.carpeta,
        nombre_archivo=args.nombre,
        almacen=args.almacen,
        monitor=args.monitor,
        tipo_desde=args.tipo_desde,
        tipo_hasta=args.tipo_hasta,
    )
