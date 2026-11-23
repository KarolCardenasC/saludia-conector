"""Modelo común de atención (paso intermedio obligatorio antes de FHIR).

Todas las fuentes, sin importar su formato, se traducen primero a
`AtencionComun`. El motor FHIR solo conoce este modelo y nunca ve una
fuente directamente (decisión de diseño 2, sección 4.4 del informe).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


class ErrorConfiguracion(Exception):
    """Problema del archivo de mapeo o de acceso a la fuente (no de los datos).

    Se usa cuando la fuente no se puede conectar: YAML mal escrito,
    archivo inexistente, columna declarada que no existe, etc.
    """


# --- Campos del modelo común -----------------------------------------
CAMPOS_OBLIGATORIOS = (
    "id_atencion", "tipo_documento", "numero_documento", "sexo",
    "fecha_nacimiento", "fecha_atencion", "codigo_cie10",
)
CAMPOS_OPCIONALES = ("nombres", "apellidos", "nombre_completo", "hora_atencion")
CAMPOS_MODELO = CAMPOS_OBLIGATORIOS + CAMPOS_OPCIONALES

DESCRIPCION_CAMPOS = {
    "id_atencion": "Identificador de la atención en el sistema de origen",
    "tipo_documento": "Tipo de documento del paciente",
    "numero_documento": "Número de documento del paciente",
    "sexo": "Sexo del paciente",
    "fecha_nacimiento": "Fecha de nacimiento del paciente",
    "fecha_atencion": "Fecha (y hora, si existe) de la atención",
    "codigo_cie10": "Diagnóstico principal en CIE-10",
    "nombres": "Nombres del paciente",
    "apellidos": "Apellidos del paciente",
    "nombre_completo": "Nombre completo en una sola columna (si no vienen separados)",
    "hora_atencion": "Hora de la atención, si viene en una columna aparte",
}

# Valores estándar después de normalizar
SEXOS_VALIDOS = {"M": "Masculino", "F": "Femenino", "I": "Indeterminado / intersexual"}
TIPOS_DOCUMENTO_VALIDOS = {
    "CC": "Cédula de ciudadanía", "TI": "Tarjeta de identidad",
    "RC": "Registro civil", "CE": "Cédula de extranjería", "PA": "Pasaporte",
    "PT": "Permiso por protección temporal", "PE": "Permiso especial de permanencia",
    "CD": "Carné diplomático", "SC": "Salvoconducto", "CN": "Certificado de nacido vivo",
    "AS": "Adulto sin identificación", "MS": "Menor sin identificación",
    "DE": "Documento extranjero", "SI": "Sin identificación",
}

# --- Tipos de hallazgo (errores reportados) ---------------------------
CAMPO_VACIO = "campo_obligatorio_vacio"
FECHA_INVALIDA = "fecha_invalida"
CIE10_INEXISTENTE = "cie10_inexistente"
CIE10_NO_HABILITADO = "cie10_no_habilitado"
VALOR_NO_RECONOCIDO = "valor_no_reconocido"
FECHA_INCOHERENTE = "fecha_incoherente"
ID_DUPLICADO = "id_duplicado"
ERROR_LECTURA = "error_lectura"


@dataclass
class Hallazgo:
    """Un error encontrado en un registro. Se reporta; nunca se corrige."""
    campo: str
    tipo_error: str
    valor_encontrado: Any
    mensaje: str


@dataclass
class RegistroCrudo:
    """Una fila tal como la entrega el adaptador (columnas originales)."""
    fuente: str
    fila: int                      # fila como la vería una persona en el archivo
    datos: dict[str, Any]          # columna_original -> valor
    hallazgos: list[Hallazgo] = field(default_factory=list)


@dataclass
class AtencionComun:
    """Atención en el modelo común de SALUDIA."""
    fuente: str
    fila: int
    # valores tal como llegaron, ya renombrados a campos del modelo
    crudo: dict[str, Any] = field(default_factory=dict)
    # valores normalizados (None si faltan o no se pudieron interpretar)
    id_atencion: str | None = None
    tipo_documento: str | None = None
    numero_documento: str | None = None
    nombres: str | None = None
    apellidos: str | None = None
    nombre_completo: str | None = None
    sexo: str | None = None
    fecha_nacimiento: date | None = None
    fecha_atencion: datetime | date | None = None
    codigo_cie10: str | None = None
    hallazgos: list[Hallazgo] = field(default_factory=list)

    @property
    def valida(self) -> bool:
        return not self.hallazgos

    @property
    def etiqueta(self) -> str:
        """Identificador legible aunque falte el id."""
        return self.id_atencion or f"(sin id · fila {self.fila})"

    def agregar(self, campo: str, tipo: str, valor: Any, mensaje: str) -> None:
        self.hallazgos.append(Hallazgo(campo, tipo, valor, mensaje))
