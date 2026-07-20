"""
sap_login.py
Módulo reutilizable para conectarse a SAP GUI de forma inteligente.
"""

import win32com.client
import pythoncom
import subprocess
import time
import os
import configparser
from dotenv import load_dotenv

# Cargar variables de entorno (Credenciales)
load_dotenv()
SAP_USER = os.getenv("SAP_USER")
SAP_PASSWORD = os.getenv("SAP_PASSWORD")

# Cargar configuraciones del INI
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
config = configparser.ConfigParser()
config.read(os.path.join(BASE_DIR, 'sap_config.ini'))

SERVIDOR = config['SAP']['servidor']
MANDANTE = config['SAP']['mandante']
IDIOMA   = config['SAP']['idioma']

def abrir_saplogon():
    """Abre el proceso saplogon.exe si no está en ejecución."""
    try:
        # Verifica si el proceso ya existe
        subprocess.check_output('tasklist | findstr "saplogon.exe"', shell=True)
    except subprocess.CalledProcessError:
        print("🚀 Abriendo SAP Logon...")
        # Ruta por defecto de SAP en la mayoría de instalaciones
        ruta_sap = r"C:\Program Files (x86)\SAP\FrontEnd\SAPgui\saplogon.exe"
        if not os.path.exists(ruta_sap):
            ruta_sap = r"C:\Program Files\SAP\FrontEnd\SAPgui\saplogon.exe"
        subprocess.Popen(ruta_sap)
        time.sleep(5) # Esperar a que cargue la interfaz

def _existe(session, element_id):
    """True si el elemento existe en la sesión, False si no."""
    try:
        session.findById(element_id)
        return True
    except Exception:
        return False


def _leer_statusbar(session):
    """
    Devuelve (tipo, texto) de la barra de status de wnd[0].
    Tipos comunes SAP: 'S' (success), 'W' (warning), 'E' (error), 'A' (abort), 'I' (info).
    """
    try:
        sbar = session.findById("wnd[0]/sbar")
        return (sbar.messageType or "").strip(), (sbar.text or "").strip()
    except Exception:
        return "", ""


def _cerrar_popups_post_login(session):
    """
    Después del Enter en el login, SAP puede mostrar 1..N popups:
      - Multi-logon (usuario ya conectado en otra terminal)
      - Aviso de sistema / copyright
      - Cambio de contraseña obligatorio (expirada)
    Devuelve un mensaje descriptivo si detecta un caso que requiere intervención humana.
    """
    # Multi-logon: continuar con este y finalizar los demás
    if _existe(session, "wnd[1]/usr/radMULTI_LOGON_OPT1"):
        session.findById("wnd[1]/usr/radMULTI_LOGON_OPT1").select()
        session.findById("wnd[1]").sendVKey(0)
        time.sleep(0.5)

    # Cambio de contraseña obligatorio (contraseña expirada)
    # SAP muestra wnd[1] con campos RSYST-NCODE / RSYST-NCOD2 y NO permite continuar sin cambiarla.
    if _existe(session, "wnd[1]/usr/pwdRSYST-NCODE"):
        return ("Contraseña expirada. SAP requiere cambiarla desde la interfaz "
                "gráfica antes de poder usar el asistente.")

    # Aviso de sistema / copyright: cerrar con OK (btn[0]) si aparece
    if _existe(session, "wnd[1]"):
        try:
            session.findById("wnd[1]").sendVKey(0)
            time.sleep(0.3)
        except Exception:
            pass

    return None


def _sigue_en_login(session):
    """
    True si tras el intento de login todavía estamos en la pantalla de login
    (indica credenciales rechazadas u otro error).
    """
    return _existe(session, "wnd[0]/usr/txtRSYST-BNAME")


def obtener_sesion_sap():
    """
    Detecta el estado de SAP y retorna la sesión activa (session(0)).
    Hace login automático si es necesario y **valida que el login haya sido exitoso**.

    Lanza RuntimeError si:
      - No puede conectar al Scripting Engine
      - Faltan credenciales en .env
      - Las credenciales son rechazadas por SAP
      - La contraseña está expirada
    """
    # Inicializar COM en este thread (necesario si se llama desde un thread secundario)
    pythoncom.CoInitialize()

    abrir_saplogon()

    SapGuiAuto = None
    last_err = None

    # Intento 1: moniker directo (funciona en la mayoría de equipos)
    try:
        SapGuiAuto = win32com.client.GetObject("SAPGUI")
    except Exception as e:
        last_err = e

    # Intento 2: SAP ROT Wrapper (necesario en algunos Windows donde el moniker falla)
    if SapGuiAuto is None:
        try:
            rot = win32com.client.Dispatch("SapROTWr.SapROTWrapper")
            SapGuiAuto = rot.GetROTEntry("SAPGUI")
        except Exception as e2:
            last_err = e2

    if SapGuiAuto is None:
        raise RuntimeError(
            f"❌ No se pudo conectar al Scripting Engine de SAP.\n"
            f"   Verifique:\n"
            f"     1. SAP GUI esté abierto\n"
            f"     2. Scripting habilitado: Opciones → Accesibilidad → Enable Scripting\n"
            f"     3. No esté bloqueado por política de equipo\n"
            f"   Detalle: {last_err}"
        )

    try:
        application = SapGuiAuto.GetScriptingEngine
    except Exception as e:
        raise RuntimeError(f"❌ Error al obtener el Scripting Engine de SAP: {e}")

    # 1. Si no hay conexiones (Pantalla principal de servidores)
    if application.Children.Count == 0:
        print(f"🔌 Conectando al servidor: {SERVIDOR}")
        connection = application.OpenConnection(SERVIDOR, True)
        time.sleep(2)
    else:
        connection = application.Children(0)

    # 2. Obtener la sesión activa
    if connection.Children.Count == 0:
        raise RuntimeError("No se pudo crear una sesión en la conexión.")

    session = connection.Children(0)

    # 3. Validar estado de la sesión (¿Estamos en la pantalla de Login?)
    en_login = _existe(session, "wnd[0]/usr/txtRSYST-BNAME")

    if en_login:
        print("🔑 Pantalla de login detectada. Ingresando credenciales...")
        if not SAP_USER or not SAP_PASSWORD:
            raise ValueError("Faltan SAP_USER o SAP_PASSWORD en el archivo .env")

        session.findById("wnd[0]/usr/txtRSYST-MANDT").text = MANDANTE
        session.findById("wnd[0]/usr/txtRSYST-BNAME").text = SAP_USER
        session.findById("wnd[0]/usr/pwdRSYST-BCODE").text = SAP_PASSWORD
        session.findById("wnd[0]/usr/txtRSYST-LANGU").text = IDIOMA
        session.findById("wnd[0]").sendVKey(0)  # Enter

        # Dar tiempo a que SAP procese el login antes de validar
        time.sleep(0.8)

        # Cerrar popups post-login (multi-logon, aviso, etc.) y detectar bloqueos
        motivo = _cerrar_popups_post_login(session)
        if motivo:
            raise RuntimeError(f"❌ Login bloqueado por SAP: {motivo}")

        # VALIDACIÓN: si seguimos en la pantalla de login, el login fue rechazado
        time.sleep(0.3)
        if _sigue_en_login(session):
            tipo, msg = _leer_statusbar(session)
            detalle = msg if msg else "credenciales rechazadas (sin mensaje de SAP)"
            raise RuntimeError(
                f"❌ Login fallido ({tipo or 'sin tipo'}): {detalle}\n"
                f"   Verificá SAP_USER / SAP_PASSWORD en .env y el mandante en sap_config.ini."
            )

        # VALIDACIÓN adicional: si el statusbar reporta error tras salir del login
        tipo, msg = _leer_statusbar(session)
        if tipo in ("E", "A") and msg:
            raise RuntimeError(f"❌ SAP reportó error tras login ({tipo}): {msg}")

        info_transaccion = getattr(session.info, "transaction", "") or ""
        print(f"✅ Login exitoso (transacción actual: {info_transaccion or 'menú principal'}).")
    else:
        info_transaccion = session.info.transaction
        if info_transaccion == "SESSION_MANAGER":
            print("✅ Ya existe una sesión activa en el menú principal.")
        else:
            print(f"✅ Ya existe una sesión activa (Actualmente en la transacción {info_transaccion}).")

    return session