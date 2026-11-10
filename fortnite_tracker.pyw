#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Chest Tracker  (con interfaz grafica)
==============================================
Programa que corre en segundo plano y cuenta cuantas veces abres un cofre
en Fortnite, detectando la pulsacion mantenida de la tecla "E".

Muestra una ventana moderna (CustomTkinter) con:
  - Total de cofres abiertos
  - Probabilidad del token por cofre (ajustable, por defecto 0.1%)
  - Probabilidad acumulada de exito  P = 1 - (1-p)^n   (metodo del complemento)
  - Icono dibujado del cofre (estilo Fortnite) junto a las probabilidades
  - Barra de progreso y cofres necesarios para llegar al ~50% / ~90%

Cada apertura se guarda ademas en un archivo de texto (cofres.log).

Requisitos:  pip install pynput customtkinter Pillow
Uso:         doble click sobre fortnite_tracker.pyw (Windows)
             o `python fortnite_tracker.pyw` desde terminal.

Opciones:
  --hold MS      ms minimos que hay que mantener E para contar (def. 250)
  --prob X       probabilidad del token por cofre, 0..1 (def. 0.001 = 0.1%)
  --minimized    arranca oculto (solo bandeja, si usas --tray)
  --tray         muestra icono extra en el area de notificacion
"""

import argparse
import json
import math
import os
import sys
import threading
import time
import tkinter.messagebox as messagebox
from datetime import datetime

try:
    from pynput import keyboard
except ImportError:
    print("Falta la libreria pynput. Instala con:  pip install pynput")
    sys.exit(1)

# ----------------------------- Configuracion ------------------------------ #
DEFAULT_HOLD_MS = 250        # Umbral de mantencion de E (ver README)
COOLDOWN_S = 1.0             # Evita dobles conteos de una misma interaccion
KEY_TO_WATCH = "e"           # Tecla usada para abrir cofres
DEFAULT_TOKEN_PROB = 1 / 137500   # ~0.000727 % de que salga el token en UN cofre
DATA_DIR = os.path.join(os.path.expanduser("~"), "FortniteChestTracker")
LOG_FILE = os.path.join(DATA_DIR, "cofres.log")      # archivo de texto legible
STATE_FILE = os.path.join(DATA_DIR, "estado.json")   # contador persistente
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")  # preferencias de la UI
# --------------------------------------------------------------------------- #

os.makedirs(DATA_DIR, exist_ok=True)


# ============================ Logica del tracker =========================== #
class ChestTracker:
    """Detecta aperturas (E mantenida >= hold_ms) y persiste el contador."""

    def __init__(self, hold_ms: float = DEFAULT_HOLD_MS):
        self.lock = threading.Lock()
        self.count = 0
        self.hold_ms = hold_ms
        self.press_start = None
        self.last_count_time = 0.0
        self.token_prob = DEFAULT_TOKEN_PROB
        self.on_chest = None          # callback(new_count) al registrar un cofre
        self._load_state()

    # ---------------- estado / persistencia ---------------- #
    def _load_state(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.count = int(data.get("total", 0))
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            self.count = 0

    def _save_state(self):
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"total": self.count,
                       "ultima_actualizacion": datetime.now().isoformat(timespec="seconds")},
                      f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)

    def _append_log(self, hold_ms):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] Cofre #{self.count}  (E mantenida {hold_ms} ms)\n")

    # ---------------- eventos de teclado ---------------- #
    def on_press(self, key):
        if self._key_name(key) != KEY_TO_WATCH:
            return
        with self.lock:
            if self.press_start is None:  # ignora autorepeat mientras se mantiene
                self.press_start = time.monotonic()

    def on_release(self, key):
        if self._key_name(key) != KEY_TO_WATCH:
            return
        with self.lock:
            if self.press_start is None:
                return
            hold_s = time.monotonic() - self.press_start
            self.press_start = None

            hold_ms = hold_s * 1000.0
            now = time.monotonic()
            counted = False
            if hold_ms >= self.hold_ms and (now - self.last_count_time) >= COOLDOWN_S:
                self.count += 1
                self.last_count_time = now
                self._save_state()
                self._append_log(int(hold_ms))
                counted = True
            new_count = self.count
            cb = self.on_chest

        if counted:
            print(f"Cofre #{new_count} registrado (mantuviste E {int(hold_ms)} ms)")
            if cb:
                try:
                    cb(new_count)
                except Exception:
                    pass

    @staticmethod
    def _key_name(key):
        try:
            return key.char.lower()
        except AttributeError:
            return (key.name or "").lower()

    def reset(self):
        with self.lock:
            self.count = 0
            self._save_state()
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{stamp}] --- contador reiniciado desde la UI ---\n")


# =============================== Matematica ================================ #
def cumulative_success(n: int, p: float) -> float:
    """Probabilidad de AL MENOS un exito tras n intentos (metodo del
       complemento):  P(exito) = 1 - P(ningun exito) = 1 - (1 - p)^n"""
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return 1.0 - math.pow(1.0 - p, n)


def chests_for_target(p: float, target: float) -> int:
    """Invierte el complemento: n = ceil( ln(1-target) / ln(1-p) ) cofres
       necesarios para alcanzar 'target' de probabilidad acumulada."""
    if p <= 0 or p >= 1 or not (0 < target < 1):
        return 0
    return max(0, math.ceil(math.log(1.0 - target) / math.log(1.0 - p)))


def make_chest_ctk_image(size: int):
    import customtkinter as ctk
    from PIL import Image
    import os
    
    # Obtenemos la ruta del script actual
    script_dir = os.path.dirname(os.path.abspath(__file__))
    img_path = os.path.join(script_dir, "pirate-shop-token.png")
    
    try:
        img = Image.open(img_path).resize((size, size), Image.Resampling.LANCZOS)
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception as e:
        return None

def save_chest_png(path: str, size: int = 64):
    from PIL import Image
    import os
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    img_path = os.path.join(script_dir, "pirate-shop-token.png")
    
    try:
        img = Image.open(img_path).resize((size, size), Image.Resampling.LANCZOS)
        img.save(path)
        return path
    except Exception as e:
        return None


# ============================ Interfaz grafica ============================= #
BG = "#1b1f2e"          # fondo oscuro azulado (estilo Fortnite)
CARD = "#262b40"
ACCENT = "#ffb43c"      # dorado
BLUE = "#3d6fd6"
GREEN = "#7ee081"
TEXT_DIM = "#9aa3c0"


class App:
    def __init__(self, tracker: ChestTracker, start_minimized: bool = False):
        self.tracker = tracker

        try:
            import customtkinter as ctk
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
            self.ctk = ctk
            self.root = ctk.CTk()
            self._use_ctk = True
        except Exception:
            import tkinter as tk
            self.ctk = None
            self.root = tk.Tk()
            self.root.configure(bg=BG)
            self._use_ctk = False

        self.root.title("Fortnite Chest Tracker")
        self.root.geometry("600x540")
        self.root.minsize(520, 480)

        # Icono de la ventana (usamos .ico para compatibilidad nativa con Windows)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, "icono_app.ico")
        
        try:
            if os.path.exists(icon_path):
                # iconbitmap es el método nativo de Tkinter para archivos .ico en Windows
                self.root.iconbitmap(default=icon_path)
                self._win_icon = icon_path 
            else:
                print(f"AVISO: No se encontró {icon_path}, se usará el icono por defecto.")
        except Exception as e:
            print(f"No se pudo cargar el icono: {e}")

        # Imagen grande del cofre para la tarjeta de probabilidades
        self.chest_img = None
        if self._use_ctk:
            try:
                self.chest_img = make_chest_ctk_image(110)
            except Exception:
                self.chest_img = None

        self.var_count = self._stringvar("0")
        self.var_single = self._stringvar("-")
        self.var_cum = self._stringvar("-")
        self.var_n50 = self._stringvar("-")
        self.var_n90 = self._stringvar("-")
        self.var_status = self._stringvar("Esperando aperturas... mantén E para abrir cofres")
        self.prob_entry_val = self._stringvar(
            f"{tracker.token_prob * 100:.6f}")  # Muestra 6 decimales: 0.000727

        self._build_ui()
        self._refresh()

        # El listener de pynput corre en su propio hilo; el callback redirige
        # al hilo de la UI mediante root.after (thread-safe).
        self.tracker.on_chest = lambda n: self.root.after(0, self._on_new_chest)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if start_minimized:
            self.root.withdraw()

    # ---------- helpers ---------- #
    def _stringvar(self, initial):
        if self._use_ctk:
            return self.ctk.StringVar(master=self.root, value=initial)
        import tkinter as tk
        return tk.StringVar(master=self.root, value=initial)

    def _row(self, parent, bg="transparent"):
        if self._use_ctk:
            return self.ctk.CTkFrame(parent, fg_color=bg)
        import tkinter as tk
        return tk.Frame(parent, bg=CARD if bg == "transparent" else bg)

    def _label(self, parent, textvariable=None, text=None, size=14,
               color="#ffffff", bold=False, anchor="w"):
        if self._use_ctk:
            return self.ctk.CTkLabel(
                parent, textvariable=textvariable, text=text,
                font=self.ctk.CTkFont(size=size,
                                      weight="bold" if bold else "normal"),
                text_color=color, anchor=anchor)
        import tkinter as tk
        return tk.Label(parent, textvariable=textvariable, text=text,
                        bg=parent.cget("bg") if parent.cget("bg") != BG else BG,
                        fg=color,
                        font=("Segoe UI", size, "bold" if bold else "normal"),
                        anchor=anchor)

    def _card(self, parent):
        if self._use_ctk:
            return self.ctk.CTkFrame(parent, corner_radius=14, fg_color=CARD)
        import tkinter as tk
        return tk.Frame(parent, bg=CARD, padx=6, pady=6)

    def _button(self, parent, text, cmd, color=ACCENT, width=150):
        if self._use_ctk:
            return self.ctk.CTkButton(parent, text=text, command=cmd,
                                      fg_color=color, corner_radius=8,
                                      width=width)
        import tkinter as tk
        return tk.Button(parent, text=text, command=cmd, bg=color, fg="#101018",
                         relief="flat", padx=8, pady=4, width=width // 8)

    def _entry(self, parent, var, width_chars=8):
        if self._use_ctk:
            return self.ctk.CTkEntry(parent, textvariable=var,
                                     width=width_chars * 10)
        import tkinter as tk
        return tk.Entry(parent, textvariable=var, width=width_chars,
                        bg="#11141f", fg="white", insertbackground="white",
                        relief="flat")

    def _progress_bar(self, parent):
        if self._use_ctk:
            return self.ctk.CTkProgressBar(parent, height=12,
                                           progress_color=ACCENT)
        import tkinter as tk
        pb = tk.Canvas(parent, height=12, bg="#11141f", highlightthickness=0)
        pb.fill_ratio = 0.0

        def draw(*_):
            pb.delete("all")
            w = pb.winfo_width()
            pb.create_rectangle(0, 0, max(1, w * pb.fill_ratio), 12,
                                fill=ACCENT, width=0)

        pb.bind("<Configure>", draw)

        def setv(v):
            pb.fill_ratio = v
            draw()

        pb.set = setv
        return pb

    # ---------- construccion de la UI ---------- #
    def _build_ui(self):
        outer = self._card(self.root) if not self._use_ctk else \
            self.ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        outer.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- cabecera ---- #
        header = self._card(outer)
        header.pack(fill="x", padx=10, pady=(10, 6))
        hrow = self._row(header)
        hrow.pack(fill="x")
        title_row = self._row(header)
        title_row.pack(fill="x", padx=12, pady=8)
        if self.chest_img is not None:
            small_icon = self.ctk.CTkLabel(title_row,
                                           image=self.chest_img, text="")
            small_icon.configure(image=make_chest_ctk_image(34))
            self._small_icon_ref = small_icon
            small_icon.pack(side="left", padx=(0, 8))
        self._label(title_row, text="CHEST TRACKER", size=20, color=ACCENT,
                    bold=True).pack(side="left")
        self._label(title_row, textvariable=self.var_status, size=11,
                    color=TEXT_DIM).pack(side="right", padx=4)

         # ---- AVISO DE ADVERTENCIA ---- #
        warning_card = self._card(outer)
        warning_card.pack(fill="x", padx=10, pady=(0, 6))
        
        warning_row = self._row(warning_card)
        warning_row.pack(fill="x", padx=12, pady=10)
        
        # Texto principal grande en rojo
        self._label(warning_row, text="⚠️  NO OLVIDAR CERRAR JUNTO A FORTNITE  ⚠️", 
                    size=18, color="#ff3333", bold=True, anchor="center").pack(pady=(0, 4))
        
        # Texto secundario más pequeño
        self._label(warning_row, text="El programa sigue contando incluso sin Fortnite abierto", 
                    size=11, color="#ff6666", anchor="center").pack()

        # ---- panel principal: contador + probabilidades ---- #
        main = self._card(outer)
        main.pack(fill="both", expand=True, padx=10, pady=6)

        grid = self._row(main)
        grid.pack(fill="both", expand=True, padx=6, pady=6)

        # Columna izquierda: contador grande + barra de progreso
        left = self._row(grid)
        left.pack(side="left", expand=True, fill="both", padx=10, pady=10)
        self._label(left, text="COFRES ABIERTOS", size=13, color=TEXT_DIM,
                    bold=True).pack(anchor="w", pady=(0, 2))
        self._label(left, textvariable=self.var_count, size=56,
                    color="#ffffff", bold=True).pack(anchor="w")
        self.progress = self._progress_bar(left)
        self.progress.pack(fill="x", pady=(14, 2))
        self._label(left, text="Progreso hacia el ~90 % de probabilidad",
                    size=11, color=TEXT_DIM).pack(anchor="w")

        # Columna derecha: cofre + probabilidades
        right = self._row(grid)
        right.pack(side="left", expand=True, fill="both", padx=10, pady=10)

        prob_row = self._row(right)
        prob_row.pack(anchor="w", pady=(0, 4))
        if self.chest_img is not None:
            big_chest = self.ctk.CTkLabel(prob_row, image=self.chest_img, text="")
            big_chest.pack(side="left", padx=(0, 12))
        stats_col = self._row(prob_row)
        stats_col.pack(side="left")
        self._label(stats_col, text="Prob. del token (por cofre)", size=12,
                    color=TEXT_DIM).pack(anchor="w")
        self._label(stats_col, textvariable=self.var_single, size=18,
                    color=ACCENT, bold=True).pack(anchor="w")
        self._label(stats_col, text="Prob. acumulada (complemento)", size=12,
                    color=TEXT_DIM).pack(anchor="w", pady=(8, 0))
        self._label(stats_col, textvariable=self.var_cum, size=18,
                    color=GREEN, bold=True).pack(anchor="w")

        # Mini-tarjetas 50 % / 90 %
        refs = self._row(right)
        refs.pack(anchor="w", pady=(6, 0))
        box50 = self._mini_card(refs, "Cofres para ~50 %", self.var_n50)
        box50.pack(side="left", padx=(0, 8))
        box90 = self._mini_card(refs, "Cofres para ~90 %", self.var_n90)
        box90.pack(side="left")

        # ---- fila de control ---- #
        ctrl = self._card(outer)
        ctrl.pack(fill="x", padx=10, pady=6)
        crow = self._row(ctrl)
        crow.pack(fill="x", padx=12, pady=10)
        self._label(crow, text="Prob. token (%):", size=13).pack(side="left")
        self.prob_entry = self._entry(crow, self.prob_entry_val, 8)
        self.prob_entry.pack(side="left", padx=6)
        self._button(crow, "Aplicar", self._apply_prob, color=GREEN,
                     width=90).pack(side="left", padx=4)
        self._button(crow, "Salir", self._on_close, color="#b3384a",
                     width=90).pack(side="right", padx=4)
        self._button(crow, "Reiniciar", self._reset, color=BLUE,
                     width=110).pack(side="right", padx=4)

        # ---- pie ---- #
        foot = self._row(outer)
        foot.pack(fill="x")
        self._label(foot, text=f"Registro en: {LOG_FILE}", size=11,
                    color=TEXT_DIM).pack(anchor="w", padx=14, pady=(2, 8))

    def _mini_card(self, parent, title, var):
        card = self._row(parent, bg="#2f3654")
        if self._use_ctk:
            card.configure(corner_radius=10)
        self._label(card, text=title, size=11, color=TEXT_DIM).pack(
            anchor="w", padx=10, pady=(6, 0))
        self._label(card, textvariable=var, size=16, color="#ffffff",
                    bold=True).pack(anchor="w", padx=10, pady=(0, 6))
        return card

    def _fmt_pct(self, x):
        """Formatea probabilidades mostrando suficientes decimales según el tamaño."""
        pct = x * 100
        if pct < 0.001:
            return f"{pct:.6f} %"  # Para valores muy pequeños como 0.000727
        elif pct < 0.01:
            return f"{pct:.4f} %"
        elif pct < 0.1:
            return f"{pct:.3f} %"
        else:
            return f"{pct:.2f} %"

    def _refresh(self):
        n = self.tracker.count
        p = self.tracker.token_prob
        cum = cumulative_success(n, p)
        n90 = chests_for_target(p, 0.90)
        self.var_count.set(str(n))
        self.var_single.set(self._fmt_pct(p))
        self.var_cum.set(self._fmt_pct(cum))
        self.var_n50.set(f"{chests_for_target(p, 0.50):,}".replace(",", "."))
        self.var_n90.set(f"{n90:,}".replace(",", "."))
        try:
            self.progress.set(min(1.0, cum / 0.90))  # barra relativa al 90 %
        except Exception:
            pass

    def _on_new_chest(self):
        self._refresh()
        self.var_status.set(f"¡Cofre abierto! Total: {self.tracker.count}")

    # ---------- acciones ---------- #
    def _apply_prob(self):
        try:
            pct = float(self.prob_entry_val.get().replace(",", "."))
            if not (0 < pct <= 100):
                raise ValueError
            self.tracker.token_prob = pct / 100.0
            cfg = {}
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
            cfg["token_prob"] = self.tracker.token_prob
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.var_status.set(f"Probabilidad aplicada: {pct:g} % por cofre")
        except Exception:
            self.var_status.set("Valor inválido: usa un número entre 0 y 100.")
        self._refresh()

    def _reset(self):
        """Reinicia el contador previa confirmación del usuario."""
        import tkinter.messagebox as messagebox
        
        confirmar = messagebox.askyesno(
            title="⚠️ Confirmar reinicio",
            message="¿Estás SEGURO de que quieres reiniciar el contador a 0?\n\n"
                    "Esta acción borrará todo tu progreso acumulado y NO se puede deshacer."
        )
        
        if confirmar:
            self.tracker.reset()
            self._refresh()
            self.var_status.set("Contador reiniciado manualmente.")
        else:
            self.var_status.set("Reinicio cancelado por el usuario.")

    def show(self):
        self.root.deiconify()

    def _on_close(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ================================= Tray ==================================== #
def run_tray(app_holder, stop_event):
    """Icono opcional en el area de notificacion (pystray). Se activa con --tray."""
    try:
        import pystray
        from PIL import Image
    except ImportError:
        return
    png = save_chest_png(os.path.join(DATA_DIR, "_chest_tray.png"), 64)
    img = Image.open(png)

    def restore(icon, item):
        app_holder["show"]()

    def quit_(icon, item):
        stop_event.set()
        app_holder["quit"]()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Abrir ventana", restore, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Salir", quit_),
    )
    icon = pystray.Icon("chest_tracker", img, "Fortnite Chest Tracker", menu)
    icon.run()


# ================================= Main ===================================== #
def load_saved_prob():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return float(json.load(f).get("token_prob", DEFAULT_TOKEN_PROB))
    except Exception:
        return DEFAULT_TOKEN_PROB


def parse_args():
    p = argparse.ArgumentParser(description="Fortnite Chest Tracker")
    p.add_argument("--hold", type=float, default=DEFAULT_HOLD_MS, metavar="MS",
                   help=f"ms minimos de E para contar (def. {DEFAULT_HOLD_MS:g})")
    p.add_argument("--prob", type=float, default=None, metavar="P",
                   help="probabilidad del token por cofre, 0..1 (def. 0.001)")
    p.add_argument("--minimized", action="store_true",
                   help="arrancar oculto (usa junto con --tray)")
    p.add_argument("--tray", action="store_true",
                   help="mostrar tambien icono en la bandeja de Windows")
    return p.parse_args()


def main():
    args = parse_args()
    tracker = ChestTracker(hold_ms=max(0.0, args.hold))
    tracker.token_prob = args.prob if args.prob is not None \
        else load_saved_prob()

    listener = keyboard.Listener(on_press=tracker.on_press,
                                 on_release=tracker.on_release)
    listener.daemon = True
    listener.start()

    app = App(tracker, start_minimized=args.minimized)

    if args.tray:
        stop_event = threading.Event()
        holder = {"show": app.show, "quit": app._on_close}
        tray_thread = threading.Thread(target=run_tray,
                                       args=(holder, stop_event), daemon=True)
        tray_thread.start()

    app.run()
    listener.stop()

if __name__ == "__main__":
    main()
