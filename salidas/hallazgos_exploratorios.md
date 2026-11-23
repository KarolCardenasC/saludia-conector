# Hallazgos exploratorios, fuera de los criterios C1–C5

> Prueba de aprendizaje con casos difíciles que NO son errores sembrados. No modifica las metas ni los criterios C1–C5 y no se usa para confirmar la hipótesis H2. Lo esperado de cada caso se definió antes de ejecutar.

Generado: 2026-11-22T18:55:42-05:00

## Variante A · configuración por defecto (igual que la fuente 2)

Mapeo: `exploratorio/mapeo_exploratorio_A.yaml` · ✓ coincide: 6 · ✗ no detecta: 4 · ◐ marca de más: 2 · ◐ normaliza distinto: 0

| Caso | Situación | Se esperaba | El sistema | Resultado | Detalle |
|---|---|---|---|---|---|
| EX-01 | CIE-10 en minúscula | aceptar | aceptado (RDA válido) | ✓ coincide | codigo_cie10 = J00X |
| EX-02 | CIE-10 con punto | aceptar | marcado con error | ◐ marca de más | cie10_inexistente: 'J45.9' no tiene el formato CIE-10 de SISPRO (letra + 3 caracteres, sin punto) y no está en el catálogo |
| EX-03 | CIE-10 de 3 caracteres | aceptar | marcado con error | ◐ marca de más | cie10_inexistente: 'I10' no tiene el formato CIE-10 de SISPRO (letra + 3 caracteres, sin punto) y no está en el catálogo |
| EX-04 | Espacios sobrantes | aceptar | aceptado (RDA válido) | ✓ coincide | numero_documento = 1045001004 |
| EX-05 | Fecha de atención futura | marcar | aceptado (RDA válido) | ✗ no detecta | — |
| EX-06 | Mismo paciente, otra atención | aceptar | aceptado (RDA válido) | ✓ coincide | numero_documento = 1045001001 |
| EX-07 | Id de atención repetido | marcar | marcado con error | ✓ coincide | id_duplicado: El id 'EX-01' ya apareció en la fila 2 |
| EX-08 | Mismo documento, otra persona | marcar | aceptado (RDA válido) | ✗ no detecta | — |
| EX-09 | Sexo en otro formato | marcar | marcado con error | ✓ coincide | valor_no_reconocido: 'F' no está en la tabla de equivalencias de sexo del mapeo |
| EX-10 | Tipo de documento incoherente con la edad | marcar | aceptado (RDA válido) | ✗ no detecta | — |
| EX-11 | Diagnóstico incoherente con el sexo | marcar | aceptado (RDA válido) | ✗ no detecta | — |
| EX-12 | Nacimiento posterior a la atención | marcar | marcado con error | ✓ coincide | fecha_incoherente: La fecha de nacimiento es posterior a la fecha de atención |

## Variante B · con las opciones cie10_quitar_punto y cie10_completar_x

Mapeo: `exploratorio/mapeo_exploratorio_B.yaml` · ✓ coincide: 8 · ✗ no detecta: 4 · ◐ marca de más: 0 · ◐ normaliza distinto: 0

| Caso | Situación | Se esperaba | El sistema | Resultado | Detalle |
|---|---|---|---|---|---|
| EX-01 | CIE-10 en minúscula | aceptar | aceptado (RDA válido) | ✓ coincide | codigo_cie10 = J00X |
| EX-02 | CIE-10 con punto | aceptar | aceptado (RDA válido) | ✓ coincide | codigo_cie10 = J459 |
| EX-03 | CIE-10 de 3 caracteres | aceptar | aceptado (RDA válido) | ✓ coincide | codigo_cie10 = I10X |
| EX-04 | Espacios sobrantes | aceptar | aceptado (RDA válido) | ✓ coincide | numero_documento = 1045001004 |
| EX-05 | Fecha de atención futura | marcar | aceptado (RDA válido) | ✗ no detecta | — |
| EX-06 | Mismo paciente, otra atención | aceptar | aceptado (RDA válido) | ✓ coincide | numero_documento = 1045001001 |
| EX-07 | Id de atención repetido | marcar | marcado con error | ✓ coincide | id_duplicado: El id 'EX-01' ya apareció en la fila 2 |
| EX-08 | Mismo documento, otra persona | marcar | aceptado (RDA válido) | ✗ no detecta | — |
| EX-09 | Sexo en otro formato | marcar | marcado con error | ✓ coincide | valor_no_reconocido: 'F' no está en la tabla de equivalencias de sexo del mapeo |
| EX-10 | Tipo de documento incoherente con la edad | marcar | aceptado (RDA válido) | ✗ no detecta | — |
| EX-11 | Diagnóstico incoherente con el sexo | marcar | aceptado (RDA válido) | ✗ no detecta | — |
| EX-12 | Nacimiento posterior a la atención | marcar | marcado con error | ✓ coincide | fecha_incoherente: La fecha de nacimiento es posterior a la fecha de atención |
