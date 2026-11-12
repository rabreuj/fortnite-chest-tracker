#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera icono_app.ico (multiresolucion) a partir de pirate-shop-token.png.

Un .ico valido para Windows debe contener varios tamanos; un PNG renombrado
a .ico NO funciona y Explorer muestra el icono generico.

Uso:  python crear_icono.py
"""

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Falta Pillow. Instala con:  pip install Pillow")
    sys.exit(1)

HERE = Path(__file__).resolve().parent
SRC = HERE / "pirate-shop-token.png"
DST = HERE / "icono_app.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48),
         (64, 64), (128, 128), (256, 256)]


def main():
    if not SRC.exists():
        print(f"[ERROR] No se encuentra {SRC.name}")
        return 1
    try:
        img = Image.open(SRC).convert("RGBA")
    except Exception as e:
        print(f"[ERROR] No se pudo abrir el PNG: {e}")
        return 1

    print(f"Origen : {SRC.name}  ({img.width}x{img.height})")
    if img.width != img.height:
        lado = max(img.width, img.height)
        lienzo = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        lienzo.paste(img, ((lado - img.width) // 2, (lado - img.height) // 2))
        img = lienzo
        print("Aviso  : el PNG no era cuadrado, se ha centrado sobre lienzo transparente.")

    try:
        img.save(DST, format="ICO", sizes=SIZES)
    except Exception as e:
        print(f"[ERROR] No se pudo escribir el ICO: {e}")
        return 1

    print(f"Generado: {DST.name}  ({DST.stat().st_size / 1024:.1f} KB)")
    print("Tamanos :", ", ".join(f"{w}x{h}" for w, h in SIZES))
    print()
    print("Si Explorer sigue mostrando el icono antiguo, es cache de Windows:")
    print("    ie4uinit.exe -show")
    return 0


if __name__ == "__main__":
    sys.exit(main())