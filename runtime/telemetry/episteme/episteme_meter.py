"""Medidor epistémico. Honestidad de mediciones (B21).

Una cantidad NO medida jamás puede hacerse pasar por medida.

Antes, este módulo alimentaba la **detección de crisis homeostáticas**
(`runtime/control/homeostasis/life_monitor.py:145-146,209`) con valores
fabricados que el llamador no podía distinguir de mediciones reales:

- `evaluate()` fabricaba `np.random.uniform(...)` para `efficiency` y
  `fisher_info` cuando el contexto no los traía → **ruido presentado como
  medición**;
- `get_global_efficiency()` → `return 1.0` fijo → el organismo se veía con
  **eficiencia perfecta siempre** y no podía detectar una crisis de eficiencia;
- `get_accumulated_energy()` → `return 0.0` fijo → **energía acumulada nula
  siempre**;
- `_read_power()` caía a `psutil.cpu_percent() * 1.2` → un **porcentaje de CPU
  multiplicado por una constante mágica, presentado como vatios**;
- `apply_noise()` logueaba "ruido caótico aplicado" sin aplicar nada.

Contrato nuevo, explícito:

- **`None` significa NO MEDIDO.** Nunca se devuelve un número inventado ni una
  constante que simule una medición. `None` **no** significa "malo": significa
  que no hay evidencia, y ningún consumidor debe tratarlo como evidencia (ni de
  salud, ni de crisis).
- Los dicts de métricas llevan `"measured": bool` y, cuando corresponde,
  `"missing_inputs"`, para que el consumidor pueda distinguir sin adivinar.
- `get_global_efficiency()` / `get_accumulated_energy()` devuelven mediciones
  **reales** cuando el organismo efectivamente alimentó al medidor vía
  `update()`/`evaluate()`, y `None` cuando nunca lo hizo (que es el estado real
  hoy: ningún componente del runtime llama a `update()`).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("EpistemeMeter")

# Sentinela de "no medido". Se expone para que los consumidores puedan
# documentar/chequear la ausencia de medición sin comparar contra números.
UNMEASURED = None

# Insumos que `evaluate()` NO puede fabricar: o vienen del contexto, o no hay
# medición.
REQUIRED_EVALUATE_INPUTS = ("efficiency", "fisher_info")

# pynvml es opcional: sin él NO hay medición de potencia (y se dice, no se
# fabrica). `torch` estaba importado y jamás se usaba; `psutil` solo servía para
# el fallback fabricado `cpu_percent() * 1.2` — ambos fuera.
try:
    import pynvml
except ImportError:  # pragma: no cover - depende del entorno
    pynvml = None


def is_measured(value: Any) -> bool:
    """True si `value` es una medición real (no el sentinela de 'no medido')."""
    return value is not None


class EpistemeMeter:
    def __init__(self, tau_epist=30, epsilon=1e-9):
        self.tau_epist = tau_epist
        self.epsilon = epsilon
        self.ema_delta = None
        self.prev_efficiency = None
        # Energía = ∫ potencia dt, acumulada SOLO con muestras de potencia
        # realmente medidas. Si nunca hubo ninguna, queda None (no 0.0).
        self._accumulated_energy: Optional[float] = None
        self._last_power_ts: Optional[float] = None
        self._update_count = 0

        self._GPU_HANDLE = None
        if pynvml is not None:
            try:
                pynvml.nvmlInit()
                self._GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
            except Exception as exc:  # pragma: no cover - depende del hardware
                logger.warning(
                    "[Episteme] NVML no disponible (%s): la potencia queda NO MEDIDA", exc
                )
        else:
            logger.warning("[Episteme] pynvml ausente: la potencia queda NO MEDIDA")

    # ── Cálculos reales ──────────────────────────────────────────────────────

    def _mutual_information(self, posterior, prior):
        ratio = (posterior + self.epsilon) / (prior + self.epsilon)
        return float(np.mean(posterior * np.log(ratio)))

    def _read_power(self) -> Optional[float]:
        """Potencia instantánea en vatios, o None si NO es medible.

        B21: antes caía a `psutil.cpu_percent() * 1.2` — un porcentaje de CPU por
        una constante mágica NO es una medición de potencia. Si NVML no está,
        no hay medición: se devuelve None y se dice.
        """
        if self._GPU_HANDLE is None:
            return None
        try:
            return pynvml.nvmlDeviceGetPowerUsage(self._GPU_HANDLE) / 1000.0
        except Exception as exc:  # pragma: no cover - depende del hardware
            logger.warning("[Episteme] Lectura de potencia fallida (%s): NO MEDIDA", exc)
            return None

    def _accumulate_energy(self, power: Optional[float]) -> None:
        """Integra energía solo con potencia realmente medida."""
        now = time.time()
        if power is None:
            self._last_power_ts = now
            return
        if self._last_power_ts is not None:
            dt = max(0.0, now - self._last_power_ts)
            base = self._accumulated_energy or 0.0
            self._accumulated_energy = base + power * dt
        elif self._accumulated_energy is None:
            # Primera muestra: hay potencia medida pero todavía no hay intervalo.
            self._accumulated_energy = 0.0
        self._last_power_ts = now

    # ── API ──────────────────────────────────────────────────────────────────

    def update(self, current_efficiency, fisher_info, posterior=None, prior=None) -> Dict[str, Any]:
        """Actualiza el medidor con mediciones REALES provistas por el llamador.

        Todo lo que devuelve deriva de los argumentos o del hardware. Nada se
        fabrica. `power_estimate`/`mutual_info` pueden ser None (= no medidos).
        """
        if current_efficiency is None or fisher_info is None:
            raise ValueError(
                "EpistemeMeter.update() requiere mediciones reales de "
                "current_efficiency y fisher_info; no se fabrican entradas (B21)"
            )

        current_efficiency = float(current_efficiency)
        if self.prev_efficiency is None:
            delta = 0.0
        else:
            delta = current_efficiency - self.prev_efficiency
        self.prev_efficiency = current_efficiency

        alpha = 2 / (self.tau_epist + 1)
        self.ema_delta = delta if self.ema_delta is None else (1 - alpha) * self.ema_delta + alpha * delta

        fisher_density = float(np.sqrt(np.mean(np.square(fisher_info))))
        mutual_info = (
            self._mutual_information(posterior, prior)
            if posterior is not None and prior is not None
            else None
        )
        power = self._read_power()
        self._accumulate_energy(power)
        self._update_count += 1

        return {
            "measured": True,
            "delta_epist": delta,
            "ema_delta_epist": self.ema_delta,
            "fisher_density": fisher_density,
            "mutual_info": mutual_info,
            "power_estimate": power,  # None = potencia NO medida
            "efficiency": current_efficiency,
        }

    def evaluate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Evalúa el contexto. NUNCA fabrica insumos faltantes (B21).

        Antes: `context.get("efficiency", np.random.uniform(0.5, 1.0))` — si el
        contexto no traía el dato, se inventaba ruido y el llamador no podía
        distinguirlo de una medición.

        Ahora: si falta `efficiency` o `fisher_info`, es un **input faltante** y
        se devuelve un resultado explícito de NO MEDIDO (determinista, con las
        métricas en None y la lista de insumos que faltan). El estado interno del
        medidor NO se toca: un input ausente no puede corromper la EMA.
        """
        context = context or {}
        missing: List[str] = [
            key for key in REQUIRED_EVALUATE_INPUTS if context.get(key) is None
        ]
        if missing:
            logger.warning(
                "[Episteme] evaluate(): insumos faltantes %s -> resultado NO MEDIDO "
                "(no se fabrican entradas)",
                missing,
            )
            return self.unmeasured_result(missing)

        return self.update(
            context["efficiency"],
            context["fisher_info"],
            context.get("posterior"),
            context.get("prior"),
        )

    @staticmethod
    def unmeasured_result(missing_inputs: List[str]) -> Dict[str, Any]:
        """Resultado explícito de 'no medido'. Determinista: sin azar."""
        return {
            "measured": False,
            "missing_inputs": list(missing_inputs),
            "delta_epist": UNMEASURED,
            "ema_delta_epist": UNMEASURED,
            "fisher_density": UNMEASURED,
            "mutual_info": UNMEASURED,
            "power_estimate": UNMEASURED,
            "efficiency": UNMEASURED,
        }

    def get_global_efficiency(self) -> Optional[float]:
        """Última eficiencia REALMENTE observada, o None si nunca se midió.

        B21: antes devolvía `1.0` fijo (stub). El consumidor
        (`life_monitor._assess_crisis_level`) veía **eficiencia perfecta siempre**
        y por lo tanto no podía detectar jamás una crisis de eficiencia.

        None = NO MEDIDO. No es "malo" ni "0.0": es ausencia de evidencia, y
        ningún consumidor debe contarla como evidencia de salud.
        """
        if self.prev_efficiency is None:
            logger.debug(
                "[Episteme] get_global_efficiency(): NO MEDIDO "
                "(nadie alimentó update()/evaluate() con una eficiencia real)"
            )
            return UNMEASURED
        return float(self.prev_efficiency)

    def get_accumulated_energy(self) -> Optional[float]:
        """Energía acumulada (∫ potencia dt) sobre muestras REALES, o None.

        B21: antes devolvía `0.0` fijo (stub) — energía nula siempre. Solo
        acumula con potencia efectivamente medida (NVML); sin NVML no hay
        medición y devuelve None.
        """
        if self._accumulated_energy is None:
            logger.debug("[Episteme] get_accumulated_energy(): NO MEDIDO (sin muestras de potencia)")
            return UNMEASURED
        return float(self._accumulated_energy)

    def apply_noise(self, intensity: float):
        """NO IMPLEMENTADO (B21).

        Antes era un stub que logueaba "Ruido caótico aplicado con intensidad X"
        sin aplicar ningún ruido: aparentaba un efecto que no existía. Si alguien
        lo invoca esperando un efecto, tiene que enterarse.
        """
        raise NotImplementedError(
            f"EpistemeMeter.apply_noise(intensity={intensity!r}) no está implementado: "
            "era un stub que solo logueaba. No aplica ruido alguno (B21). "
            "Implementarlo o no llamarlo."
        )
