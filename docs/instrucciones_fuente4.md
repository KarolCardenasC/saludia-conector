# Instrucciones para conectar la fuente 4 (prueba del criterio C5)

**Objetivo:** conectar una fuente nueva a SALUDIA **escribiendo solo un archivo YAML**,
sin modificar el código del conector ni el archivo de la fuente.

## 1. Campos del modelo común

| Campo | ¿Obligatorio? | Qué es |
|---|---|---|
| `id_atencion` | Sí | Identificador de la atención en el sistema de origen |
| `tipo_documento` | Sí | Tipo de documento del paciente |
| `numero_documento` | Sí | Número de documento del paciente |
| `sexo` | Sí | Sexo del paciente |
| `fecha_nacimiento` | Sí | Fecha de nacimiento |
| `fecha_atencion` | Sí | Fecha (y hora, si existe) de la atención |
| `codigo_cie10` | Sí | Diagnóstico principal en CIE-10 |
| `nombres`, `apellidos` | No | Nombres y apellidos en columnas separadas |
| `nombre_completo` | No | Nombre completo en una sola columna (en lugar de los dos anteriores) |
| `hora_atencion` | No | Hora de la atención, si viene en una columna aparte |

Valores estándar después de traducir: **sexo** `M`, `F`, `I`. **Tipo de documento**
`CC`, `TI`, `RC`, `CE`, `PA`, `PT`, `PE`, `CD`, `SC`, `CN`, `AS`, `MS`, `DE`, `SI`.

## 2. Cómo escribir el YAML

1. Copia `mapeos/_plantilla.yaml` como `mapeos/fuente4_csv.yaml` (cualquier nombre que no empiece por `_`).
2. Pon el archivo de la fuente 4 en `datos/fuentes/` y escribe su ruta en `fuente.ruta`.
3. Llena las secciones en orden: **fuente → lectura → columnas → formatos_fecha → equivalencias**.
   Los comentarios de la plantilla explican cada opción con ejemplos.
4. Escribe en `columnas` el nombre de cada columna **tal como aparece en el encabezado**.
   Las columnas que no menciones se ignoran solas.
5. En `equivalencias` anota **todos** los códigos de sexo y de tipo de documento que aparezcan en la fuente.
6. Guarda en UTF-8 y prueba con el cronómetro: `python scripts/c5_cronometro.py intento`.
   Si el YAML tiene un problema, el programa dice cuál y en qué línea o clave; corrige y vuelve a intentar.

## 3. Qué se puede y qué no se puede hacer

**Sí puedes:**
- Escribir y corregir tu YAML las veces que necesites (cada intento queda contado).
- Usar todas las opciones documentadas en la plantilla.
- Leer los mensajes de error del programa y guiarte por ellos.

**No puedes (si lo haces, C5 = "no"):**
- Modificar cualquier archivo `.py` del proyecto.
- Modificar los YAML de las fuentes 1 a 3 ni `config/`.
- Editar, convertir, renombrar columnas o "limpiar" el archivo de la fuente 4.
- Pedir que se agregue una opción nueva al esquema para que tu fuente pase.

**Si algo de tu fuente no se puede expresar con las opciones de la plantilla, no lo fuerces:
anótalo.** Es un hallazgo válido para la sección 6 (por ejemplo, "el esquema no permite X") y
el veredicto quedará en **parcial** o **no**, según lo que se haya logrado.

## 4. Qué cuenta como éxito

El programa da el veredicto **sí** cuando se cumplen las cuatro condiciones:
1. El código y los YAML de las fuentes 1 a 3 no cambiaron (se comparan huellas SHA-256).
2. Se procesaron todas las filas de la fuente 4.
3. Los RDA generados pasan la validación estructural.
4. Los valores normalizados coinciden con tu archivo `esperado_fuente4.csv`.

Anota el tiempo real con tu cronómetro y toma captura del YAML final.

## 5. Formato de `esperado_fuente4.csv`

Prepáralo **a mano, sin usar el conector**, y guárdalo en `datos/fuentes/esperado_fuente4.csv`
(UTF-8, separado por comas). Debe tener una fila por registro de la fuente 4 y estas columnas, con los
valores **ya en formato estándar**:

| Columna | Formato | Ejemplo |
|---|---|---|
| `id_atencion` | igual que en la fuente | `A-0001` |
| `tipo_documento` | código estándar | `CC` |
| `numero_documento` | igual que en la fuente | `1045678901` |
| `sexo` | `M`, `F` o `I` | `F` |
| `fecha_nacimiento` | `AAAA-MM-DD` | `1990-03-25` |
| `fecha_atencion` | `AAAA-MM-DD` o `AAAA-MM-DD HH:MM` si la fuente trae hora | `2026-05-14 09:30` |
| `codigo_cie10` | 4 caracteres, sin punto | `J00X` |
| `esperado_valido` | `si` o `no` (`no` si sembraste un error en esa fila) | `si` |
