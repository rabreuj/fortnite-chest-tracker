#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests de la logica de Fortnite Chest Tracker v1.1.

No abre la GUI ni modifica tu contador real: redirige estado.json y cofres.log
a un directorio temporal antes de instanciar nada.

Uso:  python test_logic.py
"""

import importlib.machinery
import importlib.util
import math
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "fortnite_tracker.pyw"

if not SRC.exists():
    print(f"[ERROR] No se encuentra {SRC.name} junto a este script.")
    sys.exit(1)

_loader = importlib.machinery.SourceFileLoader("ftc", str(SRC))
_spec = importlib.util.spec_from_loader("ftc", _loader)
ftc = importlib.util.module_from_spec(_spec)
_loader.exec_module(ftc)

# Neutraliza la consulta del estado fisico de la tecla (dependiente de Windows)
ftc.physical_e_down = lambda: None

_results = []


def check(nombre, cond, extra=""):
    ok = bool(cond)
    _results.append(ok)
    print(f"  {'OK  ' if ok else 'FAIL'}  {nombre}" + (f"   {extra}" if extra else ""))


def fresh_tracker(hold=250):
    """Tracker nuevo con estado aislado en un temporal propio."""
    d = Path(tempfile.mkdtemp(prefix="ftc_test_"))
    ftc.STATE_FILE = str(d / "estado.json")
    ftc.LOG_FILE = str(d / "cofres.log")
    return ftc.ChestTracker(hold_ms=hold)


class FakeKeyCode:
    """Imita pynput.keyboard.KeyCode: tiene vk y char, NO tiene .name"""
    def __init__(self, vk=None, char=None):
        self.vk, self.char = vk, char


class FakeKey:
    """Imita el enum Key: tiene .name, NO tiene .char"""
    def __init__(self, name):
        self.name = name


E = FakeKeyCode(vk=0x45, char="e")
P = 1 / 137500


def abrir(tr, t0, mult, hold=0.30):
    tr.events.put(("press", t0, mult))
    tr.events.put(("release", t0 + hold, mult))


# --------------------------------------------------------------------------- #
print("\n=== 1) El bug de v1.0 y su correccion ===")


def _key_name_viejo(key):
    try:
        return key.char.lower()
    except AttributeError:
        return (key.name or "").lower()


killer = FakeKeyCode(vk=0xFF, char=None)
try:
    _key_name_viejo(killer)
    check("el codigo viejo falla con KeyCode(char=None)", False, "no lanzo excepcion")
except AttributeError as e:
    check("el codigo viejo lanza AttributeError (mataba el listener)", True, str(e))
check("el codigo nuevo NO lanza excepcion", ftc.ChestTracker._is_e(killer) is False)

print("\n=== 2) _is_e robusto ===")
casos = [
    ("E normal", FakeKeyCode(vk=0x45, char="e"), True),
    ("Shift+E", FakeKeyCode(vk=0x45, char="E"), True),
    ("Ctrl+E char=None", FakeKeyCode(vk=0x45, char=None), True),
    ("Ctrl+E char=\\x05", FakeKeyCode(vk=0x45, char="\x05"), True),
    ("tecla muerta (e con acento)", FakeKeyCode(vk=0x45, char="\u00e9"), True),
    ("KeyCode huerfano", killer, False),
    ("Key.shift", FakeKey("shift"), False),
    ("sin vk ni char", FakeKeyCode(), False),
    ("None", None, False),
    ("tecla W", FakeKeyCode(vk=0x57, char="w"), False),
]
for nombre, key, esperado in casos:
    got = ftc.ChestTracker._is_e(key)
    check(nombre, got == esperado, f"-> {got}")

print("\n=== 3) Matematica: probabilidad acumulada ===")
for n in (0, 1, 100, 5000, 95296):
    nuevo = ftc.cumulative({1.0: n}, P)
    viejo = ftc.cumulative_success(n, P)
    check(f"x1 con n={n} coincide con la formula clasica",
          abs(nuevo - viejo) < 1e-12, f"{nuevo:.10f}")

b = {1.0: 500, 2.0: 100, 3.0: 50}
directo = 1.0
for m, n in b.items():
    directo *= (1.0 - m * P) ** n
directo = 1.0 - directo
check("buckets mixtos == producto directo",
      abs(ftc.cumulative(b, P) - directo) < 1e-13)

check("el multiplicador NO es retroactivo",
      abs(ftc.cumulative({1.0: 500, 2.0: 100}, P) - ftc.cumulative({2.0: 600}, P)) > 1e-6)

print("\n=== 4) Coeficientes restantes (ida y vuelta) ===")
for hist, mult, target in [({1.0: 500}, 2.0, 0.5), ({1.0: 500}, 2.0, 0.9),
                           ({}, 1.0, 0.5), ({1.0: 95296}, 1.0, 0.5),
                           ({1.0: 500, 2.0: 100}, 1.5, 0.75)]:
    r = ftc.remaining_for_target(hist, P, mult, target)
    despues = dict(hist)
    despues[mult] = despues.get(mult, 0) + r
    menos = dict(hist)
    menos[mult] = menos.get(mult, 0) + max(0, r - 1)
    ok = (ftc.cumulative(despues, P) >= target - 1e-12) and \
         (r == 0 or ftc.cumulative(menos, P) < target)
    check(f"restantes minimos hist={hist} x{mult} target={target}", ok, f"r={r}")

print("\n=== 5) Barra de camino (debe cambiar con el multiplicador) ===")
abiertos = 2500
r_x1 = ftc.remaining_for_target({1.0: abiertos}, P, 1.0, 0.90)
r_x2 = ftc.remaining_for_target({1.0: abiertos}, P, 2.0, 0.90)
j1 = ftc.journey_progress(abiertos, r_x1)
j2 = ftc.journey_progress(abiertos, r_x2)
check("x2 reduce los cofres restantes", r_x2 < r_x1, f"{r_x1} -> {r_x2}")
check("x2 AUMENTA la barra", j2 > j1, f"{j1*100:.2f}% -> {j2*100:.2f}%")
check("objetivo alcanzado -> barra al 100%", ftc.journey_progress(10, 0) == 1.0)
check("imposible -> barra a 0", ftc.journey_progress(10, -1) == 0.0)
check("sin cofres -> barra a 0", ftc.journey_progress(0, 1000) == 0.0)

print("\n=== 6) Casos limite ===")
check("p efectiva >= 1 -> probabilidad 1", ftc.cumulative({200000.0: 1}, P) == 1.0)
check("p = 0 -> imposible", ftc.remaining_for_target({1.0: 10}, 0.0, 1.0, 0.5) == -1)
check("buckets vacio -> probabilidad 0", ftc.cumulative({}, P) == 0.0)
check("target ya alcanzado -> 0 restantes",
      ftc.remaining_for_target({1.0: 500000}, P, 1.0, 0.5) == 0)

print("\n=== 7) Migracion de estados antiguos ===")
for data, esperado_total, esperado_buckets in [
    ({"total": 1234}, 1234, {1.0: 1234}),
    ({"total": 0}, 0, {}),
    ({}, 0, {}),
    ({"total": "abc"}, 0, {}),
    ({"total": 650, "buckets": {"1.0": 500, "2.0": 100, "3.0": 50}}, 650,
     {1.0: 500, 2.0: 100, 3.0: 50}),
]:
    bk, tot = ftc.ChestTracker._parse_buckets(data)
    check(f"migracion {str(data)[:45]}", tot == esperado_total and bk == esperado_buckets)

print("\n=== 8) Tracker: umbral de hold y cooldown ===")
tr = fresh_tracker()
base = time.monotonic()
abrir(tr, base,        1.0, 0.30)   # cuenta
abrir(tr, base + 0.5,  1.0, 0.30)   # cooldown -> no
abrir(tr, base + 2.0,  1.0, 0.10)   # hold corto -> no
abrir(tr, base + 4.0,  1.0, 0.40)   # cuenta
abrir(tr, base + 6.0,  1.0, 0.26)   # cuenta
time.sleep(0.6)
check("3 cofres contados", tr.count == 3, f"count={tr.count}")
check("sin errores en el worker", tr.errors == 0)

print("\n=== 9) Autorepeat: muchos keydown = 1 cofre ===")
tr = fresh_tracker()
t0 = time.monotonic()
for i in range(30):
    tr.events.put(("press", t0 + i * 0.03, 1.0))
tr.events.put(("release", t0 + 0.9, 1.0))
time.sleep(0.5)
check("30 autorepeat + 1 keyup = 1 cofre", tr.count == 1, f"count={tr.count}")

print("\n=== 10) FIX 9: el multiplicador se fija al PULSAR, no al procesar ===")
tr = fresh_tracker()
tr.multiplier = 1.0
tr.on_press(E)
tr.multiplier = 2.0          # cambio inmediato, antes de soltar
time.sleep(0.30)
tr.on_release(E)
time.sleep(0.5)
check("el cofre se etiqueta x1 (no x2)",
      tr.buckets.get(1.0) == 1 and 2.0 not in tr.buckets, str(tr.buckets))

print("\n=== 11) Historico por multiplicador ===")
tr = fresh_tracker()
base = time.monotonic()
for i in range(5):
    abrir(tr, base + i * 2, 1.0)
for i in range(3):
    abrir(tr, base + 20 + i * 2, 2.0)
for i in range(2):
    abrir(tr, base + 40 + i * 2, 3.0)
time.sleep(0.6)
check("buckets correctos", tr.buckets == {1.0: 5, 2.0: 3, 3.0: 2}, str(tr.buckets))
check("total 10", tr.count == 10)
check("equivalentes a x1 = 17", ftc.equivalent_chests(tr.buckets) == 17.0)

print("\n=== 12) Ajuste manual del total ===")
tr = fresh_tracker()
base = time.monotonic()
abrir(tr, base, 1.0)
abrir(tr, base + 2, 2.0)
time.sleep(0.4)
n, delta = tr.set_total(800)
check("subir a 800 anade al bucket x1",
      n == 800 and delta == 798 and tr.buckets.get(1.0) == 799 and tr.buckets.get(2.0) == 1,
      str(tr.buckets))
n, delta = tr.set_total(1)
check("bajar a 1 descuenta de x1 primero",
      n == 1 and tr.buckets.get(1.0, 0) == 0 and tr.buckets.get(2.0) == 1,
      str(tr.buckets))
tr.reset()
time.sleep(0.3)
check("reset limpia contador y buckets", tr.count == 0 and tr.buckets == {})

print("\n=== 13) Persistencia y recarga ===")
tr = fresh_tracker()
base = time.monotonic()
abrir(tr, base, 1.0)
abrir(tr, base + 2, 2.0)
time.sleep(0.4)
tr2 = ftc.ChestTracker(hold_ms=250)   # misma ruta temporal -> debe recuperar
check("recarga el mismo historico", tr2.buckets == tr.buckets, str(tr2.buckets))

print("\n=== 14) Latencia del hook (limite de Windows ~300000 us) ===")
tr = fresh_tracker()
N = 20000
s = time.perf_counter()
for _ in range(N):
    tr.on_press(E)
    tr.on_release(E)
us = (time.perf_counter() - s) / N * 1e6
check(f"latencia {us:.2f} us por par press+release", us < 1000)
check("5000 eventos basura sin excepciones", True)
tr2 = fresh_tracker()
basura = [killer, FakeKeyCode(), None, FakeKey("ctrl_l"), "texto", 123, object()]
for i in range(5000):
    k = basura[i % len(basura)]
    tr2.on_press(k)
    tr2.on_release(k)
time.sleep(0.3)
check("errores no capturados = 0", tr2.errors == 0, f"errores={tr2.errors}")

# --------------------------------------------------------------------------- #
total = len(_results)
fallos = total - sum(_results)
print("\n" + "=" * 60)
print(f"  {total - fallos}/{total} comprobaciones correctas")
if fallos:
    print(f"  {fallos} FALLOS")
print("=" * 60 + "\n")
sys.exit(1 if fallos else 0)