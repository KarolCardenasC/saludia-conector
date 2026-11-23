"""Salida de terminal con colores ANSI (solo biblioteca estándar).

- En Windows activa el soporte ANSI con os.system("").
- Se desactiva con --sin-color, con la variable NO_COLOR o si la salida
  no es una terminal (por ejemplo, al redirigir a un archivo).
- Usa los 16 colores básicos, que se leen bien con fondo claro y oscuro.
"""
from __future__ import annotations

import os
import re
import sys

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_CODIGOS = {
    "b": "1", "d": "2", "i": "3",
    "azul": "34", "verde": "32", "rojo": "31", "amarillo": "33",
    "magenta": "35", "cian": "36", "gris": "90",
}
ANCHO = 78


def preparar_salida() -> None:
    """Salida segura con caracteres especiales (✓, ·, ─) en cualquier sistema.

    - Si la salida va a una terminal, se respeta su codificación (en Windows la
      consola recibe Unicode directamente) y se reemplaza lo que no se pueda mostrar.
    - Si la salida va a un archivo o a otro programa (redirección o tubería), en
      Windows Python usaría la codificación antigua del sistema (cp1252); se fuerza
      UTF-8 para que ✓ y · no se pierdan ni rompan la lectura.
    """
    for flujo in (sys.stdout, sys.stderr):
        try:
            es_tty = flujo.isatty()
        except (AttributeError, ValueError):
            es_tty = False
        try:
            if es_tty:
                flujo.reconfigure(errors="replace")
            else:
                flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def largo_visible(texto: str) -> int:
    return len(_ANSI.sub("", texto))


class Consola:
    def __init__(self, color: bool | None = None, flujo=None):
        self.flujo = flujo or sys.stdout
        if color is None:
            es_tty = hasattr(self.flujo, "isatty") and self.flujo.isatty()
            color = es_tty and "NO_COLOR" not in os.environ
        self.color = color
        if self.color and os.name == "nt":
            os.system("")  # activa las secuencias ANSI en la consola de Windows

    # --- utilidades ---------------------------------------------------
    def c(self, texto, *estilos: str) -> str:
        texto = str(texto)
        if not self.color or not estilos:
            return texto
        cod = ";".join(_CODIGOS[e] for e in estilos)
        return f"\x1b[{cod}m{texto}\x1b[0m"

    def p(self, texto: str = "", fin: str = "\n") -> None:
        self.flujo.write(texto + fin)
        self.flujo.flush()

    def ok(self, texto="sí") -> str:
        return self.c(f"✓ {texto}", "verde", "b")

    def mal(self, texto="no") -> str:
        return self.c(f"✗ {texto}", "rojo", "b")

    def pendiente(self, texto="pendiente") -> str:
        return self.c(f"… {texto}", "amarillo", "b")

    def estado(self, valor: bool | None, si="sí", no="no", pend="pendiente") -> str:
        return {True: self.ok(si), False: self.mal(no), None: self.pendiente(pend)}[valor]

    # --- bloques ------------------------------------------------------
    def banner(self, titulo: str, subtitulo: str, leyenda: str) -> None:
        interior = ANCHO - 2
        borde = self.c("╭" + "─" * interior + "╮", "azul")
        self.p(borde)
        for texto, estilos in ((titulo, ("b", "azul")), (subtitulo, ()), (leyenda, ("magenta",))):
            relleno = interior - 2 - len(texto)
            self.p(self.c("│", "azul") + "  " + self.c(texto, *estilos) + " " * max(relleno, 0)
                   + self.c("│", "azul"))
        self.p(self.c("╰" + "─" * interior + "╯", "azul"))

    def seccion(self, titulo: str) -> None:
        self.p()
        self.p(self.c(f"▌ {titulo}", "b", "azul"))

    def dato(self, etiqueta: str, valor: str, ancho: int = 22) -> None:
        self.p(f"  {self.c(etiqueta.ljust(ancho), 'gris')} {valor}")

    def barra(self, etiqueta: str, i: int, n: int, ancho: int = 28, sufijo: str = "") -> None:
        llenos = int(ancho * i / n) if n else ancho
        barra = self.c("█" * llenos, "cian") + self.c("░" * (ancho - llenos), "gris")
        texto = f"  {etiqueta} {barra} {i:>3}/{n:<3} {sufijo}"
        if self.color:
            self.p("\r" + texto, fin="" if i < n else "\n")
        elif i == n:  # sin color/terminal: una sola línea final
            self.p(texto)

    def tabla(self, encabezados: list[str], filas: list[list[str]], alinear: str | None = None) -> None:
        alinear = alinear or "l" * len(encabezados)
        anchos = [max(largo_visible(str(x)) for x in col) for col in zip(encabezados, *filas)]

        def celda(t, j):
            falta = anchos[j] - largo_visible(t)
            return (" " * falta + t) if alinear[j] == "r" else (t + " " * falta)

        def linea(i, m, d):
            return self.c(i + m.join("─" * (a + 2) for a in anchos) + d, "gris")

        sep = self.c("│", "gris")
        self.p("  " + linea("┌", "┬", "┐"))
        self.p("  " + sep + sep.join(f" {self.c(celda(h, j), 'b')} " for j, h in enumerate(encabezados)) + sep)
        self.p("  " + linea("├", "┼", "┤"))
        for f in filas:
            self.p("  " + sep + sep.join(f" {celda(str(x), j)} " for j, x in enumerate(f)) + sep)
        self.p("  " + linea("└", "┴", "┘"))
