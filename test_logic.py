#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba rapida de la logica del tracker y las probabilidades (sin UI).
   Uso:  python test_logic.py"""
import importlib.util, os, shutil, sys, time

# Copiamos el modulo a .py para poder importarlo
src = os.path.join(os.path.dirname(__file__), "fortnite_tracker.pyw")
dst = os.path.join(os.path.dirname(__file__), "_ft_module.py")
shutil.copy(src, dst)
spec = importlib.util.spec_from_file_location("_ft_module", dst)
ft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ft)

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), "-", name)
    if not cond: fails.append(name)

# --- matematica del complemento ---
p = 0.001
check("P(0 cofres) = 0%", ft.cumulative_success(0, p) == 0.0)
check("P(693) ~ 50%", abs(ft.cumulative_success(693, p) - 0.5) < 0.001)
check("n para 50% = 693", ft.chests_for_target(p, 0.5) == 693)
check("n para 90% = 2302", ft.chests_for_target(p, 0.9) == 2302)
check("monotono creciente", all(
    ft.cumulative_success(n, p) <= ft.cumulative_success(n+1, p)
    for n in range(0, 200)))

# --- detector de aperturas (umbral + cooldown) ---
class E: char = "e"
class X: char = "x"
t = ft.ChestTracker(hold_ms=250)
t.count = 0; t.last_count_time = 0.0

t.on_press(X); time.sleep(0.4); t.on_release(X)          # tecla incorrecta
check("ignora teclas que no son E", t.count == 0)

t.on_press(E); time.sleep(0.10); t.on_release(E)         # toque corto
check("toque de 100 ms NO cuenta (< umbral)", t.count == 0)

t.on_press(E); time.sleep(0.40); t.on_release(E)         # apertura valida
check("E mantenida 400 ms SI cuenta", t.count == 1)

t.on_press(E); time.sleep(0.40); t.on_release(E)         # dentro del cooldown
check("cooldown evita doble conteo inmediato", t.count == 1)

t.last_count_time = 0.0                                   # fuerza fin de cooldown
t.on_press(E); time.sleep(0.40); t.on_release(E)
check("tras cooldown vuelve a contar", t.count == 2)

# --- persistencia ---
loaded = ft.ChestTracker()
check("estado persistido en estado.json", loaded.count == 2)

os.remove(dst)
print("\nRESULTADO:", "TODO OK" if not fails else f"FALLOS: {fails}")
sys.exit(1 if fails else 0)
