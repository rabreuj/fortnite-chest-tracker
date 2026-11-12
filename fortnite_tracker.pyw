#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fortnite Chest Tracker v1.1
===========================
Contador de cofres abiertos en Fortnite con probabilidad acumulada para el
token del Pirate Shop. Windows + CustomTkinter.

FUNCIONES
  - Contador persistente de cofres, editable a mano desde la UI.
  - Probabilidad base configurable + Restaurar (valor real) + Deshacer.
  - Multiplicador de evento (x1 por defecto; presets x1 / x1.5 / x2).
  - Probabilidad acumulada EXACTA con historico por multiplicador.
  - Barra de camino recorrido y cofres restantes para ~50 % y ~90 %.
  - Registro legible (cofres.log) y diagnostico (debug.log).

DOS MAGNITUDES DISTINTAS (no confundir)
  Probabilidad acumulada : depende SOLO de los cofres ya abiertos.
                           No cambia al tocar el multiplicador.
  Camino recorrido       : abiertos / (abiertos + restantes).
                           SI cambia con el multiplicador, porque los
                           cofres que faltan cambian. Es lo que mide la barra.

MULTIPLICADOR: NO ES RETROACTIVO
  Se aplica a los cofres abiertos a partir de activarlo. El historico se guarda
  por multiplicador ("buckets") y la probabilidad se calcula como:

      P(al menos 1 token) = 1 - PROD_i (1 - m_i * p)^(n_i)

  Ejemplo: 500 cofres x1 + 100 cofres x2
      P = 1 - (1-p)^500 * (1-2p)^100      <-- correcto
      P = 1 - (1-2p)^600                  <-- INCORRECTO (retroactivo)

  Calculo en log-espacio con log1p/expm1 para precision con p diminutas.

AJUSTE MANUAL DEL TOTAL
  Escribir un total aplica la diferencia al bucket x1 (tasa base), donde
  pertenecen los cofres abiertos antes de usar la app. Al reducir se descuenta
  de x1 primero; solo toca buckets de evento si x1 se agota.

ROBUSTEZ
  [FIX 1] _is_e() por Virtual Key, nunca lanza excepciones. El antiguo
          _key_name() provocaba AttributeError con KeyCode(char=None) y pynput
          mataba el listener en silencio: la GUI seguia visible sin contar.
  [FIX 2] El hook solo encola: sin lock, sin disco, sin print (~16 us frente al
          limite de ~300 ms de LowLevelHooksTimeout de Windows).
  [FIX 3] UI por polling; nada de root.after() desde el hilo del listener.
  [FIX 4] Logging con rotacion.
  [FIX 5] Watchdog: reinicia el listener si muere.
  [FIX 6] Resync con GetAsyncKeyState (keyups perdidos por alt-tab/UAC).
  [FIX 7] Mutex de instancia unica.
  [FIX 8] resource_path() + ICO multiresolucion autogenerado + AppUserModelID.
  [FIX 9] El multiplicador se captura EN EL HOOK y viaja con el evento.

Requisitos: pip install pynput customtkinter Pillow pystray
Uso:        doble click sobre fortnite_tracker.pyw
            o  python fortnite_tracker.pyw --debug
"""

import argparse
import ctypes
import json
import logging
import logging.handlers
import math
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime

try:
    from pynput import keyboard
except ImportError:
    keyboard = None

# ----------------------------- Configuracion ------------------------------ #
APP_ID          = "FortniteChestTracker.v1_1"
APP_VERSION     = "1.1"
DEFAULT_HOLD_MS = 250
COOLDOWN_S      = 1.0
HOLD_MAX_S      = 10.0
KEY_TO_WATCH    = "e"
VK_E            = 0x45
DEFAULT_TOKEN_PROB = 1 / 137500      # probabilidad REAL de referencia
DEFAULT_MULT    = 1.0
MULT_MIN        = 0.01
MULT_MAX        = 1000.0
MAX_CHESTS      = 10_000_000
PROB_HISTORY    = 12                 # niveles de "Deshacer"

IS_WINDOWS = (os.name == "nt")

DATA_DIR    = os.path.join(os.path.expanduser("~"), "FortniteChestTracker")
LOG_FILE    = os.path.join(DATA_DIR, "cofres.log")
STATE_FILE  = os.path.join(DATA_DIR, "estado.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
DEBUG_FILE  = os.path.join(DATA_DIR, "debug.log")

os.makedirs(DATA_DIR, exist_ok=True)

# ------------------------------- [FIX 4] Log ------------------------------- #
log = logging.getLogger("chesttracker")
log.setLevel(logging.INFO)
try:
    _h = logging.handlers.RotatingFileHandler(
        DEBUG_FILE, maxBytes=512_000, backupCount=2, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    log.addHandler(_h)
except Exception:
    log.addHandler(logging.NullHandler())


# --------------------------- [FIX 8] Rutas / icono ------------------------- #
def resource_path(rel: str) -> str:
    """Ruta valida tanto en script como en .exe de PyInstaller (--onefile)."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(base, rel)
    if os.path.exists(p):
        return p
    p2 = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), rel)
    return p2 if os.path.exists(p2) else p


def _find_asset(name: str):
    for cand in (resource_path(os.path.join("assets", name)), resource_path(name)):
        if os.path.exists(cand):
            return cand
    return None


def ensure_icon_file():
    """Devuelve un .ico utilizable; si solo hay PNG lo genera multiresolucion."""
    ico = _find_asset("icono_app.ico")
    if ico:
        return ico
    png = _find_asset("pirate-shop-token.png")
    if not png:
        return None
    cached = os.path.join(DATA_DIR, "icono_generado.ico")
    try:
        from PIL import Image
        if not os.path.exists(cached):
            Image.open(png).convert("RGBA").save(
                cached, format="ICO",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                       (64, 64), (128, 128), (256, 256)])
        return cached
    except Exception:
        log.exception("no se pudo generar el ICO")
        return None


def set_app_user_model_id():
    """Necesario para que la barra de tareas muestre el icono correcto."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        log.exception("AppUserModelID")


# ------------------------- [FIX 7] Instancia unica ------------------------- #
_mutex_handle = None


def acquire_single_instance() -> bool:
    global _mutex_handle
    if not IS_WINDOWS:
        return True
    try:
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, APP_ID)
        return ctypes.windll.kernel32.GetLastError() != 183  # ALREADY_EXISTS
    except Exception:
        return True


# ------------------------- [FIX 6] Estado fisico tecla --------------------- #
def physical_e_down():
    """True/False en Windows; None si no se puede saber."""
    if not IS_WINDOWS:
        return None
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(VK_E) & 0x8000)
    except Exception:
        return None


# ============================ Logica del tracker =========================== #
class ChestTracker:
    """El hook SOLO encola (ts + multiplicador). Un worker procesa y persiste."""

    def __init__(self, hold_ms: float = DEFAULT_HOLD_MS):
        self.lock = threading.Lock()
        self.count = 0
        self.buckets = {}                 # {multiplicador: nº de cofres}
        self.multiplier = DEFAULT_MULT    # lo escribe la UI, lo lee el hook
        self.hold_ms = hold_ms
        self.token_prob = DEFAULT_TOKEN_PROB
        self.press_start = None           # exclusivo del worker
        self.press_mult = DEFAULT_MULT    # exclusivo del worker
        self.last_count_time = 0.0
        self.raw_press = 0
        self.raw_release = 0
        self.errors = 0
        self.events = queue.Queue()
        self._stop = threading.Event()
        self._load_state()
        self._worker = threading.Thread(target=self._process_loop,
                                        name="chest-worker", daemon=True)
        self._worker.start()

    # ---------------- [FIX 1] deteccion a prueba de balas ---------------- #
    @staticmethod
    def _is_e(key) -> bool:
        try:
            if getattr(key, "vk", None) == VK_E:
                return True
            ch = getattr(key, "char", None)
            return bool(ch) and ch.lower() == KEY_TO_WATCH
        except Exception:
            return False

    # ------- [FIX 9] el multiplicador viaja con el evento (3-tupla SIEMPRE) -- #
    def on_press(self, key):
        try:
            if self._is_e(key):
                self.raw_press += 1
                self.events.put(("press", time.monotonic(), float(self.multiplier)))
        except Exception:
            self.errors += 1
            log.exception("on_press")

    def on_release(self, key):
        try:
            if self._is_e(key):
                self.raw_release += 1
                self.events.put(("release", time.monotonic(), float(self.multiplier)))
        except Exception:
            self.errors += 1
            log.exception("on_release")

    def request_reset_state(self):
        self.events.put(("reset", time.monotonic(), 0.0))

    # ---------------- [FIX 2] worker fuera del hook ---------------- #
    def _resync_stale(self):
        if self.press_start is None:
            return
        age = time.monotonic() - self.press_start
        if age < 0.4:
            return
        phys = physical_e_down()
        if phys is False or age > HOLD_MAX_S:
            log.warning("press_start huerfano (%.1f s) -> reset", age)
            self.press_start = None

    def _process_loop(self):
        while not self._stop.is_set():
            try:
                kind, ts, mult = self.events.get(timeout=0.25)
            except queue.Empty:
                try:
                    self._resync_stale()
                except Exception:
                    log.exception("resync")
                continue
            except Exception:
                self.errors += 1
                log.exception("cola")
                continue
            try:
                if kind == "reset":
                    self.press_start = None
                    self.press_mult = DEFAULT_MULT
                    self.last_count_time = 0.0
                    continue

                if kind == "press":
                    if self.press_start is None:      # ignora autorepeat
                        self.press_start = ts
                        self.press_mult = mult        # vigente al INICIAR
                    continue

                # ---- release ----
                if self.press_start is None:
                    continue
                hold_ms = (ts - self.press_start) * 1000.0
                used_mult = round(float(self.press_mult), 6)
                self.press_start = None
                if hold_ms >= self.hold_ms and (ts - self.last_count_time) >= COOLDOWN_S:
                    if used_mult <= 0:
                        used_mult = DEFAULT_MULT
                    with self.lock:
                        self.count += 1
                        self.last_count_time = ts
                        self.buckets[used_mult] = self.buckets.get(used_mult, 0) + 1
                        n = self.count
                        snapshot = dict(self.buckets)
                    log.info("Cofre #%d (hold %d ms, x%g)", n, int(hold_ms), used_mult)
                    self._persist(n, snapshot, int(hold_ms), used_mult)
            except Exception:
                self.errors += 1
                log.exception("worker")

    # ---------------- ajuste manual del total ---------------- #
    def set_total(self, new_total: int):
        """Fija el total de cofres. La diferencia va al bucket x1 (tasa base).
        Al reducir se descuenta de x1 primero y luego de los demas (ascendente).
        Devuelve (nuevo_total, delta)."""
        new_total = max(0, min(MAX_CHESTS, int(new_total)))
        with self.lock:
            current = sum(self.buckets.values())
            delta = new_total - current
            if delta > 0:
                self.buckets[DEFAULT_MULT] = self.buckets.get(DEFAULT_MULT, 0) + delta
            elif delta < 0:
                need = -delta
                order = sorted(self.buckets.keys(),
                               key=lambda m: (m != DEFAULT_MULT, m))
                for m in order:
                    if need <= 0:
                        break
                    take = min(need, self.buckets[m])
                    self.buckets[m] -= take
                    need -= take
                    if self.buckets[m] <= 0:
                        del self.buckets[m]
            self.count = sum(self.buckets.values())
            n = self.count
            snapshot = dict(self.buckets)
        self._persist(n, snapshot, 0,
                      note=f"total ajustado manualmente a {n} ({delta:+d})")
        log.info("total ajustado a %d (delta %+d), buckets=%s", n, delta, snapshot)
        return n, delta

    # ---------------- persistencia tolerante a fallos ---------------- #
    def _persist(self, n, buckets, hold_ms, mult=None, note=None):
        payload = {
            "total": n,
            "buckets": {str(k): v for k, v in buckets.items()},
            "ultima_actualizacion": datetime.now().isoformat(timespec="seconds"),
        }
        for attempt in range(3):
            try:
                tmp = STATE_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                os.replace(tmp, STATE_FILE)
                break
            except Exception:
                log.exception("save_state intento %d", attempt + 1)
                time.sleep(0.05)
        try:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                if hold_ms:
                    f.write(f"[{stamp}] Cofre #{n}  (E {hold_ms} ms, x{mult:g})\n")
                elif note:
                    f.write(f"[{stamp}] --- {note} ---\n")
                else:
                    f.write(f"[{stamp}] --- contador reiniciado / cierre ---\n")
        except Exception:
            log.exception("append_log")

    @staticmethod
    def _parse_buckets(data):
        """Migra estados antiguos (solo 'total') al formato por multiplicador."""
        raw = data.get("buckets")
        if isinstance(raw, dict) and raw:
            out = {}
            for k, v in raw.items():
                try:
                    m = round(float(k), 6)
                    n = int(v)
                    if m > 0 and n > 0:
                        out[m] = out.get(m, 0) + n
                except Exception:
                    continue
            if out:
                return out, sum(out.values())
        try:
            total = int(data.get("total", 0))
        except Exception:
            total = 0
        if total > 0:
            return {DEFAULT_MULT: total}, total
        return {}, 0

    def _load_state(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        self.buckets, self.count = self._parse_buckets(data)
        if self.buckets:
            log.info("estado cargado: %d cofres, buckets=%s", self.count, self.buckets)

    def snapshot(self):
        with self.lock:
            return self.count, dict(self.buckets)

    def reset(self):
        with self.lock:
            self.count = 0
            self.buckets = {}
        self.request_reset_state()
        self._persist(0, {}, 0, note="contador reiniciado desde la UI")
        log.info("contador reiniciado desde la UI")

    def shutdown(self):
        self._stop.set()
        try:
            n, bk = self.snapshot()
            self._persist(n, bk, 0, note="cierre de la aplicacion")
        except Exception:
            pass


# =============================== Matematica ================================ #
def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def log_survival(buckets: dict, p: float) -> float:
    """log( P(ningun token) ) = sum_i n_i * ln(1 - m_i*p).
    -inf significa exito garantizado. log1p evita perdida de precision."""
    ls = 0.0
    for m, n in buckets.items():
        if n <= 0:
            continue
        pe = clamp01(m * p)
        if pe >= 1.0:
            return float("-inf")
        if pe > 0.0:
            ls += n * math.log1p(-pe)
    return ls


def cumulative(buckets: dict, p: float) -> float:
    """P(al menos un exito) = 1 - PROD (1 - m_i*p)^n_i.
    Solo depende de los cofres YA abiertos: no cambia con el multiplicador."""
    ls = log_survival(buckets, p)
    if ls == float("-inf"):
        return 1.0
    return max(0.0, min(1.0, -math.expm1(ls)))


def remaining_for_target(buckets: dict, p: float, mult: float, target: float) -> int:
    """Cofres RESTANTES (al multiplicador actual) para alcanzar 'target',
    teniendo en cuenta la probabilidad ya acumulada.
    0 si ya se alcanzo, -1 si es imposible (p efectiva = 0)."""
    if not (0 < target < 1):
        return 0
    ls = log_survival(buckets, p)
    tls = math.log1p(-target)
    if ls <= tls:
        return 0
    pe = clamp01(mult * p)
    if pe <= 0.0:
        return -1
    if pe >= 1.0:
        return 1
    return max(0, math.ceil((tls - ls) / math.log1p(-pe)))


def journey_progress(opened: int, remaining: int) -> float:
    """Fraccion del camino recorrida, en cofres.

    opened:    cofres que ya llevas abiertos (total real)
    remaining: cofres que faltan al multiplicador actual

    SI cambia con el multiplicador: si faltan menos cofres, has recorrido una
    parte mayor del camino. La probabilidad acumulada, en cambio, solo depende
    de lo ya abierto y se muestra aparte.
    """
    if remaining < 0:
        return 0.0                      # imposible (p efectiva = 0)
    if remaining == 0:
        return 1.0                      # objetivo alcanzado
    total = opened + remaining
    if total <= 0:
        return 1.0
    return max(0.0, min(1.0, opened / total))


def equivalent_chests(buckets: dict) -> float:
    """Cofres 'equivalentes a x1' (informativo, aproximacion de primer orden)."""
    return sum(m * n for m, n in buckets.items())


# --- referencia: caso simple x1 desde cero (generalizado por las de arriba) --- #
def cumulative_success(n: int, p: float) -> float:
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return 1.0 - math.pow(1.0 - p, n)


def chests_for_target(p: float, target: float) -> int:
    if p <= 0 or p >= 1 or not (0 < target < 1):
        return 0
    return max(0, math.ceil(math.log(1.0 - target) / math.log(1.0 - p)))


# =============================== Imagenes ================================== #
def make_chest_ctk_image(size: int):
    try:
        import customtkinter as ctk
        from PIL import Image
        png = _find_asset("pirate-shop-token.png")
        if not png:
            return None
        img = Image.open(png).convert("RGBA").resize((size, size),
                                                     Image.Resampling.LANCZOS)
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception:
        log.exception("make_chest_ctk_image")
        return None


def save_chest_png(path: str, size: int = 64):
    try:
        from PIL import Image
        png = _find_asset("pirate-shop-token.png")
        if not png:
            return None
        Image.open(png).convert("RGBA").resize(
            (size, size), Image.Resampling.LANCZOS).save(path)
        return path
    except Exception:
        log.exception("save_chest_png")
        return None


# ============================ Interfaz grafica ============================= #
BG       = "#1b1f2e"
CARD     = "#262b40"
ACCENT   = "#ffb43c"
BLUE     = "#3d6fd6"
GREEN    = "#7ee081"
RED      = "#ff5555"
PURPLE   = "#6b5bd2"
SLATE    = "#3a4266"
TEXT_DIM = "#9aa3c0"


class App:
    def __init__(self, tracker: ChestTracker, start_minimized: bool = False):
        self.tracker = tracker
        self.listener = None
        self.restarts = 0
        self._last_seen = -1
        self._closing = False
        self._tray_show = False
        self._tray_quit = False
        self._count_focused = False
        self._prob_history = []           # para "Deshacer"

        set_app_user_model_id()

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

        self.root.title(f"Fortnite Chest Tracker v{APP_VERSION}")
        self.root.geometry("700x830")
        self.root.minsize(650, 780)

        self._icon_path = ensure_icon_file()
        self._apply_icon()

        self.chest_img = make_chest_ctk_image(100) if self._use_ctk else None

        self.var_count   = self._stringvar("0")
        self.var_single  = self._stringvar("-")
        self.var_eff     = self._stringvar("-")
        self.var_cum     = self._stringvar("-")
        self.var_n50     = self._stringvar("-")
        self.var_n90     = self._stringvar("-")
        self.var_status  = self._stringvar("Mantén E para abrir cofres")
        self.var_capture = self._stringvar("● CAPTURA ACTIVA")
        self.var_multbadge = self._stringvar("x1")
        self.var_multwarn  = self._stringvar("")
        self.var_speed   = self._stringvar("")
        self.var_diag    = self._stringvar("")
        self.var_hist    = self._stringvar("")
        self.prob_entry_val  = self._stringvar(f"{tracker.token_prob * 100:.6f}")
        self.mult_entry_val  = self._stringvar(f"{tracker.multiplier:g}")
        self.count_entry_val = self._stringvar(str(tracker.count))

        self._build_ui()
        self._refresh()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_listener()
        self.root.after(150, self._poll)
        self.root.after(250, self._apply_icon)

        if start_minimized:
            self.root.withdraw()

    # ---------- [FIX 5] listener + watchdog ---------- #
    def _start_listener(self):
        if keyboard is None:
            self.var_status.set("ERROR: falta pynput (pip install pynput)")
            self.var_capture.set("● SIN CAPTURA")
            return
        try:
            self.tracker.request_reset_state()
            self.listener = keyboard.Listener(on_press=self.tracker.on_press,
                                              on_release=self.tracker.on_release)
            self.listener.daemon = True
            self.listener.start()
            log.info("listener iniciado (restarts=%d)", self.restarts)
        except Exception:
            log.exception("no se pudo iniciar el listener")
            self.listener = None

    def _ensure_listener(self):
        if keyboard is None:
            return
        try:
            alive = self.listener is not None and self.listener.is_alive()
        except Exception:
            alive = False
        if not alive:
            self.restarts += 1
            log.warning("listener CAIDO -> reiniciando (#%d)", self.restarts)
            self._start_listener()
            self.var_status.set(f"Captura reactivada automáticamente ({self.restarts})")

    def _force_reconnect(self):
        try:
            if self.listener is not None:
                self.listener.stop()
        except Exception:
            pass
        self.listener = None
        self._ensure_listener()
        self.var_status.set("Captura reiniciada manualmente.")

    # ---------- [FIX 3] polling: unica puerta a Tkinter ---------- #
    def _poll(self):
        if self._closing:
            return
        try:
            if self._tray_show:
                self._tray_show = False
                self.show()
            if self._tray_quit:
                self._tray_quit = False
                self._on_close()
                return

            self._ensure_listener()

            n = self.tracker.count
            if n != self._last_seen:
                self._last_seen = n
                self._refresh()
                self.var_status.set(f"¡Cofre abierto! Total: {n}")

            alive = self.listener is not None and self.listener.is_alive()
            self.var_capture.set("● CAPTURA ACTIVA" if alive else "● REACTIVANDO…")
            try:
                self.lbl_capture.configure(text_color=GREEN if alive else RED)
            except Exception:
                pass
            self.var_diag.set(
                f"E: {self.tracker.raw_press} press / {self.tracker.raw_release} release"
                f"   ·   contados: {n}   ·   reinicios: {self.restarts}"
                f"   ·   errores: {self.tracker.errors}")
        except Exception:
            log.exception("poll")
        finally:
            try:
                self.root.after(150, self._poll)
            except Exception:
                pass

    def _apply_icon(self):
        if not self._icon_path:
            return
        try:
            self.root.iconbitmap(default=self._icon_path)
        except Exception:
            log.exception("iconbitmap")

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
        return tk.Label(parent, textvariable=textvariable, text=text, bg=CARD,
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
                                      fg_color=color, corner_radius=8, width=width)
        import tkinter as tk
        return tk.Button(parent, text=text, command=cmd, bg=color, fg="#101018",
                         relief="flat", padx=6, pady=4, width=max(4, width // 9))

    def _entry(self, parent, var, width_chars=8):
        if self._use_ctk:
            return self.ctk.CTkEntry(parent, textvariable=var, width=width_chars * 10)
        import tkinter as tk
        return tk.Entry(parent, textvariable=var, width=width_chars, bg="#11141f",
                        fg="white", insertbackground="white", relief="flat")

    def _progress_bar(self, parent):
        if self._use_ctk:
            return self.ctk.CTkProgressBar(parent, height=12, progress_color=ACCENT)
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
        if self._use_ctk:
            outer = self.ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        else:
            outer = self._card(self.root)
        outer.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- cabecera ---- #
        header = self._card(outer)
        header.pack(fill="x", padx=10, pady=(10, 6))
        title_row = self._row(header)
        title_row.pack(fill="x", padx=12, pady=8)
        if self.chest_img is not None:
            small = make_chest_ctk_image(34)
            lbl = self.ctk.CTkLabel(title_row, image=small, text="")
            self._small_icon_ref = (lbl, small)
            lbl.pack(side="left", padx=(0, 8))
        self._label(title_row, text="CHEST TRACKER", size=20, color=ACCENT,
                    bold=True).pack(side="left")
        self.lbl_capture = self._label(title_row, textvariable=self.var_capture,
                                       size=11, color=GREEN, bold=True)
        self.lbl_capture.pack(side="right", padx=4)
        self.lbl_multbadge = self._label(title_row, textvariable=self.var_multbadge,
                                         size=13, color=TEXT_DIM, bold=True)
        self.lbl_multbadge.pack(side="right", padx=(0, 10))

        # ---- avisos ---- #
        warn = self._card(outer)
        warn.pack(fill="x", padx=10, pady=(0, 6))
        wrow = self._row(warn)
        wrow.pack(fill="x", padx=12, pady=10)
        self._label(wrow, text="⚠️  NO OLVIDAR CERRAR JUNTO A FORTNITE  ⚠️",
                    size=17, color="#ff3333", bold=True,
                    anchor="center").pack(pady=(0, 4))
        self._label(wrow, text="El programa sigue contando incluso sin Fortnite abierto",
                    size=11, color="#ff6666", anchor="center").pack()
        self.lbl_multwarn = self._label(wrow, textvariable=self.var_multwarn,
                                        size=12, color=ACCENT, bold=True,
                                        anchor="center")
        self.lbl_multwarn.pack(pady=(4, 0))
        self._label(wrow, textvariable=self.var_status, size=11, color=TEXT_DIM,
                    anchor="center").pack(pady=(4, 0))

        # ---- panel principal ---- #
        main = self._card(outer)
        main.pack(fill="both", expand=True, padx=10, pady=6)
        grid = self._row(main)
        grid.pack(fill="both", expand=True, padx=6, pady=6)

        left = self._row(grid)
        left.pack(side="left", expand=True, fill="both", padx=10, pady=10)
        self._label(left, text="COFRES ABIERTOS", size=13, color=TEXT_DIM,
                    bold=True).pack(anchor="w", pady=(0, 2))
        self._label(left, textvariable=self.var_count, size=54, color="#ffffff",
                    bold=True).pack(anchor="w")
        self.progress = self._progress_bar(left)
        self.progress.pack(fill="x", pady=(14, 2))
        self._label(left, text="Camino al ~90 % (en cofres)",
                    size=11, color=TEXT_DIM).pack(anchor="w")
        self._label(left, textvariable=self.var_speed, size=10,
                    color=PURPLE, bold=True).pack(anchor="w", pady=(2, 0))
        self._label(left, textvariable=self.var_hist, size=10,
                    color=TEXT_DIM).pack(anchor="w", pady=(10, 0))

        right = self._row(grid)
        right.pack(side="left", expand=True, fill="both", padx=10, pady=10)
        prob_row = self._row(right)
        prob_row.pack(anchor="w", pady=(0, 4))
        if self.chest_img is not None:
            self.ctk.CTkLabel(prob_row, image=self.chest_img,
                              text="").pack(side="left", padx=(0, 12))
        stats = self._row(prob_row)
        stats.pack(side="left")
        self._label(stats, text="Prob. base (por cofre, x1)", size=12,
                    color=TEXT_DIM).pack(anchor="w")
        self._label(stats, textvariable=self.var_single, size=17, color=ACCENT,
                    bold=True).pack(anchor="w")
        self._label(stats, text="Prob. efectiva (con multiplicador)", size=12,
                    color=TEXT_DIM).pack(anchor="w", pady=(6, 0))
        self._label(stats, textvariable=self.var_eff, size=17, color=PURPLE,
                    bold=True).pack(anchor="w")
        self._label(stats, text="Prob. acumulada (histórico exacto)", size=12,
                    color=TEXT_DIM).pack(anchor="w", pady=(6, 0))
        self._label(stats, textvariable=self.var_cum, size=17, color=GREEN,
                    bold=True).pack(anchor="w")

        refs = self._row(right)
        refs.pack(anchor="w", pady=(8, 0))
        self._mini_card(refs, "Restantes ~50 %", self.var_n50).pack(
            side="left", padx=(0, 8))
        self._mini_card(refs, "Restantes ~90 %", self.var_n90).pack(side="left")

        # ---- controles ---- #
        ctrl = self._card(outer)
        ctrl.pack(fill="x", padx=10, pady=6)

        # Fila A: probabilidad base + restaurar + deshacer
        arow = self._row(ctrl)
        arow.pack(fill="x", padx=12, pady=(10, 4))
        self._label(arow, text="Prob. token (%):", size=13).pack(side="left")
        self.prob_entry = self._entry(arow, self.prob_entry_val, 9)
        self.prob_entry.pack(side="left", padx=6)
        self.prob_entry.bind("<Return>", lambda e: self._apply_prob())
        self._button(arow, "Aplicar", self._apply_prob, color=GREEN,
                     width=80).pack(side="left", padx=3)
        self._button(arow, "Restaurar", self._restore_prob, color=BLUE,
                     width=88).pack(side="left", padx=3)
        self.btn_undo = self._button(arow, "Deshacer", self._undo_prob,
                                     color=SLATE, width=84)
        self.btn_undo.pack(side="left", padx=3)
        self._label(arow, text=f"Real: {DEFAULT_TOKEN_PROB * 100:.6f} %",
                    size=10, color=TEXT_DIM).pack(side="right", padx=4)

        # Fila B: multiplicador
        mrow = self._row(ctrl)
        mrow.pack(fill="x", padx=12, pady=4)
        self._label(mrow, text="Multiplicador (x):", size=13).pack(side="left")
        self.mult_entry = self._entry(mrow, self.mult_entry_val, 6)
        self.mult_entry.pack(side="left", padx=6)
        self.mult_entry.bind("<Return>", lambda e: self._apply_mult())
        for txt, val in (("x1", 1.0), ("x1.5", 1.5), ("x2", 2.0)):
            self._button(mrow, txt, lambda v=val: self._preset_mult(v),
                         color=SLATE, width=48).pack(side="left", padx=2)
        self._button(mrow, "Aplicar", self._apply_mult, color=ACCENT,
                     width=80).pack(side="left", padx=6)
        self._label(mrow, text="Solo afecta a los próximos cofres",
                    size=10, color=TEXT_DIM).pack(side="right", padx=4)

        # Fila C: total de cofres + acciones
        crow = self._row(ctrl)
        crow.pack(fill="x", padx=12, pady=(4, 10))
        self._label(crow, text="Cofres abiertos:", size=13).pack(side="left")
        self.count_entry = self._entry(crow, self.count_entry_val, 9)
        self.count_entry.pack(side="left", padx=6)
        self.count_entry.bind("<Return>", lambda e: self._apply_count())
        self.count_entry.bind("<FocusIn>", lambda e: self._set_count_focus(True))
        self.count_entry.bind("<FocusOut>", lambda e: self._set_count_focus(False))
        self._button(crow, "Aplicar", self._apply_count, color=GREEN,
                     width=80).pack(side="left", padx=3)
        self._label(crow, text="ajusta x1", size=10,
                    color=TEXT_DIM).pack(side="left", padx=2)
        self._button(crow, "Salir", self._on_close, color="#b3384a",
                     width=66).pack(side="right", padx=3)
        self._button(crow, "Reiniciar", self._reset, color=BLUE,
                     width=86).pack(side="right", padx=3)
        self._button(crow, "Reconectar", self._force_reconnect, color=PURPLE,
                     width=96).pack(side="right", padx=3)

        # ---- pie / diagnostico ---- #
        foot = self._row(outer)
        foot.pack(fill="x")
        self._label(foot, textvariable=self.var_diag, size=10,
                    color=TEXT_DIM).pack(anchor="w", padx=14, pady=(2, 0))
        self._label(foot, text=f"Registro: {LOG_FILE}", size=10,
                    color=TEXT_DIM).pack(anchor="w", padx=14, pady=(0, 8))

    def _set_count_focus(self, value):
        self._count_focused = bool(value)

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
        x = max(0.0, min(1.0, x))       # normaliza -0.0
        pct = x * 100
        if pct < 0.001:
            return f"{pct:.6f} %"
        elif pct < 0.01:
            return f"{pct:.4f} %"
        elif pct < 0.1:
            return f"{pct:.3f} %"
        return f"{pct:.2f} %"

    @staticmethod
    def _fmt_int(n):
        if n < 0:
            return "∞"
        return f"{n:,}".replace(",", ".")

    def _refresh(self):
        n, buckets = self.tracker.snapshot()
        p = self.tracker.token_prob
        mult = float(self.tracker.multiplier)

        cum = cumulative(buckets, p)
        eff = clamp01(mult * p)

        self.var_count.set(str(n))
        # no pisar lo que el usuario esta escribiendo
        if not self._count_focused:
            self.count_entry_val.set(str(n))

        self.var_single.set(self._fmt_pct(p))
        self.var_eff.set(self._fmt_pct(eff) + f"  (x{mult:g})")
        self.var_cum.set(self._fmt_pct(cum))

        r50 = remaining_for_target(buckets, p, mult, 0.50)
        r90 = remaining_for_target(buckets, p, mult, 0.90)
        self.var_n50.set(self._fmt_int(r50))
        self.var_n90.set(self._fmt_int(r90))

        # ---- barra: camino recorrido en cofres (cambia con el multiplicador) ----
        journey = journey_progress(n, r90)
        try:
            self.progress.set(journey)
        except Exception:
            pass
        self.var_speed.set(
            f"{journey * 100:.2f} % del camino · faltan {self._fmt_int(r90)} cofres")

        self.var_multbadge.set(f"x{mult:g}")
        try:
            self.lbl_multbadge.configure(text_color=ACCENT if mult != 1.0 else TEXT_DIM)
        except Exception:
            pass
        if mult != 1.0:
            self.var_multwarn.set(
                f"⚡ MULTIPLICADOR x{mult:g} ACTIVO — recuerda volver a x1 al acabar el evento")
        else:
            self.var_multwarn.set("")

        if buckets:
            partes = " · ".join(f"{v}×x{k:g}" for k, v in sorted(buckets.items()))
            equiv = f"{equivalent_chests(buckets):,.0f}".replace(",", ".")
            self.var_hist.set(f"Histórico: {partes}   (≈ {equiv} cofres a x1)")
        else:
            self.var_hist.set("Histórico: sin cofres todavía")

    # ---------- configuracion ---------- #
    def _save_config(self):
        cfg = {}
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                cfg = {}
        except Exception:
            pass
        cfg["token_prob"] = self.tracker.token_prob
        cfg["multiplier"] = float(self.tracker.multiplier)
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            log.exception("save_config")

    def _push_prob_history(self, old_value):
        self._prob_history.append(float(old_value))
        if len(self._prob_history) > PROB_HISTORY:
            self._prob_history.pop(0)

    def _set_prob(self, p, message):
        self.tracker.token_prob = p
        self.prob_entry_val.set(f"{p * 100:.6f}")
        self._save_config()
        self.var_status.set(message)
        self._refresh()

    # ---------- acciones: probabilidad ---------- #
    def _apply_prob(self):
        try:
            pct = float(self.prob_entry_val.get().replace(",", "."))
            if not (0 < pct <= 100):
                raise ValueError
            new_p = pct / 100.0
            old_p = self.tracker.token_prob
            if abs(new_p - old_p) > 1e-15:
                self._push_prob_history(old_p)
            self._set_prob(new_p, f"Probabilidad base aplicada: {pct:g} % por cofre")
            log.info("prob base = %g %%", pct)
        except Exception:
            self.var_status.set("Valor inválido: usa un número entre 0 y 100.")
            self._refresh()

    def _restore_prob(self):
        old_p = self.tracker.token_prob
        if abs(old_p - DEFAULT_TOKEN_PROB) <= 1e-15:
            self.var_status.set("Ya estás usando la probabilidad real.")
            return
        self._push_prob_history(old_p)
        self._set_prob(DEFAULT_TOKEN_PROB,
                       f"Probabilidad real restaurada: {DEFAULT_TOKEN_PROB * 100:.6f} % (1/137500)")
        log.info("prob restaurada al valor real")

    def _undo_prob(self):
        if not self._prob_history:
            self.var_status.set("No hay cambios de probabilidad que deshacer.")
            return
        prev = self._prob_history.pop()
        self._set_prob(prev, f"Probabilidad anterior restaurada: {prev * 100:.6f} %")
        log.info("prob deshecha -> %g %%", prev * 100)

    # ---------- acciones: multiplicador ---------- #
    def _preset_mult(self, value):
        self.mult_entry_val.set(f"{value:g}")
        self._apply_mult()

    def _apply_mult(self):
        try:
            raw = self.mult_entry_val.get().strip().lower().lstrip("x").replace(",", ".")
            m = float(raw)
            if not (MULT_MIN <= m <= MULT_MAX):
                raise ValueError
            m = round(m, 6)
            self.tracker.multiplier = m       # lectura atomica desde el hook
            self.mult_entry_val.set(f"{m:g}")
            self._save_config()
            self.var_status.set(
                f"Multiplicador x{m:g} aplicado a los PRÓXIMOS cofres (histórico intacto)")
            log.info("multiplicador = x%g", m)
        except Exception:
            self.var_status.set(
                f"Multiplicador inválido: usa un número entre {MULT_MIN:g} y {MULT_MAX:g}.")
        self._refresh()

    # ---------- acciones: total de cofres ---------- #
    @staticmethod
    def _parse_count(raw):
        s = raw.strip().replace(" ", "").replace("_", "")
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):   # separador de miles
            s = s.replace(".", "").replace(",", "")
        if not s.isdigit():
            raise ValueError
        n = int(s)
        if n > MAX_CHESTS:
            raise ValueError
        return n

    def _apply_count(self):
        import tkinter.messagebox as messagebox
        try:
            target = self._parse_count(self.count_entry_val.get())
        except Exception:
            self.var_status.set(
                f"Número inválido: usa un entero entre 0 y {MAX_CHESTS:,}".replace(",", "."))
            self._refresh()
            return

        current, buckets = self.tracker.snapshot()
        if target == current:
            self.var_status.set(f"El total ya es {current}.")
            self.count_entry_val.set(str(current))
            return

        delta = target - current
        if delta < 0:
            detalle = ("Se descontarán de tu histórico base (x1) primero; "
                       "solo se tocarán los cofres de evento si x1 se agota.")
            if not messagebox.askyesno(
                    title="Confirmar reducción",
                    message=f"Vas a reducir el total de {current} a {target} cofres "
                            f"({delta:+d}).\n\n{detalle}\n\n¿Continuar?"):
                self.count_entry_val.set(str(current))
                self.var_status.set("Ajuste de cofres cancelado.")
                return

        n, applied = self.tracker.set_total(target)
        self._last_seen = n                    # evita que el polling pise el estado
        self.count_entry_val.set(str(n))
        self._refresh()
        if applied > 0:
            self.var_status.set(
                f"Total ajustado a {n} cofres (+{applied} añadidos al histórico x1)")
        else:
            self.var_status.set(f"Total ajustado a {n} cofres ({applied})")

    # ---------- acciones: reset / ventana ---------- #
    def _reset(self):
        import tkinter.messagebox as messagebox
        if messagebox.askyesno(
                title="⚠️ Confirmar reinicio",
                message="¿Estás SEGURO de que quieres reiniciar el contador a 0?\n\n"
                        "Se borrará el contador y el histórico por multiplicador.\n"
                        "Esta acción NO se puede deshacer."):
            self.tracker.reset()
            self._last_seen = 0
            self.count_entry_val.set("0")
            self._refresh()
            self.var_status.set("Contador e histórico reiniciados.")
        else:
            self.var_status.set("Reinicio cancelado por el usuario.")

    def show(self):
        try:
            self.root.deiconify()
            self.root.lift()
        except Exception:
            pass

    def request_show(self):
        self._tray_show = True

    def request_quit(self):
        self._tray_quit = True

    def _on_close(self):
        self._closing = True
        try:
            if self.listener is not None:
                self.listener.stop()
        except Exception:
            pass
        try:
            self.tracker.shutdown()
        except Exception:
            pass
        log.info("app cerrada")
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ================================= Tray ==================================== #
def run_tray(app, stop_event):
    try:
        import pystray
        from PIL import Image
    except ImportError:
        log.warning("pystray no instalado: --tray ignorado")
        return
    png = save_chest_png(os.path.join(DATA_DIR, "_chest_tray.png"), 64)
    if not png:
        return
    try:
        img = Image.open(png)
    except Exception:
        return

    def restore(icon, item):
        app.request_show()

    def quit_(icon, item):
        stop_event.set()
        app.request_quit()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Abrir ventana", restore, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Salir", quit_),
    )
    try:
        pystray.Icon("chest_tracker", img, "Fortnite Chest Tracker", menu).run()
    except Exception:
        log.exception("tray")


# ================================= Main ===================================== #
def load_config():
    """Devuelve (token_prob, multiplier) con validacion y defaults."""
    p, m = DEFAULT_TOKEN_PROB, DEFAULT_MULT
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict):
            try:
                pv = float(cfg.get("token_prob", DEFAULT_TOKEN_PROB))
                if 0 < pv <= 1:
                    p = pv
            except Exception:
                pass
            try:
                mv = float(cfg.get("multiplier", DEFAULT_MULT))
                if MULT_MIN <= mv <= MULT_MAX:
                    m = round(mv, 6)
            except Exception:
                pass
    except Exception:
        pass
    return p, m


def parse_args():
    p = argparse.ArgumentParser(description=f"Fortnite Chest Tracker v{APP_VERSION}")
    p.add_argument("--hold", type=float, default=DEFAULT_HOLD_MS, metavar="MS",
                   help=f"ms minimos de E para contar (def. {DEFAULT_HOLD_MS:g})")
    p.add_argument("--prob", type=float, default=None, metavar="P",
                   help="probabilidad base por cofre, 0..1")
    p.add_argument("--mult", type=float, default=None, metavar="X",
                   help="multiplicador de evento (def. 1)")
    p.add_argument("--chests", type=int, default=None, metavar="N",
                   help="fija el total de cofres al arrancar")
    p.add_argument("--minimized", action="store_true", help="arrancar oculto")
    p.add_argument("--tray", action="store_true", help="icono en la bandeja")
    p.add_argument("--debug", action="store_true", help="log tambien por consola")
    p.add_argument("--multi", action="store_true", help="permitir varias instancias")
    return p.parse_args()


def main():
    args = parse_args()
    if args.debug:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        log.addHandler(sh)
        log.setLevel(logging.DEBUG)

    log.info("=== arranque v%s | frozen=%s | win=%s ===",
             APP_VERSION, getattr(sys, "frozen", False), IS_WINDOWS)

    if not args.multi and not acquire_single_instance():
        try:
            import tkinter.messagebox as mb
            mb.showwarning("Ya está abierto",
                           "Fortnite Chest Tracker ya se está ejecutando.")
        except Exception:
            pass
        return

    if keyboard is None:
        try:
            import tkinter.messagebox as mb
            mb.showerror("Falta pynput", "Instala con:  pip install pynput")
        except Exception:
            print("Falta pynput. Instala con:  pip install pynput")
        return

    saved_prob, saved_mult = load_config()

    tracker = ChestTracker(hold_ms=max(0.0, args.hold))
    tracker.token_prob = args.prob if args.prob is not None else saved_prob
    tracker.multiplier = args.mult if args.mult is not None else saved_mult
    if not (MULT_MIN <= tracker.multiplier <= MULT_MAX):
        tracker.multiplier = DEFAULT_MULT
    if args.chests is not None:
        tracker.set_total(args.chests)

    app = App(tracker, start_minimized=args.minimized)

    if args.tray:
        threading.Thread(target=run_tray, args=(app, threading.Event()),
                         daemon=True).start()

    app.run()


if __name__ == "__main__":
    main()


# ============================================================================ #
# COMPILAR (Windows) — o ejecuta build.bat, que hace todo esto y empaqueta:
#
# pyinstaller --noconfirm --clean --onefile --noconsole ^
#   --name "FortniteChestTracker" ^
#   --icon="assets\icono_app.ico" ^
#   --add-data "assets\icono_app.ico;assets" ^
#   --add-data "assets\pirate-shop-token.png;assets" ^
#   fortnite_tracker.pyw
#
# Build de diagnostico: cambia --noconsole por --console
# ============================================================================ #