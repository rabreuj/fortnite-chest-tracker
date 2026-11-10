# Fortnite Chest Tracker 🧰

Programa en Python que corre en segundo plano, cuenta cuántas veces abres un
cofre en Fortnite (detectando la tecla **E** mantenida) y muestra una
**interfaz gráfica moderna** con las probabilidades del token.

## Qué muestra la interfaz

| Elemento | Descripción |
|---|---|
| **Cofres abiertos** | Contador grande que se actualiza en vivo al abrir cada cofre |
| **Prob. del token (por cofre)** | Probabilidad `p` de que salga el token en UN cofre (editable, por defecto 0.1 %) |
| **Prob. acumulada** | Método del complemento: `P(al menos 1 éxito) = 1 − (1 − p)ⁿ` |
| **Icono del cofre** | Cofre dorado estilo Fortnite dibujado junto a las probabilidades |
| **Barra de progreso** | Progreso hacia el ~90 % de probabilidad acumulada |
| **Cofres para ~50 % / ~90 %** | Inversión del complemento: `n = ⌈ln(1−objetivo) / ln(1−p)⌉` |
| **Prob. token (%) editable** | Cámbiala si Epic ajusta la tasa real; se guarda en `config.json` |

Con p = 0.1 %: a los **693 cofres** tienes ~50 % de probabilidad de haber
visto el token, y a los **2.302 cofres** ~90 %.

## Requisitos

- Windows 10/11 (también funciona en Linux/macOS)
- Python 3.9+ → https://python.org (marca "Add Python to PATH")

```bat
pip install pynput customtkinter Pillow
```

*(Opcional para icono en la bandeja: `pip install pystray`)*

## Uso

- **Doble clic** sobre `fortnite_tracker.pyw` → abre la ventana del tracker.
- Desde terminal, con opciones:

```bat
python fortnite_tracker.pyw --hold 300          :: umbral de E mantendida (ms)
python fortnite_tracker.pyw --prob 0.002        :: prob. del token (0..1)
python fortnite_tracker.pyw --tray              :: + icono en la bandeja
python fortnite_tracker.pyw --minimized --tray  :: arrancar oculto
```

## Cómo detecta las aperturas

No existe API pública de Epic/Fortnite para esto, así que el contador se basa
en detectar la pulsación de **E mantenida ≥ 250 ms** (el anillo de interacción
del cofre tarda ~0.5 s; un toque casual de teclado dura <150 ms, por eso 250
descarta falsos positivos sin perder aperturas rápidas). Hay además un
*cooldown* de 1 s para evitar dobles conteos.

> ⚠️ Es un detector **aproximado**: contará cualquier E mantenida (también
> fuera del juego). Revisa `cofres.log`: registra la duración real de cada
> pulsación para que calibres el umbral con `--hold`.

## Archivos que genera

En `C:\Users\<TU_USUARIO>\FortniteChestTracker\`:

| Archivo | Contenido |
|---|---|
| `cofres.log` | Un renglón por cofre: fecha, hora y ms de pulsación |
| `estado.json` | Contador persistente (sobrevive reinicios) |
| `config.json` | Probabilidad del token guardada desde la UI |

## Pruebas incluidas

```bat
python test_logic.py
```

Verifica: fórmula del complemento, inversión 50 %/90 %, umbral de 250 ms
(100 ms no cuenta, 400 ms sí), cooldown, ignorar otras teclas y persistencia.

## Empaquetar como .exe para tus amigos

```bat
pip install pyinstaller
pyinstaller --noconsole --onefile --name ChestTracker fortnite_tracker.pyw
```

El ejecutable queda en `dist\ChestTracker.exe`.

**Importante:** avisa siempre a quien lo use de que el programa observa la
tecla E de forma global mientras está corriendo (es un keylogger funcional,
aunque solo cuente y no guarde texto tecleado). Que decidan ellos instalarlo.
