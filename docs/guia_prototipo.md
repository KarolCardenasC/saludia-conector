# Guía del prototipo SALUDIA · índice y párrafos

> Material de apoyo para el documento guía del equipo y para las secciones 5 y 6 del informe.
> Los párrafos están listos para copiar. **Los números de C1 a C5 deben tomarse de la corrida propia**
> (`salidas/metricas.json`), no de esta guía.

## Índice

1. Presentación del prototipo
2. Instalación y ejecución
3. Datos sintéticos y metas fijas *(fase 2)*
4. Lectura, mapeo YAML, normalización y validación *(fase 3)*
5. Construcción y validación del RDA en FHIR R4 *(fase 4)*
6. Métricas C1–C5 y cronómetro de C5 *(fase 5)*
7. Interfaz: terminal y dashboard *(fase 6)*
8. Prueba exploratoria con casos difíciles *(fase 7)*
9. Pruebas automáticas *(fase 7)*
10. Experimento C5 con la fuente 4
11. Video de respaldo y repositorio en GitHub *(pendiente)*
12. Lista de figuras

---

## 1. Presentación del prototipo

**Qué es:** un programa en Python que toma atenciones de tres fuentes con formatos distintos, las traduce a un
modelo común y las convierte en Resúmenes Digitales de Atención (RDA) en HL7 FHIR R4, midiendo los criterios C1 a C5.

**Alcance:** pasos 1 a 7 del diagrama (recuadro naranja). Quedan fuera la cola de reintento, el envío a la IHCE,
el cifrado, el panel de cumplimiento y Docker.

> Desarrollamos un prototipo funcional que implementa los siete pasos del flujo dentro del alcance definido en la
> sección 4: lectura de las fuentes, mapeo mediante archivos de configuración, modelo común de atención,
> normalización, validación de datos con el catálogo CIE-10, construcción del RDA como documento HL7 FHIR R4 y
> generación del reporte de errores con las métricas de los criterios de éxito. Por tratarse de un prototipo
> académico, trabaja únicamente con datos sintéticos, realiza una validación estructural contra FHIR R4 base y no
> implementa los componentes de envío a la IHCE, que quedan como fase posterior.

## 2. Instalación y ejecución

Comandos: `python -m venv .venv` → activar → `pip install -r requirements.txt` → `python main.py generar-datos`
→ `python main.py ejecutar` → abrir `salidas/dashboard.html`. Detalle en el README.

> El prototipo se instala con un entorno virtual de Python y un archivo de dependencias con versiones fijas, de
> modo que cualquier persona puede reproducirlo en Windows, macOS o Linux. Se ejecuta con tres comandos: uno que
> genera los datos sintéticos, uno que procesa las fuentes y produce los resultados, y uno que corre las pruebas
> automáticas. Lo probamos con Python 3.13 y 3.14.

## 3. Datos sintéticos y metas fijas · fase 2

**Qué se construyó:** la estructura del repositorio, el archivo de metas fijas (`config/metas.yaml`), un catálogo
CIE-10 de 300 códigos con formato SISPRO y el generador de 300 atenciones sintéticas con 30 errores sembrados.

**Cómo funciona:** un programa inventa 300 consultas médicas con nombres colombianos aleatorios, que siempre salen
iguales porque parten de una "semilla" fija. Las escribe en tres archivos que imitan tres sistemas distintos de una
IPS. A 30 de esas consultas les pone un error a propósito y anota en una lista aparte cuáles son. Al final se
revisa a sí mismo para confirmar que las otras 270 consultas no tienen ningún error.

> Como no tenemos acceso a un HIS real, construimos un conjunto de 300 atenciones sintéticas de consulta externa
> con la librería Faker (configuración regional es_CO) y una semilla fija, de modo que cualquier persona puede
> regenerar exactamente los mismos datos. Las distribuimos en tres fuentes que imitan los escenarios más comunes de
> una IPS pequeña: una base de datos SQLite con nombres de columna abreviados, un archivo CSV exportado desde un
> software antiguo y una hoja de Excel diligenciada a mano. Cada fuente usa nombres de columna, formatos de fecha y
> códigos de sexo y de tipo de documento distintos. En 30 registros (el 10 %) sembramos a propósito un error cada
> uno: 10 códigos CIE-10 inexistentes, 10 fechas imposibles o mal escritas y 10 campos obligatorios vacíos.
> Registramos cuáles son en una lista de verdad que el conector nunca lee y que solo usamos para medir el criterio
> C3. Antes de ejecutar cualquier prueba dejamos las metas de los cinco criterios en un archivo de configuración y
> guardamos su huella SHA-256, para demostrar que no las cambiamos después de ver los resultados.

## 4. Lectura, mapeo YAML, normalización y validación · fase 3

**Qué se construyó:** los adaptadores que leen las tres fuentes en solo lectura, el esquema y los mapeos YAML, el
modelo común, el normalizador, el validador con el catálogo CIE-10, la plantilla y las instrucciones para la fuente 4,
y el comando `revisar-mapeos`.

**Cómo funciona:** cada fuente tiene un archivo de configuración que funciona como un diccionario de traducción.
Indica dónde está el archivo, cómo se llama cada columna y qué significa cada código ("2" quiere decir femenino, por
ejemplo). El conector lee la fuente sin poder modificarla y traduce cada registro a un formato único. Después revisa
que no falten datos, que las fechas existan y que el diagnóstico esté en el catálogo CIE-10. Si algo está mal, lo
anota con la fila y el motivo, pero no lo borra ni intenta adivinar el valor correcto.

> El conector se apoya en un archivo de mapeo YAML por fuente, que describe dónde está el archivo, cómo se lee
> (separador, codificación, hoja o tabla, fila de encabezado), qué columna corresponde a cada campo del modelo común,
> en qué formato vienen las fechas y cómo se traducen los códigos propios de cada sistema. Por ejemplo, el sexo "1/2"
> del CSV y "Masculino/Femenino" del Excel terminan como "M/F". Los adaptadores abren las fuentes únicamente en modo
> de lectura: la base de datos SQLite con mode=ro y los archivos planos en modo binario de lectura. Lo verificamos
> con pruebas que intentan escribir y fallan, y comparando la huella SHA-256 de cada archivo antes y después de
> leerlo. Cada registro pasa primero a un modelo común propio y solo después se usa para construir el RDA. Al
> normalizar y validar, un dato que no se puede interpretar se marca con su fila, su campo y el motivo, pero nunca se
> descarta ni se corrige, porque esa decisión le corresponde al personal de la IPS.

## 5. Construcción y validación del RDA en FHIR R4 · fase 4

**Qué se construyó:** el motor FHIR, la validación estructural (R4 base + reglas de documento), el comando
`ejecutar` y las salidas: RDA en JSON, ejemplo de RDA, reporte de errores y resumen de la corrida.

**Cómo funciona:** cada consulta que pasó la revisión se convierte en un documento digital con el estándar HL7 FHIR.
El documento tiene cuatro piezas: portada (Composition), paciente (Patient), consulta (Encounter) y diagnóstico
(Condition). Antes de guardarlo, el programa lo revisa con una librería que conoce las reglas de FHIR R4 y con una
lista de verificación propia de lo que esa librería no revisa.

> Cada atención válida del modelo común se transforma en un Resumen Digital de Atención representado como un Bundle
> FHIR R4 de tipo document. El Bundle contiene cuatro recursos: una Composition (primer recurso, de tipo LOINC
> 34133-9), el Patient, el Encounter ambulatorio y el Condition con el diagnóstico en CIE-10. Todos se enlazan
> mediante identificadores urn:uuid que se resuelven dentro del mismo documento. La validación estructural tiene dos
> capas. Primero, el documento se interpreta con la librería fhir.resources 6.4.0, que corresponde a FHIR 4.0.1 (R4)
> y comprueba tipos de datos, campos obligatorios y formatos. Segundo, aplicamos reglas propias de documento. En
> nuestras pruebas encontramos que la librería, por sí sola, acepta códigos de estado inventados, fechas con hora pero
> sin zona horaria y referencias que no apuntan a ningún recurso; por eso agregamos verificaciones de esas reglas y
> de las invariantes de documento de R4 (identificador, marca de tiempo y Composition como primer recurso). Para
> comprobar que la validación no aprueba cualquier cosa, la sometimos a 15 documentos alterados a propósito y los
> rechazó todos. Aclaramos que se trata de una validación estructural contra FHIR R4 base y no de conformidad con la
> guía de implementación del RDA del Ministerio de Salud.

## 6. Métricas C1–C5 y cronómetro de C5 · fase 5

**Qué se construyó:** el módulo que calcula los cinco criterios, la tabla final en la terminal, `metricas.json` y el
cronómetro del experimento C5.

**Cómo funciona:** al final de cada corrida, el programa compara lo que logró con las metas escritas desde el
principio en un archivo que nadie toca. Cuenta los registros de cada fuente por un camino independiente, revisa
cuántos documentos FHIR quedaron válidos, compara los errores encontrados con la lista secreta de errores sembrados y
mide el tiempo de cada atención. El quinto criterio se mide aparte con un cronómetro que primero toma la huella del
código y al final verifica que no cambió.

> Para medir los criterios construimos un módulo de métricas que lee las metas directamente del archivo de
> configuración fijado antes de las pruebas y verifica, mediante su huella SHA-256, que no se modificó. C1 compara los
> registros extraídos con un conteo independiente de cada fuente, obtenido con COUNT(*) en SQLite y con lectores
> distintos a los del conector para CSV y Excel. C2 se calcula sobre las 270 atenciones sin errores sembrados. C3
> cruza el reporte del sistema con la lista de errores sembrados, que el validador nunca consulta, y reporta aparte
> los falsos positivos. C4 se mide con time.perf_counter() para cada atención, desde su extracción hasta que su RDA
> queda escrito. Para C5 desarrollamos un cronómetro que primero registra la huella del código y de la configuración.
> Luego mide el tiempo y el número de intentos hasta conectar la fuente nueva, y al final verifica que el código no
> cambió, que se procesaron todas las filas, que los RDA son válidos y que los datos normalizados coinciden con un
> resultado esperado preparado a mano. Sus veredictos son sí, parcial o no.

## 7. Interfaz: terminal y dashboard · fase 6

**Qué se construyó:** una terminal con colores y un tablero web autocontenido que funciona sin internet.

**Cómo funciona:** al terminar, el programa muestra un resumen con colores (verde cumplió, rojo no cumplió, amarillo
pendiente) y crea `dashboard.html`, que se abre con doble clic. La página se arma con los resultados reales de esa
corrida; si algo no se ha medido, dice "pendiente".

> Para comunicar los resultados, el prototipo genera dos salidas visuales a partir de los datos reales de cada
> ejecución. En la terminal muestra el progreso por fuente, un resumen de los siete pasos del flujo y una tabla con
> los criterios C1 a C5 frente a sus metas. Además produce un tablero en un único archivo HTML autocontenido, con los
> estilos, los gráficos SVG y la interacción incluidos en el mismo archivo, de modo que se abre sin conexión a
> internet y sin instalar nada adicional. El tablero presenta el recorrido del dato dentro del alcance del prototipo,
> los cinco criterios de éxito con su estado, la distribución de atenciones, errores y tiempos, una comparación entre
> el dato crudo de cada fuente y su versión normalizada, el reporte de errores con filtros y un ejemplo del RDA
> generado. Por diseño, el tablero muestra de forma visible la leyenda "Prototipo académico · datos sintéticos ·
> validación estructural FHIR R4", no afirma certificación ni conformidad con el Ministerio de Salud y marca como
> pendiente cualquier criterio que aún no se haya medido. Validamos la paleta de colores para personas con daltonismo
> y revisamos el tablero en computador, en celular, en modo oscuro y en versión impresa.

## 8. Prueba exploratoria con casos difíciles · fase 7

**Qué se construyó:** 12 casos difíciles que no son errores sembrados (`exploratorio/casos_dificiles.csv`), dos
variantes de mapeo (A por defecto; B con las opciones de CIE-10 activadas) y el comando `python main.py exploratorio`,
que deja el reporte en `salidas/hallazgos_exploratorios.md`.

**Cómo funciona:** antes de correr la prueba escribimos qué debería hacer el sistema en cada caso: aceptarlo y
normalizarlo, o marcarlo como error. Luego el programa procesa los casos y compara lo que hizo con lo esperado.
No cambia las metas ni entra en C1 a C5: es una prueba para aprender dónde están los límites del sistema.

**Resultado observado** (no depende del computador, porque no mide tiempos):

| Caso | Se esperaba | Variante A | Variante B |
|---|---|---|---|
| CIE-10 en minúscula (`j00x`) | aceptar | ✓ normaliza a J00X | ✓ |
| CIE-10 con punto (`J45.9`) | aceptar | ◐ lo marca como inexistente | ✓ normaliza a J459 |
| CIE-10 de 3 caracteres (`I10`) | aceptar | ◐ lo marca como inexistente | ✓ normaliza a I10X |
| Espacios sobrantes en el documento | aceptar | ✓ | ✓ |
| Fecha de atención futura (2031) | marcar | ✗ no lo detecta | ✗ |
| Mismo paciente, otra atención | aceptar | ✓ | ✓ |
| Id de atención repetido | marcar | ✓ id_duplicado | ✓ |
| Mismo documento, otra persona | marcar | ✗ no lo detecta | ✗ |
| Sexo en otro formato (`F` donde se usa 1/2) | marcar | ✓ valor_no_reconocido | ✓ |
| TI para una persona de 44 años | marcar | ✗ no lo detecta | ✗ |
| Vaginitis (N760) en un hombre | marcar | ✗ no lo detecta | ✗ |
| Nacimiento posterior a la atención | marcar | ✓ fecha_incoherente | ✓ |
| **Total** | | **6 ✓ · 4 ✗ · 2 ◐** | **8 ✓ · 4 ✗ · 0 ◐** |

> **Hallazgos exploratorios, fuera de los criterios C1–C5.** Además del experimento principal, sometimos el conector
> a 12 casos difíciles que no forman parte de los errores sembrados ni de los criterios de éxito, y definimos antes de
> ejecutar qué debía hacer el sistema en cada uno. Con la configuración por defecto, el sistema actuó como esperábamos
> en 6 casos: normalizó un código CIE-10 escrito en minúscula, eliminó espacios sobrantes, aceptó a un mismo paciente
> con dos atenciones y detectó un identificador de atención repetido, un código de sexo ajeno a la fuente y una fecha
> de nacimiento posterior a la atención. En 2 casos marcó como error códigos válidos escritos en otro formato (J45.9 e
> I10). Ambos se resolvieron activando dos opciones del archivo de mapeo, sin cambiar el código, lo que respalda el
> enfoque de configuración del criterio C5. En cambio, en 4 casos el sistema no detectó el problema: una fecha de
> atención en el futuro, un mismo número de documento asociado a otra persona, una tarjeta de identidad para un adulto
> y un diagnóstico incompatible con el sexo del paciente. Estos casos muestran que la validación actual es sintáctica
> y de catálogo, pero no revisa la coherencia clínica ni la identidad del paciente entre registros. Lo tomamos como
> aprendizaje y como trabajo futuro: agregar reglas de coherencia (fechas futuras, edad frente a tipo de documento) y
> restricciones de sexo y edad por diagnóstico, y verificar la identidad del paciente antes de enviar el RDA.

## 9. Pruebas automáticas · fase 7

**Qué se construyó:** pruebas `unittest` para cada regla de diseño, cada tipo de error, la estructura del Bundle, las
métricas, el cronómetro de C5, el dashboard y `main.py` de punta a punta. Todas pasan en Python 3.13 y 3.14.

**Cómo funciona:** son programas que revisan automáticamente que el conector cumpla lo que promete. Por ejemplo,
intentan escribir en la base de datos y comprueban que no pueden, o dañan un RDA a propósito y comprueban que la
validación lo rechaza.

> Acompañamos el prototipo con pruebas automáticas escritas con unittest, la biblioteca de pruebas estándar de Python.
> Hay al menos una prueba por cada regla de diseño de la sección 4.4: solo lectura de las fuentes, paso obligatorio
> por el modelo común, reporte de los errores sin borrarlos ni corregirlos, tolerancia a datos malos y uso del
> catálogo CIE-10 de SISPRO. A ellas se suman pruebas de cada tipo de error, de la estructura del RDA, de las métricas,
> del cronómetro de C5 y una ejecución completa del programa. También comprobamos que el validador nunca lee la lista
> de errores sembrados y que las métricas cambian cuando se simula un error no detectado, para evitar resultados que
> salgan bien por construcción.

## 10. Experimento C5 con la fuente 4

**Qué se hizo:** se congeló el código final, se conectó una fuente nueva (exportación de una EPS con 25 atenciones,
separador `|`, fechas `AAAAMMDD` y códigos propios) escribiendo solo `mapeos/fuente4_eps.yaml`, y el cronómetro
verificó el resultado. El registro completo está en `docs/protocolo_c5_registro.md`.

**Resultado** (de `salidas/c5.json`): veredicto **sí** · 13,5 s · 1 intento · 25/25 filas · 25/25 RDA válidos ·
25/25 iguales al esperado · código sin cambios.

> Para el criterio C5 conectamos una cuarta fuente, una exportación de una EPS con 25 atenciones sintéticas,
> generada por una sesión de IA independiente que no conocía el código ni el esquema de mapeo. Usaba otro separador,
> fechas en formato AAAAMMDD, nombres de columna propios y códigos distintos para el sexo y el tipo de documento.
> Antes de conocer la fuente congelamos el código registrando la huella SHA-256 de todos los archivos del conector y
> de la configuración. Luego escribimos un único archivo de mapeo YAML a partir de la plantilla, y el cronómetro
> verificó que el código no cambió, que se procesaron las 25 filas, que los 25 RDA eran estructuralmente válidos y
> que los datos normalizados coincidían con un resultado esperado preparado aparte. El veredicto fue positivo en el
> primer intento. Aclaramos que el archivo de mapeo lo redactó el asistente de IA del proyecto, por lo que el tiempo
> registrado (13,5 segundos) no representa el de una persona de la IPS. Además, antes de iniciar corregimos el
> vocabulario del archivo esperado, que traía el sexo como male/female en lugar de M/F, como pedían las
> instrucciones; esta corrección quedó documentada y el archivo original se conserva. Lo que el experimento sí
> demuestra es que la fuente nueva se conectó solo con configuración, sin modificar el código.

## 11. Video de respaldo y repositorio en GitHub · pendiente

Se completa en la guía práctica (fase 8).

## 12. Lista de figuras

| # | Figura | Fase |
|---|---|---|
| F2-1 | Terminal de `generar-datos` con la autoverificación OK | 2 |
| F2-2 | Las 7 pruebas del generador aprobadas | 2 |
| F2-3 | `config/metas.yaml` | 2 |
| F2-4 | Fuente 2 (CSV) en el Bloc de notas | 2 |
| F2-5 | Fuente 3 (Excel) con título y encabezado en la fila 4 | 2 |
| F2-6 | Fuente 1 (SQLite) en DB Browser *(opcional)* | 2 |
| F2-7 | `datos/errores_sembrados.csv` | 2 |
| F3-1 | Normalización de la fuente 2: dato crudo → modelo común | 3 |
| F3-2 | Lo mismo para las fuentes 1 y 3 | 3 |
| F3-3 | Errores por tipo en `revisar-mapeos` | 3 |
| F3-4 | `mapeos/fuente2_csv.yaml` | 3 |
| F3-5 | Prueba de solo lectura | 3 |
| F3-6 | Pruebas aprobadas | 3 |
| F4-1 | Terminal de `ejecutar` | 4 |
| F4-2 | `ejemplo_rda.json`: Bundle y Composition | 4 |
| F4-3 | `ejemplo_rda.json`: Patient, Encounter y Condition | 4 |
| F4-4 | `reporte_errores.csv` en Excel | 4 |
| F4-5 | Carpeta `salidas/rda/fuente1_sqlite` | 4 |
| F4-6 | Prueba de RDA alterados a propósito | 4 |
| F5-1 | Tabla final C1–C5 | 5 |
| F5-2 | `metricas.json`: bloque de metas sin cambios | 5 |
| F5-3 | `metricas.json`: bloque C3 | 5 |
| F5-4 | Pruebas de métricas y del cronómetro | 5 |
| F6-1 | Terminal completa de `ejecutar` (con colores) | 6 |
| F6-2 | Terminal con `--sin-color` *(opcional)* | 6 |
| F6-3 | Dashboard: encabezado y recorrido de 7 pasos | 6 |
| F6-4 | Dashboard: tarjetas KPI | 6 |
| F6-5 | Dashboard: gráficos con tooltip | 6 |
| F6-6 | Dashboard: pestaña de la fuente 2 | 6 |
| F6-7 | Dashboard: tabla de errores filtrada | 6 |
| F6-8 | Dashboard: RDA de ejemplo e integridad | 6 |
| F7-1 | Terminal de `exploratorio`, variante A | 7 |
| F7-2 | Terminal de `exploratorio`, variante B | 7 |
| F7-3 | `exploratorio/casos_dificiles.csv` (lo esperado, escrito antes) | 7 |
| F7-4 | `python -m unittest -v`, final con todas las pruebas OK | 7 |
| F7-5 | Página principal del repositorio en GitHub con el README | 8 |
| F7-6 | YAML de la fuente 4 y `fin` del cronómetro con el veredicto | C5 |
| F7-7 | Dashboard con la tarjeta C5 actualizada | C5 |
