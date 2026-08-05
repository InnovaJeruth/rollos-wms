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
from tkinter import font as tkfont

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
ORANGE   = "#c85a00"
ORANGE_H = "#a04800"


# ── Dialogo de conflictos ────────────────────────────────────────────────────

class ConflictDialog(tk.Toplevel):
    """
    Modal que muestra lotes con destinos conflictivos y pide al admin
    elegir el destino correcto para cada uno.
    Cierra con self.result = list de entries resueltas, o None si cancelo.
    """

    def __init__(self, parent, conflictos):
        super().__init__(parent)
        self.title("Conflictos de destino — Almacen TEXCORP")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()          # modal
        self.result = None

        self._vars = []          # una tk.StringVar por conflicto

        # Titulo
        tk.Label(self, text="⚠  Conflictos de destino",
                 font=("Segoe UI", 14, "bold"), bg=BG, fg=WARN_FG
                 ).pack(padx=24, pady=(20, 4))
        tk.Label(self,
                 text="El mismo lote fue escaneado con destinos distintos.\n"
                      "Elige el destino correcto para cada uno:",
                 font=("Segoe UI", 10), bg=BG, fg=WHITE, justify="left"
                 ).pack(padx=24, pady=(0, 12))

        # Frame con scroll si hay muchos
        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", expand=True, padx=24)

        canvas = tk.Canvas(container, bg=BG, highlightthickness=0,
                           width=420, height=min(320, len(conflictos) * 110 + 20))
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=BG)
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_resize(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_win, width=canvas.winfo_width())
        inner.bind("<Configure>", _on_resize)

        for i, conf in enumerate(conflictos):
            lote       = conf["lote"]
            desc       = conf["descripcion"]
            opciones   = conf["opciones"]

            # Separador entre items
            if i > 0:
                tk.Frame(inner, height=1, bg=SEP).pack(fill="x", pady=6)

            tk.Label(inner,
                     text=f"Lote: {lote}",
                     font=("Segoe UI", 11, "bold"), bg=BG, fg=WHITE, anchor="w"
                     ).pack(fill="x")
            if desc:
                tk.Label(inner,
                         text=desc,
                         font=("Segoe UI", 9), bg=BG, fg=MUTED, anchor="w"
                         ).pack(fill="x")

            var = tk.StringVar(value=opciones[0]["bin_destino"])
            self._vars.append((var, conf))

            for opt in opciones:
                dest  = opt["bin_destino"]
                op    = opt["operario"]
                ts    = (opt["timestamp"] or "")[:16].replace("T", " ")
                label = f"  {dest}   (por {op}{('  ' + ts) if ts else ''})"
                tk.Radiobutton(inner, text=label, variable=var, value=dest,
                               font=("Segoe UI", 10), bg=BG, fg=BLUE_LT,
                               activebackground=BG, selectcolor=BG2,
                               anchor="w"
                               ).pack(fill="x")

        # Botones
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(fill="x", padx=24, pady=16)

        tk.Button(btn_frame, text="Cancelar",
                  font=("Segoe UI", 11), bg=BG2, fg=MUTED,
                  activebackground=SEP, activeforeground=WHITE,
                  relief="flat", bd=0, pady=8, cursor="hand2",
                  command=self._cancel
                  ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        tk.Button(btn_frame, text="Ejecutar con estas opciones",
                  font=("Segoe UI", 11, "bold"), bg=ORANGE, fg=WHITE,
                  activebackground=ORANGE_H, activeforeground=WHITE,
                  relief="flat", bd=0, pady=8, cursor="hand2",
                  command=self._confirm
                  ).pack(side="left", fill="x", expand=True)

        self.update_idletasks()
        # Centrar sobre la ventana padre
        pw = parent.winfo_rootx() + parent.winfo_width() // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        w  = self.winfo_reqwidth()
        h  = self.winfo_reqheight()
        self.geometry(f"+{pw - w // 2}+{ph - h // 2}")

    def _cancel(self):
        self.result = None
        self.destroy()

    def _confirm(self):
        """
        Para cada conflicto, devuelve la entrada cuyo bin_destino coincide
        con la seleccion del admin.
        """
        resueltos = []
        for var, conf in self._vars:
            elegido = var.get()
            entry   = next((o for o in conf["opciones"] if o["bin_destino"] == elegido),
                           conf["opciones"][0])
            resueltos.append(entry)
        self.result = resueltos
        self.destroy()


class WMSApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Almacen TEXCORP — Bot SAP")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry("360x500")

        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._anim_angle = 0.0
        self._anim_x = -90.0
        self._anim_id = None
        self._pendientes = 0
        self._solo_hoy = tk.BooleanVar(value=False)

        # Datos de la ultima consolidacion (unicos, conflictos, por_archivo, datos_por_archivo)
        self._pending_data = None

        self._build_ui()
        self._refresh_pendientes()
        self._poll_queue()

    # ── Construccion de UI ───────────────────────────────────────────────────

    def _build_ui(self):
        # Encabezado
        tk.Label(self.root, text="Almacen TEXCORP",
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

        # Filtro + boton actualizar en la misma fila
        row_frame = tk.Frame(self.root, bg=BG)
        row_frame.pack(fill="x", padx=28, pady=(8, 0))
        self.chk_hoy = tk.Checkbutton(
            row_frame,
            text="Solo movimientos de hoy",
            variable=self._solo_hoy,
            font=("Segoe UI", 10),
            bg=BG, fg=MUTED,
            activebackground=BG, activeforeground=WHITE,
            selectcolor=BG2,
            cursor="hand2",
            command=self._on_refresh,
        )
        self.chk_hoy.pack(side="left")
        self.btn_refresh = tk.Button(
            row_frame,
            text="↻",
            font=("Segoe UI", 11),
            bg=BG2, fg=MUTED, activebackground=SEP, activeforeground=WHITE,
            relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
            command=self._on_refresh,
        )
        self.btn_refresh.pack(side="right")

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
        self.btn_refresh.config(state=state,
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

    def _on_refresh(self):
        self.btn_refresh.config(text="↻  Verificando...", state="disabled", cursor="arrow")
        self.root.after(100, self._do_refresh)

    def _do_refresh(self):
        self._refresh_pendientes()

    def _on_registrar(self):
        if self._pendientes == 0:
            return

        # Si hay conflictos conocidos, mostrar dialogo antes de ejecutar
        if self._pending_data and self._pending_data[1]:
            unicos, conflictos, por_archivo, datos_por_archivo = self._pending_data
            dlg = ConflictDialog(self.root, conflictos)
            self.root.wait_window(dlg)
            if dlg.result is None:
                # Admin cancelo
                return
            # Combinar unicos + resolucion de conflictos
            unicos_resueltos = unicos + dlg.result
            self._set_busy(True)
            self._show_status("Moviendo rollos...", "info")
            self.lbl_footer.config(text="Por favor espera...")
            threading.Thread(
                target=self._run_registrar_explicit,
                args=(unicos_resueltos, por_archivo, datos_por_archivo),
                daemon=True,
            ).start()
        else:
            self._set_busy(True)
            self._show_status("Moviendo rollos...", "info")
            self.lbl_footer.config(text="Por favor espera...")
            unicos      = self._pending_data[0] if self._pending_data else None
            por_arch    = self._pending_data[2] if self._pending_data else None
            datos_por_a = self._pending_data[3] if self._pending_data else None
            threading.Thread(
                target=self._run_registrar_explicit,
                args=(unicos, por_arch, datos_por_a),
                daemon=True,
            ).start()

    def _run_registrar_explicit(self, unicos, por_archivo, datos_por_archivo=None):
        try:
            logging.info("Iniciando registro de movimientos P331 (lista explicita)")
            if unicos is None or por_archivo is None:
                # Fallback: descarga y consolida en el momento
                resultado = runner_p331.run_all(log_callback=lambda m: logging.info(m))
            else:
                resultado = runner_p331.run_explicit(
                    unicos, por_archivo, datos_por_archivo,
                    log_callback=lambda m: logging.info(m),
                )
            d = resultado["con_discrepancias"]
            e = resultado["errores"]
            r = resultado.get("total_llenados", resultado["procesados"])
            if e > 0:
                self._queue.put(("err", "Ocurrio un error. Avisa al encargado."))
            elif d > 0:
                self._queue.put(("warn",
                    f"✓ {r} rollo(s) registrado(s).  {d} archivo(s) con diferencias — revisar SAP."))
            else:
                self._queue.put(("ok",
                    f"✓ {r} rollo(s) registrado(s) correctamente."))
        except Exception as e:
            logging.exception("Error al registrar movimientos")
            self._queue.put(("err", "Ocurrio un error. Avisa al encargado."))

    # ── Conteo de pendientes (se actualiza al abrir y despues de cada tarea) ─

    def _refresh_pendientes(self):
        self._pending_data = None
        threading.Thread(target=self._fetch_count, daemon=True).start()

    def _fetch_count(self):
        try:
            desde = datetime.date.today().isoformat() if self._solo_hoy.get() else None
            archivos = gh.listar_pendientes()
            if not archivos:
                self._queue.put(("count_data", (0, 0, None)))
                return

            unicos, conflictos, por_archivo, datos_por_archivo = runner_p331.consolidar_movimientos(archivos, desde=desde)
            total = len(unicos) + len(conflictos)  # conflictos cuentan como 1 rollo c/u
            logging.info(
                f"Pendientes: {len(unicos)} unicos, {len(conflictos)} conflictos "
                f"en {len(archivos)} archivo(s){' (filtro: desde ' + desde + ')' if desde else ''}"
            )
            self._queue.put(("count_data", (total, len(conflictos), (unicos, conflictos, por_archivo, datos_por_archivo))))
        except Exception as e:
            logging.warning(f"No se pudo consultar GitHub: {e}")
            self._queue.put(("count_data", (-1, 0, None)))

    def _apply_count(self, total: int, n_conflicts: int, pending_data):
        self._pending_data  = pending_data
        self._pendientes    = total
        self.btn_refresh.config(text="↻  Actualizar", state="normal", cursor="hand2")

        if total < 0:
            self.btn_reg.config(
                text="▶   Registrar movimientos",
                bg=DIS_BG, fg=DIS_FG, state="disabled", cursor="arrow",
            )
            self.lbl_footer.config(text="Sin conexion a GitHub")

        elif total == 0:
            self.btn_reg.config(
                text="▶   Registrar movimientos  (0 rollos)",
                bg=DIS_BG, fg=DIS_FG, state="disabled", cursor="arrow",
            )
            self.lbl_footer.config(text="SAP activo · Sin rollos ejecutables P331")

        elif n_conflicts > 0:
            label = (
                f"▶   Registrar movimientos  ({total} rollo{'s' if total != 1 else ''}  "
                f"· ⚠ {n_conflicts} conflicto{'s' if n_conflicts != 1 else ''})"
            )
            self.btn_reg.config(
                text=label,
                bg=ORANGE, fg=WHITE,
                activebackground=ORANGE_H, activeforeground=WHITE,
                state="normal", cursor="hand2",
            )
            self.lbl_footer.config(
                text=f"SAP activo · {total} rollo(s) · {n_conflicts} conflicto(s) de destino"
            )

        else:
            self.btn_reg.config(
                text=f"▶   Registrar movimientos  ({total} rollo{'s' if total != 1 else ''})",
                bg=BLUE, fg=WHITE,
                activebackground=BLUE_H, activeforeground=WHITE,
                state="normal", cursor="hand2",
            )
            self.lbl_footer.config(
                text=f"SAP activo · {total} rollo{'s' if total != 1 else ''} ejecutable{'s' if total != 1 else ''} P331 en GitHub"
            )

    # ── Cola thread-safe ─────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]

                if kind == "count_data":
                    _, (total, n_conf, pdata) = msg
                    self._apply_count(total, n_conf, pdata)

                elif kind == "count":
                    # Compatibilidad con mensajes count simples (sin conflictos)
                    self._apply_count(msg[1], 0, None)

                else:
                    status_kind, data = kind, msg[1]
                    self._set_busy(False)
                    self._show_status(data, status_kind)
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
