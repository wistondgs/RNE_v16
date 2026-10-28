"""B8: accesos silenciados a atributos/métodos inexistentes en homeostasis.

Antes:
- `HomeoController` (control/homeostasis) accedía a `h.energy`, `h.entropy` y
  `h.stability`, que NO existen en el `HealthStatus` canónico (tiene
  `power_consumption`, `entropy_rate`, `stability_index`) → AttributeError en
  runtime, tragado por el `except` del loop de monitoreo (solo loggeaba).
- `LifeMonitor` llamaba `shutdown._phase_optimize()` (método inexistente en
  `PhasedShutdown`), `shutdown._emergency_protocol()` (omitía el posicional
  requerido `preserver`) y `preserver.save_critical_state(metadata=...)`
  (keyword inexistente) → AttributeError/TypeError tragados por
  `_execute_safely` / try-except locales.

Tras B8 los accesos quedan cableados a los nombres/firmas reales. Los checks
AST corren en cualquier entorno; los conductuales requieren la cadena de deps
de homeostasis (psutil/torch/pynvml) y se saltan con gracia si falta, como en
tests/regression/test_healthstatus_unification.py.
"""

import ast
import dataclasses
from pathlib import Path

import pytest

from contracts.types.aeon_types import HealthStatus

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOMEO_DIR = _REPO_ROOT / "runtime" / "control" / "homeostasis"


def _parse(name: str) -> ast.Module:
    return ast.parse((_HOMEO_DIR / name).read_text(encoding="utf-8"))


# --- checks estáticos (corren sin psutil/torch/pynvml) ---------------------


def test_canonical_health_expone_los_campos_cableados():
    fields = {f.name for f in dataclasses.fields(HealthStatus)}
    for name in ("power_consumption", "entropy_rate", "stability_index",
                 "temperature", "vram_usage"):
        assert name in fields, f"falta campo canónico: {name}"
    # Los nombres viejos NO existen: si reaparecen accesos, son bugs.
    for name in ("energy", "entropy", "stability"):
        assert name not in fields


def test_homeo_controller_sin_atributos_inexistentes():
    """Ningún acceso `.energy`/`.entropy`/`.stability` (no-canónicos) en homeo_controller."""
    tree = _parse("homeo_controller.py")
    offenders = [
        f"homeo_controller.py:{node.lineno}:.{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in ("energy", "entropy", "stability")
    ]
    assert not offenders, f"accesos a atributos no-canónicos: {offenders}"


def test_life_monitor_no_llama_phase_optimize():
    tree = _parse("life_monitor.py")
    offenders = [
        f"life_monitor.py:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "_phase_optimize"
    ]
    assert not offenders, f"llamadas a método inexistente _phase_optimize: {offenders}"


def test_life_monitor_emergency_protocol_pasa_preserver():
    """Toda llamada a `_emergency_protocol` en life_monitor pasa el posicional requerido."""
    tree = _parse("life_monitor.py")
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_emergency_protocol"
    ]
    assert calls, "se esperaba al menos una llamada a _emergency_protocol"
    for call in calls:
        assert len(call.args) == 1 and not call.keywords, (
            f"life_monitor.py:{call.lineno}: _emergency_protocol requiere "
            f"exactamente el posicional `preserver`"
        )


def test_life_monitor_save_critical_state_firma_real():
    """save_critical_state recibe un único dict posicional (sin keyword `metadata`)."""
    tree = _parse("life_monitor.py")
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "save_critical_state"
    ]
    assert calls, "se esperaba al menos una llamada a save_critical_state"
    for call in calls:
        assert len(call.args) == 1, (
            f"life_monitor.py:{call.lineno}: save_critical_state espera 1 posicional"
        )
        assert not any(kw.arg == "metadata" for kw in call.keywords), (
            f"life_monitor.py:{call.lineno}: keyword `metadata` no existe en la firma"
        )


# --- checks conductuales (requieren la cadena de deps de homeostasis) ------


def _canonical_health(**overrides) -> HealthStatus:
    return HealthStatus(**overrides)


def test_policies_evaluan_sobre_health_canonico():
    pytest.importorskip("psutil")

    from runtime.control.homeostasis.homeo_controller import AdaptiveThreshold, HomeoController

    controller = HomeoController.__new__(HomeoController)  # sin hilo ni sensores
    controller.thresholds = {
        key: AdaptiveThreshold(0.5)
        for key in ("thermal", "energy", "memory", "vram", "entropy")
    }
    policies = controller._initialize_policies()
    health = _canonical_health(
        power_consumption=0.9, entropy_rate=0.9, temperature=0.9,
        vram_usage=0.9, stability_index=0.4,
    )
    for policy in policies:
        # Antes: AttributeError (h.energy / h.entropy) tragado por el loop.
        assert bool(policy.activation_condition(health)) is True


def test_dynamic_ceiling_sobre_health_canonico():
    pytest.importorskip("psutil")

    from runtime.control.homeostasis.homeo_controller import HomeoController

    controller = HomeoController.__new__(HomeoController)
    health = _canonical_health(
        power_consumption=0.2, temperature=0.3, vram_usage=0.1, stability_index=0.9,
    )
    controller.evaluate_state = lambda: health
    ceiling = controller.dynamic_ceiling()
    assert 0.1 <= ceiling <= 1.0


def test_life_monitor_crisis_cableada():
    pytest.importorskip("psutil")
    pytest.importorskip("torch")
    pytest.importorskip("pynvml")

    from runtime.control.homeostasis.life_monitor import LifeMonitor
    from runtime.control.homeostasis.shutdown_logic import CrisisLevel, PhasedShutdown

    class RecordingShutdown(PhasedShutdown):
        def __init__(self):
            super().__init__(config={})
            self.emergency_preservers = []
            self.power_downs = 0

        def _emergency_protocol(self, preserver):
            self.emergency_preservers.append(preserver)

        def _safe_power_down(self):
            self.power_downs += 1

        def _broadcast_emergency(self):
            pass

    class StubGovernor:
        def assess_health(self):
            return _canonical_health(stability_index=1.0)

        def get_thermal_metrics(self):
            return {"thermal_gradient": 0.0, "entropy_trend": 0.0}

        def initiate_cooling(self, intensity):
            pass

        def reset_thermal_model(self):
            pass

    class StubMeter:
        def get_global_efficiency(self):
            return 0.5

        def get_accumulated_energy(self):
            return 0.0

    class RecordingPreserver:
        def __init__(self):
            self.critical = []
            self.full = []

        def save_critical_state(self, state):
            self.critical.append(state)
            return True

        def save_full_state(self, get_snapshot_func):
            self.full.append(get_snapshot_func())
            return True

    preserver = RecordingPreserver()
    shutdown = RecordingShutdown()
    monitor = LifeMonitor(shutdown, StubMeter(), StubGovernor(), preserver=preserver, config={})
    health = _canonical_health(stability_index=0.9)

    # OPTIMIZATION: preserva con la firma real y ejecuta los protocolos reales
    # de PhasedShutdown sin degenerar en apagado de emergencia.
    monitor._handle_crisis(CrisisLevel.OPTIMIZATION, health)
    assert preserver.critical == [{"crisis_level": "OPTIMIZATION"}]
    assert all(p.executed for p in shutdown.protocols[CrisisLevel.OPTIMIZATION])
    assert shutdown.power_downs == 0
    assert shutdown.emergency_preservers == []

    # Protocolo de emergencia: _emergency_protocol recibe el preserver requerido.
    monitor._initiate_emergency_protocol(health)
    assert shutdown.emergency_preservers == [preserver]
