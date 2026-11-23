# Protocolo y registro de la prueba C5 (fuente 4)

**Criterio C5:** conectar una fuente nueva con columnas diferentes escribiendo solo un archivo YAML de mapeo, sin
modificar el código del conector ni el de la fuente.

## Origen de la fuente 4 (declaración)

- `fuente4_eps_export.csv`: 25 atenciones sintéticas generadas por una sesión de IA (Claude) **separada**, que no
  vio el código del prototipo, ni el esquema YAML, ni las fuentes 1 a 3. Solo se le pidió que fueran distintas en
  separador, codificación, nombres de columnas, formato de fecha y códigos.
- `esperado_fuente4.csv`: valores correctos ya normalizados, creados junto con el CSV. Se usa **solo para verificar
  al final**, nunca para escribir el YAML.
- **Quién escribió el YAML:** el asistente de IA del proyecto (Claude Opus 5.5), por decisión del equipo, con el
  código ya congelado y usando solo el CSV, `mapeos/_plantilla.yaml` y `docs/instrucciones_fuente4.md`.
- **Limitaciones:**
  - la fuente 4 la generó una IA del mismo proyecto, no una persona externa;
  - quien escribió el YAML conoce el esquema, así que el tiempo medido **no representa** el de una persona de la IPS;
  - el contenido de los archivos fue visible para el asistente desde que se subieron, unos segundos antes de `inicio`.

## Ajustes previos al experimento (antes de `inicio`)

1. **Corrección de codificación en el código** (versión 1.0.1). Al correr las pruebas en Windows apareció un error
   de codificación de la salida (cp1252 frente a UTF-8), y se corrigió **antes** de conocer la fuente 4. La
   congelación anterior (18:49:57) quedó anulada y se hizo una nueva.
2. **Corrección del vocabulario del esperado.** `esperado_fuente4.csv` traía el sexo como `male`/`female`, que son
   códigos FHIR, mientras que las instrucciones (sección 5) pedían `M`/`F`, el valor del modelo común. Por decisión
   del equipo, y **antes** de iniciar el cronómetro, se cambió solo esa columna (`male→M`, `female→F`). El archivo
   original se conserva como `datos/fuentes/esperado_fuente4_original.csv`, y ninguna otra celda cambió.
   - Comparación de control, fuera del cronómetro: con el esperado original habrían coincidido 0 de 25 filas, y la
     única diferencia es `MALE` frente a `M`. Con el esperado corregido coinciden 25 de 25.

## Pasos ejecutados

1. Congelar el código: `python scripts/c5_cronometro.py congelar`. Hecho el 22-nov-2026 a las 18:55:44, con 34
   archivos y huella global `0be6e1176b804e69…`.
2. Copiar `fuente4_eps_export.csv` a `datos/fuentes/`, sin cambios (SHA-256 `75a62079d3208a72…`, igual al archivo recibido).
3. `python scripts/c5_cronometro.py inicio` a las 19:00:26.
4. Escribir `mapeos/fuente4_eps.yaml` a partir de la plantilla.
5. `python scripts/c5_cronometro.py intento`.
6. `python scripts/c5_cronometro.py fin` a las 19:00:40.

## Registro

| Intento | Hora | Resultado | Qué falló / qué se corrigió en el YAML |
|---|---|---|---|
| 1 | 19:00:35 | ok: 25 registros, 25 válidos, 25 RDA válidos | Nada; funcionó en el primer intento |

- Hora de inicio: **19:00:26** · Hora de fin: **19:00:40** · Tiempo total: **13,5 s (0,2 min)**, según el reloj del sistema.
- Número de intentos: **1**.
- ¿Cambió el código? (lo verifica el script): **no**. Huellas iguales a la congelación.
- Filas procesadas: **25 / 25** · RDA válidos: **25 / 25** · Coinciden con lo esperado: **25 / 25**.
- La fuente quedó intacta (SHA-256 antes = después): **sí**.
- **Veredicto C5: Sí** (solo YAML y correcto).
- Qué no pudo expresar el esquema YAML: **nada en esta fuente**. Se necesitaron separador `|`, fechas `AAAAMMDD`,
  códigos propios de sexo (`HOMBRE`/`MUJER`) y de tipo de documento (`CED`, `TID`, `REG`, `PAS`), y todo estaba
  previsto en la plantilla.

## Cambios posteriores al experimento (después de `fin`)

Dos archivos de **pruebas** (`tests/test_fase3.py` y `tests/test_fase5.py`) suponían que `mapeos/` solo tenía los
YAML de las fuentes 1 a 3, así que se ajustaron. El conector, `main.py`, el cronómetro, `config/` y los YAML de las
fuentes 1 a 3 **no cambiaron**. La evidencia está en `salidas/c5_cambios_posteriores.json`.

## Evidencia

- `mapeos/fuente4_eps.yaml`: el YAML final (SHA-256 `0844b942dc1c7965…`).
- `salidas/c5.json`: veredicto, tiempos, verificaciones, historial de intentos y huellas.
- `salidas/c5_congelado.json`: huellas del código congelado.
- `salidas/c5_estado.json`: registro del cronómetro.
- `salidas/c5_cambios_posteriores.json`: qué cambió después de `fin` (solo pruebas).
- `datos/fuentes/esperado_fuente4.csv` y `esperado_fuente4_original.csv`.
