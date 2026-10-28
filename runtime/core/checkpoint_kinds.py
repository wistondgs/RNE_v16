"""Constantes de tipos (kinds) de checkpoint compartidas entre paquetes.

Modulo neutral sin dependencias de runtime: permite que paquetes como
``runtime.life`` (productor de checkpoints) y ``runtime.conjunction``
(consumidor via storage) compartan la constante sin crear un ciclo de
imports entre ellos (B10).
"""

from __future__ import annotations

LIFE_CHECKPOINT_KIND = "life_checkpoint"

__all__ = ["LIFE_CHECKPOINT_KIND"]
