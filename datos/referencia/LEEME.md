# Catálogo CIE-10 de referencia

El validador usa el catálogo en este orden:

1. **`cie10_sispro.csv`**: la tabla de referencia CIE-10 oficial descargada de
   SISPRO (Ministerio de Salud y Protección Social). Si este archivo existe,
   se usa y tiene prioridad.
2. **`cie10_subconjunto.csv`**: si no está el oficial, se usa este archivo.

## Sobre `cie10_subconjunto.csv`

- Tiene **300 códigos** frecuentes en consulta externa, entre ellos los 16 que
  pidió el equipo (A099, E039, F419, G439, H109, I10X, J00X, J039, J459, K297,
  M255, M545, N390, N760, R104, R51X).
- Usa el **formato de códigos de SISPRO**: 4 caracteres sin punto. Las categorías
  sin subdivisión se completan con `X` (I10X, J00X, R51X).
- **Es un subconjunto transcrito, no la tabla oficial completa.** Los códigos y
  sus nombres se transcribieron para el prototipo y **deben contrastarse con la
  tabla de SISPRO** antes de presentarlos como oficiales.
- Las columnas (`Tabla;Codigo;Nombre;Habilitado`, separadas por `;`) son las
  mínimas que lee el cargador. La exportación oficial puede traer más columnas;
  el cargador solo necesita `Codigo` (y respeta `Habilitado` si viene).
