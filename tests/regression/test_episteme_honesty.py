"""B21: el EpistemeMeter deja de fabricar mediciones y el LifeMonitor deja de creerse sano.

Antes (`runtime/telemetry/episteme/episteme_meter.py`):

- `evaluate()` fabricaba `np.random.uniform(...)` para `efficiency`/`fisher_info`
  cuando faltaban en el contexto → **ruido presentado como medición**;
- `get_global_efficiency()` → `return 1.0` fijo;
- `get_accumulated_energy()` → `return 0.0` fijo;
- `_read_power()` caía a `psutil.cpu_percent() * 1.2` (un % de CPU por una
  constante, presentado como vatios);
- `apply_noise()` logueaba "ruido aplicado" sin aplicar nada.

Consumidor: `life_monitor._assess_crisis_level` (detección de crisis
homeostáticas). Con `efficiency=1.0` y `energy=0.0` constantes, la condición de
colapso epistémico (`efficiency <= 0.0 and energy >= energy_limit`) era
**inalcanzable**: el organismo se veía epistémicamente perfecto siempre.

Regla: una cantidad NO medida jamás puede hacerse pasar por medida.
`None` = NO MEDIDO ≠ malo. Abstenerse ≠ entrar en pánico.
"""

import ast
import importlib
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from runtime.telemetry.episteme.episteme_meter import UNMEASURED, EpistemeMeter, is_measured

_METER_SRC = Path("runtime/telemetry/episteme/episteme_meter.py")
_MONITOR_SRC = Path("runtime/control/homeostasis/life_monitor.py")


# ── 1. EpistemeMeter: nada fabricado ─────────────────────────────────────────


def test_no_hay_np_random_en_el_medidor():
    """Tripwire: ninguna llamada a np.random / random en el medidor."""
    tree = ast.parse(_METER_SRC.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("uniform"):
            offenders.append(node.lineno)
        if isinstance(node, ast.Attribute) and node.attr == "random":
            offenders.append(node.lineno)
    assert not offenders, f"el medidor volvió a fabricar entradas (líneas {offenders})"


def test_no_hay_potencia_fabricada_desde_cpu_percent():
    """`cpu_percent() * 1.2` NO es una medición de potencia."""
    source = _METER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "cpu_percent"
    ]
    assert not calls, f"potencia fabricada desde cpu_percent en líneas {calls}"


def test_evaluate_sin_datos_no_fabrica_un_numero():
    meter = EpistemeMeter()
    result = meter.evaluate({})

    assert result["measured"] is False
    assert sorted(result["missing_inputs"]) == ["efficiency", "fisher_info"]
    for key in ("efficiency", "fisher_density", "delta_epist", "ema_delta_epist",
                "mutual_info", "power_estimate"):
        assert result[key] is UNMEASURED, f"{key} debería ser NO MEDIDO, es {result[key]!r}"
        assert not is_measured(result[key])


def test_evaluate_sin_datos_es_determinista_no_aleatorio():
    """Antes: dos llamadas devolvían ruido distinto (np.random.uniform)."""
    meter = EpistemeMeter()
    first = meter.evaluate({})
    second = meter.evaluate({})
    assert first == second, "el resultado de 'no medido' varía al azar entre llamadas"


def test_evaluate_sin_datos_no_corrompe_el_estado_interno():
    """Un input ausente no puede contaminar la EMA ni la última eficiencia."""
    meter = EpistemeMeter()
    meter.evaluate({"efficiency": 0.8, "fisher_info": np.array([0.5, 0.5])})
    ema_before, prev_before = meter.ema_delta, meter.prev_efficiency

    meter.evaluate({})  # sin datos

    assert meter.ema_delta == ema_before
    assert meter.prev_efficiency == prev_before


def test_evaluate_con_datos_reales_mide():
    meter = EpistemeMeter()
    result = meter.evaluate({"efficiency": 0.42, "fisher_info": np.array([0.2, 0.3])})
    assert result["measured"] is True
    assert result["efficiency"] == pytest.approx(0.42)
    assert result["fisher_density"] == pytest.approx(float(np.sqrt(np.mean([0.04, 0.09]))))
    assert "missing_inputs" not in result


def test_update_rechaza_entradas_ausentes():
    meter = EpistemeMeter()
    with pytest.raises(ValueError, match="no se fabrican entradas"):
        meter.update(None, None)


# ── 2. get_global_efficiency / get_accumulated_energy: sin constantes mentirosas ──


def test_eficiencia_global_no_devuelve_el_1_0_mentiroso():
    meter = EpistemeMeter()
    efficiency = meter.get_global_efficiency()
    assert efficiency is UNMEASURED, f"eficiencia no medida se hace pasar por {efficiency!r}"
    assert efficiency != 1.0


def test_energia_acumulada_no_devuelve_el_0_0_mentiroso():
    meter = EpistemeMeter()
    energy = meter.get_accumulated_energy()
    assert energy is UNMEASURED, f"energía no medida se hace pasar por {energy!r}"
    assert energy != 0.0


def test_eficiencia_global_es_real_cuando_el_organismo_la_alimenta():
    """Si hay medición de verdad, se devuelve la medición de verdad."""
    meter = EpistemeMeter()
    meter.update(0.73, np.array([0.1, 0.2]))
    assert meter.get_global_efficiency() == pytest.approx(0.73)
    meter.update(0.31, np.array([0.1, 0.2]))
    assert meter.get_global_efficiency() == pytest.approx(0.31)


def test_apply_noise_no_aparenta_un_efecto_que_no_tiene():
    meter = EpistemeMeter()
    with pytest.raises(NotImplementedError, match="no aplica ruido|No aplica ruido"):
        meter.apply_noise(0.5)


# ── 3. LifeMonitor: abstención sin falso pánico ──────────────────────────────


@pytest.fixture(scope="module")
def life_monitor_mod():
    """Importa life_monitor stubbeando SOLO las deps ausentes del entorno.

    `thermodynamic_governor` importa psutil de forma dura; los stubs se usan
    únicamente para poder importar y se retiran en el teardown para no
    contaminar otros módulos de test.
    """
    injected = []
    for name in ("psutil", "torch", "pynvml"):
        if name in sys.modules:
            continue
        try:
            importlib.import_module(name)
        except ImportError:
            sys.modules[name] = ModuleType(name)
            injected.append(name)

    def _purge():
        for mod in [m for m in list(sys.modules) if m.startswith("runtime.control.homeostasis")]:
            del sys.modules[mod]

    _purge()
    module = importlib.import_module("runtime.control.homeostasis.life_monitor")
    yield module
    _purge()
    for name in injected:
        sys.modules.pop(name, None)


class _StubGovernor:
    def __init__(self, stability=1.0, entropy=0.1):
        self._stability = stability
        self._entropy = entropy

    def assess_health(self):
        from contracts.types.aeon_types import HealthStatus

        return HealthStatus(
            temperature=0.3,
            vram_usage=0.2,
            power_consumption=0.3,
            entropy_rate=self._entropy,
            stability_index=self._stability,
        )

    def get_thermal_metrics(self):
        return {"thermal_gradient": 0.0, "entropy_trend": 0.0}


class _StubShutdown:
    def __init__(self):
        self.initiated = []

    def initiate_shutdown(self, **kwargs):
        self.initiated.append(kwargs)

    def _execute_protocols(self, level):
        pass

    def rollback_shutdown(self, level):
        pass

    def _emergency_protocol(self, preserver):
        pass

    def _safe_power_down(self):
        pass

    def _broadcast_emergency(self):
        pass

    def _switch_mode(self, mode):
        pass


class _Meter:
    """Medidor con valores configurables (None = NO MEDIDO)."""

    def __init__(self, efficiency=None, energy=None):
        self._efficiency = efficiency
        self._energy = energy

    def get_global_efficiency(self):
        return self._efficiency

    def get_accumulated_energy(self):
        return self._energy


def _monitor(life_monitor_mod, meter, governor=None):
    return life_monitor_mod.LifeMonitor(
        _StubShutdown(), meter, governor or _StubGovernor(), preserver=None, config={}
    )


def test_life_monitor_arranca_sin_creerse_epistemicamente_sano(life_monitor_mod):
    monitor = _monitor(life_monitor_mod, _Meter())
    assert monitor.epistemic_vitals_measured() is False
    assert monitor.get_current_status()["epistemic_vitals_measured"] is False


def test_eficiencia_no_medida_no_concluye_sano_y_queda_visible(life_monitor_mod, caplog):
    """No cuenta como evidencia de salud, y se ve (log + telemetría)."""
    monitor = _monitor(life_monitor_mod, _Meter(efficiency=None, energy=None))

    with caplog.at_level("WARNING", logger="LifeMonitor"):
        monitor._check_life_signs()

    status = monitor.get_current_status()
    assert status["epistemic_vitals_measured"] is False
    assert status["unmeasured_vitals"] == ["efficiency", "accumulated_energy"]
    assert status["epistemic_abstentions"] == 1
    assert not monitor.epistemic_vitals_measured()

    text = caplog.text
    assert "NO MEDIDAS" in text or "NO EVALUADO" in text
    assert "ABSTIENE" in text or "abstención" in text


def test_eficiencia_no_medida_no_provoca_falso_panico(life_monitor_mod):
    """Abstenerse != inventar una crisis. Sin evidencia, no hay crisis."""
    CrisisLevel = life_monitor_mod.CrisisLevel
    monitor = _monitor(life_monitor_mod, _Meter(efficiency=None, energy=None))

    level = monitor._assess_crisis_level(
        monitor._get_current_health(),
        {"thermal_gradient": 0.0, "entropy_trend": 0.0},
        None,
        None,
    )
    assert level == CrisisLevel.NONE
    assert monitor.get_crisis_history() == []


def test_check_life_signs_con_no_medido_no_dispara_apagado_de_emergencia(life_monitor_mod):
    """El formateo `f"{None:.4f}"` reventaba y el except caía en _emergency_shutdown."""
    shutdown = _StubShutdown()
    monitor = life_monitor_mod.LifeMonitor(
        shutdown, _Meter(None, None), _StubGovernor(), preserver=None, config={}
    )
    monitor.running = True
    monitor._check_life_signs()

    assert monitor.running is True, "la no-medición degeneró en apagado de emergencia"
    assert shutdown.initiated == []


def test_la_crisis_epistemica_real_ahora_es_alcanzable(life_monitor_mod):
    """Antes era IMPOSIBLE: el meter devolvía 1.0/0.0 constantes."""
    CrisisLevel = life_monitor_mod.CrisisLevel
    monitor = _monitor(life_monitor_mod, _Meter(efficiency=0.0, energy=2.0))

    level = monitor._assess_crisis_level(
        monitor._get_current_health(),
        {"thermal_gradient": 0.0, "entropy_trend": 0.0},
        0.0,   # eficiencia medida y colapsada
        2.0,   # energía medida por encima de energy_limit (1.0)
    )
    assert level == CrisisLevel.CRITICAL


def test_la_abstencion_epistemica_no_ciega_las_otras_dimensiones(life_monitor_mod):
    """Sin eficiencia medida, las crisis medibles (estabilidad) se siguen detectando."""
    CrisisLevel = life_monitor_mod.CrisisLevel
    governor = _StubGovernor(stability=0.2)  # < stability_threshold (0.7)
    monitor = _monitor(life_monitor_mod, _Meter(None, None), governor=governor)

    level = monitor._assess_crisis_level(
        governor.assess_health(),
        {"thermal_gradient": 0.0, "entropy_trend": 0.0},
        None,
        None,
    )
    assert level == CrisisLevel.OPTIMIZATION


def test_el_historial_de_crisis_marca_la_eficiencia_no_medida(life_monitor_mod):
    CrisisLevel = life_monitor_mod.CrisisLevel
    monitor = _monitor(life_monitor_mod, _Meter(None, None))

    monitor._handle_crisis(CrisisLevel.OPTIMIZATION, monitor._get_current_health())

    record = monitor.get_crisis_history()[-1]
    assert record["efficiency"] is None
    assert record["efficiency_measured"] is False


def test_life_monitor_con_meter_real_queda_no_medido(life_monitor_mod):
    """Integración: EpistemeMeter real recién construido = NO MEDIDO, no 'sano'."""
    monitor = _monitor(life_monitor_mod, EpistemeMeter())
    monitor.running = True
    monitor._check_life_signs()

    assert monitor.get_current_status()["epistemic_vitals_measured"] is False
    assert monitor.get_crisis_history() == []   # sin falso pánico
    assert monitor.running is True


def test_life_monitor_no_formatea_none_como_float(life_monitor_mod):
    """Tripwire: el log de vitales no puede volver a asumir que hay número."""
    tree = ast.parse(_MONITOR_SRC.read_text(encoding="utf-8"))
    checks = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_assess_crisis_level"
    ]
    assert checks, "no existe _assess_crisis_level"
    # La guarda de abstención (comparación contra None) tiene que estar presente.
    source = _MONITOR_SRC.read_text(encoding="utf-8")
    assert "efficiency is None or energy_accum is None" in source
