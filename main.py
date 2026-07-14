"""
main.py
WMS SAP Bot — ventana de control para TEXCORP S.A.C.
Dos botones: Descargar inventario / Registrar movimientos P331.
Logs tecnicos en logs/wms_YYYY-MM-DD.log (invisibles para el usuario).
"""

import math
import os
import queue
import sys
import threading
import datetime
import logging
import tkinter as tk

# ── Logging a archivo ────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(_BASE_DIR)  # siempre trabajar desde la carpeta del script

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join("logs", f"wms_{datetime.date.today():%Y-%m-%d}.log"),
            encoding="utf-8",
        )
    ],
)

# ── Imports de negocio ───────────────────────────────────────────────────────
_import_error = None
try:
    import github_client as gh
    import runner_p331
    import descargar_inventario as inv_mod
    import txt_parser
except Exception as e:
    _import_error = str(e)
    logging.exception("Error al importar modulos")

# ── Paleta ───────────────────────────────────────────────────────────────────
BG       = "#1a1a1a"
BG2      = "#252525"
SEP      = "#2e2e2e"
GREEN    = "#1e7a52"
GREEN_H  = "#165a3a"
GREEN_LT = "#5de8b0"
BLUE     = "#1a4f82"
BLUE_H   = "#123a62"
BLUE_LT  = "#5db0e8"
DIS_BG   = "#1e2535"
DIS_FG   = "#3a5570"
WHITE    = "#eeeeee"
MUTED    = "#555555"
OK_BG    = "#0e2d1e"
OK_FG    = "#5de8b0"
WARN_BG  = "#2a2410"
WARN_FG  = "#e8c85d"
ERR_BG   = "#2d0e0e"
ERR_FG   = "#e87b5d"


class WMSApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("WMS SAP Bot — TEXCORP")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry("360x500")

        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._anim_angle = 0.0
        self._anim_x = -90.0
        self._anim_id = None
        self._pendientes = 0

        self._build_ui()
        self._refresh_pendientes()
        self._poll_queue()

    # ── Construccion de UI ───────────────────────────────────────────────────

    def _build_ui(self):
        # Encabezado
        tk.Label(self.root, text="WMS SAP Bot",
                 font=("Segoe UI", 20, "bold"), bg=BG, fg=WHITE).pack(pady=(28, 2))
        tk.Label(self.root, text="Almacen TEXCORP S.A.C.",
                 font=("Segoe UI", 11), bg=BG, fg=MUTED).pack()

        tk.Frame(self.root, height=1, bg=SEP).pack(fill="x", padx=28, pady=22)

        # Boton 1 — Descargar inventario
        self.btn_inv = tk.Button(
            self.root,
            text="📥   Descargar inventario",
            font=("Segoe UI", 13, "bold"),
            bg=GREEN, fg=WHITE, activebackground=GREEN_H, activeforeground=WHITE,
            relief="flat", bd=0, pady=15, cursor="hand2",
            command=self._on_descargar,
        )
        self.btn_inv.pack(fill="x", padx=28, pady=(0, 12))

        # Boton 2 — Registrar movimientos
        self.btn_reg = tk.Button(
            self.root,
            text="▶   Registrar movimientos",
            font=("Segoe UI", 13, "bold"),
            bg=BLUE, fg=WHITE, activebackground=BLUE_H, activeforeground=WHITE,
            relief="flat", bd=0, pady=15, cursor="hand2",
            command=self._on_registrar,
        )
        self.btn_reg.pack(fill="x", padx=28)

        # Canvas con rollos animados (oculto hasta que empieza una tarea)
        self.canvas = tk.Canvas(self.root, height=56, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="x", padx=28, pady=(18, 0))

        # Mensaje de estado al usuario
        self.lbl_status = tk.Label(
            self.root, text="", font=("Segoe UI", 12),
            bg=BG, fg=WHITE, wraplength=308,
        )
        self.lbl_status.pack(pady=(8, 0), padx=28)

        # Footer
        self.lbl_footer = tk.Label(
            self.root, text="Verificando conexion...",
            font=("Segoe UI", 10), bg=BG, fg=MUTED,
        )
        self.lbl_footer.pack(side="bottom", pady=16)

    # ── Animacion de rollos de tela ──────────────────────────────────────────

    def _tick_anim(self):
        if not self._running:
            self.canvas.delete("roll")
            return

        w = self.canvas.winfo_width() or 304
        y  = 38
        r  = 14
        gap = 36
        self.canvas.delete("roll")

        # piso
        self.canvas.create_line(0, y + r + 3, w, y + r + 3,
                                fill=SEP, width=1, tags="roll")

        for i in range(3):
            cx = (self._anim_x + i * gap) % (w + gap * 3) - gap
            # circulo exterior
            self.canvas.create_oval(cx - r, y - r, cx + r, y + r,
                                    outline=GREEN_LT, width=2, tags="roll")
            # linea interna que rota (simula rollo girando)
            a = math.radians(self._anim_angle + i * 60)
            x1 = cx + (r - 4) * math.cos(a)
            y1 = y  + (r - 4) * math.sin(a)
            x2 = cx - (r - 4) * math.cos(a)
            y2 = y  - (r - 4) * math.sin(a)
            self.canvas.create_line(x1, y1, x2, y2,
                                    fill=GREEN_LT, width=2, tags="roll")
            # punto central
            self.canvas.create_oval(cx - 3, y - 3, cx + 3, y + 3,
                                    fill=GREEN_LT, outline="", tags="roll")

        self._anim_x    += 2.5
        self._anim_angle = (self._anim_angle + 8) % 360
        self._anim_id    = self.root.after(30, self._tick_anim)

    # ── Estado ocupado / libre ───────────────────────────────────────────────

    def _set_busy(self, busy: bool):
        self._running = busy
        state = "disabled" if busy else "normal"
        self.btn_inv.config(state=state,
                            cursor="arrow" if busy else "hand2")
        self.btn_reg.config(state=state,
                            cursor="arrow" if busy else "hand2")
        if busy:
            self._anim_x = -90
            self._tick_anim()
        else:
            if self._anim_id:
                self.root.after_cancel(self._anim_id)
                self._anim_id = None
            self.canvas.delete("roll")

    def _show_status(self, msg: str, kind: str = "ok"):
        paleta = {
            "ok":   (OK_FG,   BG),
            "warn": (WARN_FG, BG),
            "err":  (ERR_FG,  BG),
            "info": (MUTED,   BG),
        }
        fg, bg = paleta.get(kind, (WHITE, BG))
        self.lbl_status.config(text=msg, fg=fg, bg=bg)

    # ── Acciones de botones ──────────────────────────────────────────────────

    def _on_descargar(self):
        self._set_busy(True)
        self._show_status("Descargando inventario desde SAP...", "info")
        self.lbl_footer.config(text="Por favor espera...")
        threading.Thread(target=self._run_descargar, daemon=True).start()

    def _run_descargar(self):
        try:
            logging.info("Iniciando descarga de inventario desde /SCWM/MON")
            carpeta = os.path.join(_BASE_DIR, "inventario_descargado")
            os.makedirs(carpeta, exist_ok=True)

            ruta_txt = inv_mod.descargar_inventario(carpeta, "inventario_sap.txt")
            logging.info(f"Inventario descargado en: {ruta_txt}")

            logging.info("Parseando y publicando en GitHub...")
            resultado = txt_parser.publicar_inventario(ruta_txt)
            logging.info(
                f"Publicado: {resultado['count']} rollos, {resultado['size_kb']} KB"
            )
            self._queue.put(("ok",
                f"✓ Inventario actualizado.\n"
                f"{resultado['count']:,} rollos publicados en GitHub."))
        except Exception as e:
            logging.exception("Error al descargar/publicar inventario")
            self._queue.put(("err", "Ocurrio un error. Avisa al encargado."))

    def _on_registrar(self):
        if self._pendientes == 0:
            return
        self._set_busy(True)
        self._show_status("Moviendo rollos...", "info")
        self.lbl_footer.config(text="Por favor espera...")
        threading.Thread(target=self._run_registrar, daemon=True).start()

    def _run_registrar(self):
        try:
            logging.info("Iniciando registro de movimientos P331")
            resultado = runner_p331.run_all(
                log_callback=lambda m: logging.info(m)
            )
            p = resultado["procesados"]
            d = resultado["con_discrepancias"]
            e = resultado["errores"]
            if e > 0:
                self._queue.put(("err", "Ocurrio un error. Avisa al encargado."))
            elif d > 0:
                self._queue.put(("warn",
                    f"✓ {p} registrado(s).  {d} con diferencias — revisar SAP."))
            else:
                self._queue.put(("ok",
                    f"✓ {p} movimiento(s) registrado(s) correctamente."))
        except Exception as e:
            logging.exception("Error al registrar movimientos")
            self._queue.put(("err", "Ocurrio un error. Avisa al encargado."))

    # ── Conteo de pendientes (se actualiza al abrir y despues de cada tarea) ─

    def _refresh_pendientes(self):
        threading.Thread(target=self._fetch_count, daemon=True).start()

    def _fetch_count(self):
        try:
            archivos = gh.listar_pendientes()
            self._queue.put(("count", len(archivos)))
            logging.info(f"Pendientes en GitHub: {len(archivos)}")
        except Exception as e:
            logging.warning(f"No se pudo consultar GitHub: {e}")
            self._queue.put(("count", -1))

    def _apply_count(self, count: int):
        self._pendientes = count
        if count < 0:
            # Sin conexion a GitHub
            self.btn_reg.config(
                text="▶   Registrar movimientos",
                bg=DIS_BG, fg=DIS_FG, state="disabled", cursor="arrow",
            )
            self.lbl_footer.config(text="Sin conexion a GitHub")
        elif count == 0:
            self.btn_reg.config(
                text="▶   Registrar movimientos  (0)",
                bg=DIS_BG, fg=DIS_FG, state="disabled", cursor="arrow",
            )
            self.lbl_footer.config(text="SAP activo · Sin movimientos pendientes")
        else:
            self.btn_reg.config(
                text=f"▶   Registrar movimientos  ({count})",
                bg=BLUE, fg=WHITE, state="normal", cursor="hand2",
            )
            self.lbl_footer.config(
                text=f"SAP activo · {count} movimiento(s) pendiente(s) en GitHub"
            )

    # ── Cola thread-safe ─────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                kind, data = self._queue.get_nowait()
                if kind == "count":
                    self._apply_count(data)
                else:
                    self._set_busy(False)
                    self._show_status(data, kind)
                    # Actualizar conteo 1 segundo despues de terminar
                    self.root.after(1000, self._refresh_pendientes)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


# ── Arranque ─────────────────────────────────────────────────────────────────

def main():
    if _import_error:
        import tkinter.messagebox as mb
        root = tk.Tk()
        root.withdraw()
        mb.showerror(
            "Error de inicio",
            f"No se pudo cargar el bot:\n\n{_import_error}\n\n"
            "Revisa que esten instaladas las dependencias (requirements.txt).",
        )
        sys.exit(1)

    root = tk.Tk()
    WMSApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
