"""Huella SHA-256 de las fuentes, antes y después de la corrida.

Si la huella cambia, la fuente fue modificada: eso violaría la regla
de solo lectura y se reporta.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


def huellas(rutas: dict[str, Path]) -> dict[str, str]:
    return {k: sha256_archivo(Path(r)) for k, r in rutas.items()}
