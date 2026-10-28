"""B10: LIFE_CHECKPOINT_KIND vive en un modulo neutral y rompe el ciclo conjunction<->life."""

from __future__ import annotations

import ast
from pathlib import Path

import runtime.conjunction.service as conjunction_service


def test_life_checkpoint_kind_importa_desde_modulo_neutral() -> None:
    from runtime.core.checkpoint_kinds import LIFE_CHECKPOINT_KIND

    assert LIFE_CHECKPOINT_KIND == "life_checkpoint"


def test_valor_consistente_via_reexport_de_life() -> None:
    from runtime.core.checkpoint_kinds import LIFE_CHECKPOINT_KIND as neutral_kind
    from runtime.life import LIFE_CHECKPOINT_KIND as life_kind
    from runtime.life.checkpoints import LIFE_CHECKPOINT_KIND as checkpoints_kind

    assert neutral_kind == life_kind == checkpoints_kind == "life_checkpoint"


def test_conjunction_no_importa_de_runtime_life() -> None:
    """Ningun modulo de runtime/conjunction debe importar runtime.life (ciclo B10)."""

    package_dir = Path(conjunction_service.__file__).resolve().parent
    offenders: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "runtime.life" or alias.name.startswith("runtime.life."):
                        offenders.append(f"{path.name}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "runtime.life" or module.startswith("runtime.life."):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"runtime.conjunction importa runtime.life en: {offenders}"
