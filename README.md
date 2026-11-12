# Fortnite Chest Tracker

Contador de cofres abiertos en Fortnite con cálculo de probabilidad acumulada
para el token del Pirate Shop. Windows · Python · CustomTkinter.

## Descargar

<<<<<<< HEAD
**[Última release](../../releases/latest)** → `FortniteChestTracker-v1.1-win64.zip`
Descomprime y ejecuta el `.exe`. No necesita Python ni instalación.
=======
| Elemento | Descripción |
|---|---|
| **Cofres abiertos** | Contador grande que se actualiza en vivo al abrir cada cofre |
| **Prob. del token (por cofre)** | Probabilidad `p` de que salga el token en UN cofre|
| **Prob. acumulada** | Método del complemento: `P(al menos 1 éxito) = 1 − (1 − p)ⁿ` |
| **Barra de progreso** | Progreso hacia el ~90 % de probabilidad acumulada |
| **Cofres para ~50 % / ~90 %** | Inversión del complemento: `n = ⌈ln(1−objetivo) / ln(1−p)⌉` |
| **Prob. token (%) editable** | Cámbiala si Epic ajusta la tasa real; se guarda en `config.json` |
>>>>>>> efe1a2c4c77b5bde2dca714cf72191d9c0384b33

> Windows SmartScreen puede avisar de que el ejecutable no está firmado. Es
> normal en proyectos sin certificado de firma: **Más información → Ejecutar de
> todas formas**. El código fuente está en este repositorio.

## Qué hace

Detecta la pulsación mantenida de **E** (250 ms por defecto) y cuenta un cofre.
Es un contador global de teclado: **no inyecta nada en el juego ni lee su
memoria**. Cuenta E en cualquier aplicación, así que **ciérralo cuando dejes de
jugar** o inflarás el contador.

- Contador persistente, **editable a mano** si ya llevabas cofres antes de usar la app.
- Probabilidad base configurable, con **Restaurar** y **Deshacer**.
- **Multiplicador de evento** (x1 / x1.5 / x2 o el que quieras).
- Probabilidad acumulada exacta y cofres restantes para el ~50 % y ~90 %.
- Registro legible de cada apertura y log de diagnóstico.

## Las dos magnitudes (importante)

| | Depende de | ¿Cambia al tocar el multiplicador? |
|---|---|---|
| **Prob. acumulada** (tarjeta verde) | solo los cofres ya abiertos | **No** |
| **Camino al 90 %** (barra) | abiertos + cofres que faltan | **Sí** |

Activar x2 no abre cofres, así que tu probabilidad acumulada no cambia. Lo que
cambia es la distancia al objetivo: la barra avanza y los "Restantes" bajan.

## La matemática

Con `n` cofres a probabilidad `p` por cofre, la probabilidad de al menos un
token es el complemento de no conseguir ninguno:

```
P = 1 - (1 - p)^n
```

Con multiplicadores distintos en el histórico, cada cofre tiene su propia tasa:

```
P = 1 - ∏ (1 - mᵢ · p)^nᵢ
```

**El multiplicador no es retroactivo.** Si abriste 500 cofres a x1 y luego 100 a
x2, tu probabilidad real es `1 - (1-p)^500 · (1-2p)^100`, no `1 - (1-2p)^600`.

El cálculo se hace en log-espacio con `log1p`/`expm1` para no perder precisión
con probabilidades diminutas y contadores grandes.

> La probabilidad por defecto (1/137500 ≈ 0,000727 %) es un valor de referencia
> configurable.

## Uso

| Campo | Qué hace |
|---|---|
| **Prob. token (%)** | Probabilidad base por cofre. `Restaurar` vuelve al valor de referencia; `Deshacer` recupera los últimos 12 valores aplicados. |
| **Multiplicador (x)** | Tasa de los próximos cofres. Presets x1 / x1.5 / x2, o cualquier valor entre 0.01 y 1000. Acepta decimales. |
| **Cofres abiertos** | Fija tu total real. La diferencia se aplica al histórico x1. Reducir pide confirmación. |

Enter aplica en los tres campos. El aviso naranja te recuerda volver a x1 al
acabar el evento.

**Línea de comandos:**

```
--hold MS      ms mínimos de E para contar (def. 250)
--prob P       probabilidad base por cofre, 0..1
--mult X       multiplicador inicial
--chests N     fija el total de cofres al arrancar
--minimized    arranca oculto
--tray         icono en el área de notificación
--debug        log también por consola
--multi        permite varias instancias
```

## Datos

Todo en `%USERPROFILE%\FortniteChestTracker\`:

| Archivo | Contenido |
|---|---|
| `estado.json` | Total e histórico por multiplicador |
| `config.json` | Probabilidad base y multiplicador |
| `cofres.log` | Una línea por cofre abierto |
| `debug.log` | Diagnóstico (rotativo, 3 × 512 KB) |

## Ejecutar desde el código

```bat
git clone [URL-DEL-REPO].git
cd fortnite-chest-tracker
instalar_dependencias.bat
python fortnite_tracker.pyw --debug
```

Requiere Python 3.9+ y `pynput`, `customtkinter`, `Pillow`, `pystray`.

**Comprobar la lógica:** `python test_logic.py` (no abre la GUI ni toca tus datos).

## Compilar

```bat
build.bat
```

Borra el `.spec` antiguo, limpia `build/` y `dist/`, compila con PyInstaller y
genera el `.zip` de la release con su SHA256 en `release\`.

Si el `.exe` muestra código viejo, casi siempre es un `.spec` antiguo:
bórralo y recompila. Verifica que el título de la ventana diga la versión correcta.

**Regenerar el icono:** `python crear_icono.py` crea un `.ico` multiresolución
desde el PNG. Un PNG renombrado a `.ico` no funciona.

## Solución de problemas

**Deja de contar a los pocos minutos.** Era el bug crítico de v1.0, corregido en
v1.1: una excepción silenciosa mataba el listener de teclado mientras la ventana
seguía visible. Ahora hay un watchdog que lo reactiva solo. El indicador
`● CAPTURA ACTIVA` y el contador de reinicios del pie te dicen si ocurre.

**No cuenta con Fortnite en primer plano.** Ejecuta el tracker como
administrador: Windows no entrega eventos de teclado a procesos de integridad
menor cuando la ventana activa es de integridad mayor.

**El icono no se ve.** El `.exe` ya lo lleva embebido. Si ves el antiguo es
caché de Windows: `ie4uinit.exe -show`, o renombra el `.exe`.

**Cuenta cofres de más.** Pulsar E en otras aplicaciones también cuenta. Cierra
el tracker al terminar de jugar.

## Licencia

Uso gratuito y personal, **sin uso comercial y sin obras derivadas**, con
**atribución obligatoria**. Consulta [LICENSE](LICENSE) para los términos completos.

Creado por **Raúl Abreu Jorge** — https://github.com/rabreuj/fortnite-chest-tracker.git

## Aviso

Proyecto no afiliado a Epic Games. Fortnite y sus marcas pertenecen a Epic
Games, Inc. La herramienta es un contador pasivo de teclado y una calculadora de
probabilidades; no modifica ni interactúa con el juego.
