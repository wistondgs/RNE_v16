# homeo_controller.py

import logging
import time
import numpy as np
import threading
from typing import Dict, Any, Callable, List
from dataclasses import dataclass, asdict

from runtime.control.homeostasis.thermodynamic_governor import ThermodynamicGovernor
from runtime.control.homeostasis.energy_sensors import EnergySensors
from contracts.types.aeon_types import HealthStatus
from runtime.memory.persistence import StatePreserver

logger = logging.getLogger("Homeostasis::Controller")
logger.setLevel(logging.INFO)

@dataclass
class AdaptiveThreshold:
    base_value: float
    learning_rate: float = 0.01
    current_value: float = None
    max_value: float = 1.0
    min_value: float = 0.1

    def __post_init__(self):
        self.current_value = self.base_value

    def update(self, stress_level: float):
        adjustment = self.learning_rate * (stress_level - 0.5)
        self.current_value = np.clip(
            self.current_value + adjustment,
            self.min_value,
            self.max_value
        )
        return self.current_value

@dataclass
class CognitivePolicy:
    name: str
    activation_condition: Callable[[HealthStatus], bool]
    actions: List[Callable]
    priority: int
    cooldown: float = 0.0
    last_activated: float = 0.0

class HomeoController:
    OPERATIONAL_MODES = ["high_performance", "normal", "conservative", "defensive", "emergency", "recovery"]

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.governor = ThermodynamicGovernor(config.get('thermodynamic', {}))
        self.sensors = EnergySensors(config.get('sensors', {}))
        self.preserver = StatePreserver(config.get('persistence', {}))

        self.mode = "normal"
        self.stress_index = 0.0
        self.operational_capacity = 1.0
        self.mode_history = []
        self.active_policies = []

        self.thresholds = {
            "thermal": AdaptiveThreshold(0.80),
            "energy": AdaptiveThreshold(0.85),
            "memory": AdaptiveThreshold(0.80),
            "vram": AdaptiveThreshold(0.90),
            "entropy": AdaptiveThreshold(0.75)
        }

        self.policies = self._initialize_policies()
        self.monitoring_active = True
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()

        logger.info("Homeostasis Controller initialized.")

    def _initialize_policies(self) -> List[CognitivePolicy]:
        return [
            CognitivePolicy(
                name="vram_emergency",
                activation_condition=lambda h: getattr(h, "vram_usage", 0.0) > self.thresholds["vram"].current_value,
                actions=[
                    lambda: self._activate_vram_pruning(0.4),
                    lambda: self._offload_non_essential(),
                    lambda: self._switch_mode("emergency")
                ],
                priority=0,
                cooldown=60.0
            ),
            CognitivePolicy(
                name="thermal_throttling",
                activation_condition=lambda h: h.temperature > self.thresholds["thermal"].current_value,
                actions=[
                    lambda: self.governor.activate_thermal_throttle(),
                    lambda: self._reduce_component_load("perception", 0.6),
                    lambda: self._reduce_component_load("inference", 0.7)
                ],
                priority=1,
                cooldown=30.0
            ),
            CognitivePolicy(
                name="energy_conservation",
                # B8: el HealthStatus canónico expone `power_consumption` (no `energy`);
                # mismo campo que ya usan update_stress_index y shutdown_logic.evaluate_crisis.
                activation_condition=lambda h: h.power_consumption > self.thresholds["energy"].current_value,
                actions=[
                    lambda: self._switch_mode("conservative"),
                    lambda: self._reduce_component_load("learning", 0.4),
                    lambda: self._optimize_memory_usage()
                ],
                priority=2,
                cooldown=60.0
            ),
            CognitivePolicy(
                name="chaotic_resurrection",
                # B8: el HealthStatus canónico expone `entropy_rate` (no `entropy`).
                activation_condition=lambda h: h.entropy_rate > self.thresholds["entropy"].current_value,
                actions=[
                    lambda: self._inject_chaotic_noise(0.2),
                    lambda: self._reconfigure_latent_space(),
                    lambda: self._switch_mode("recovery")
                ],
                priority=3,
                cooldown=300.0
            )
        ]

    def _monitoring_loop(self, interval: float = 0.5):
        while self.monitoring_active:
            try:
                health = self.evaluate_state()
                self.update_stress_index(health)
                self.adjust_thresholds()
                self.evaluate_policies(health)
                time.sleep(interval)
            except Exception as e:
                logger.error(f"[Homeostasis] Loop error: {e}")
                time.sleep(2)

    def evaluate_state(self) -> HealthStatus:
        health = self.governor.assess_health()
        metrics = self.sensors.system_snapshot()
        # HealthStatus canónico es frozen → reconstruir con los datos del sensor.
        from dataclasses import replace

        return replace(
            health,
            vram_usage=metrics.get("vram_usage", 0.0),
            thermal_gradient=self.governor.calculate_thermal_gradient(),
        )

    def update_stress_index(self, h: HealthStatus) -> float:
        f = [h.temperature*0.25, h.power_consumption*0.2, h.memory_load*0.15, h.vram_usage*0.3, h.entropy_rate*0.1]
        self.stress_index = min(1.0, sum(f))
        self.operational_capacity = 1.0 - (self.stress_index ** 1.8)
        return self.stress_index

    def adjust_thresholds(self):
        for key in self.thresholds:
            self.thresholds[key].update(self.stress_index)

    def evaluate_policies(self, health: HealthStatus):
        now = time.time()
        activated = []
        for policy in sorted(self.policies, key=lambda p: p.priority):
            if policy.activation_condition(health) and now - policy.last_activated > policy.cooldown:
                for action in policy.actions:
                    try:
                        action()
                    except Exception as e:
                        logger.error(f"Policy failed: {policy.name} – {e}")
                policy.last_activated = now
                activated.append(policy.name)
                logger.warning(f"⚠ Activada política: {policy.name}")
                if policy.priority == 0:
                    break
        self.active_policies = activated

    def _switch_mode(self, new_mode: str):
        if new_mode != self.mode and new_mode in self.OPERATIONAL_MODES:
            logger.info(f"🌀 Modo cambiado: {self.mode} → {new_mode}")
            self.mode = new_mode
            self.mode_history.append((time.time(), new_mode))

    def _activate_vram_pruning(self, aggressiveness: float):
        logger.warning(f"[VRAM] Poda crítica activada – nivel {aggressiveness}")

    def _reduce_component_load(self, component: str, factor: float):
        logger.info(f"[LOAD] Reducción de {component}: {int(factor*100)}%")

    def _optimize_memory_usage(self):
        logger.info("🧠 Optimizando uso de memoria y VRAM...")

    def _inject_chaotic_noise(self, intensity: float):
        logger.info(f"[Noise] Ruido caótico inyectado – intensidad {intensity}")

    def _reconfigure_latent_space(self):
        logger.info("[Latent] Reconfiguración del espacio latente ejecutada")

    def dynamic_ceiling(self) -> float:
        h = self.evaluate_state()
        # B8: campos canónicos de HealthStatus — `power_consumption` (no `energy`)
        # y `stability_index` (no `stability`).
        tf = 1.0 - h.temperature ** 2
        ef = 1.0 - h.power_consumption ** 1.5
        vf = 1.0 - h.vram_usage ** 2
        sf = h.stability_index
        return max(0.1, tf * ef * vf * sf)

    def system_snapshot(self) -> Dict[str, Any]:
        h = self.evaluate_state()
        metrics = self.sensors.system_snapshot()
        return {
            "timestamp": time.time(),
            "mode": self.mode,
            "stress": self.stress_index,
            "capacity": self.operational_capacity,
            "health": asdict(h),
            "metrics": metrics,
            "active_policies": self.active_policies,
            "thresholds": {k: t.current_value for k, t in self.thresholds.items()},
            "dynamic_ceiling": self.dynamic_ceiling()
        }

    def shutdown(self):
        self.monitoring_active = False
        self.monitor_thread.join(timeout=5)
        # `save_full_state` exige el proveedor de snapshot y aquí se llamaba sin
        # él: la llamada lanzaba TypeError en cada apagado, así que el enfriamiento
        # de abajo tampoco se ejecutaba y —lo que importa— los umbrales que el
        # organismo APRENDE (`AdaptiveThreshold.current_value`, ajustado por
        # estrés en cada ciclo de monitoreo) se perdían enteros en cada reinicio.
        # `system_snapshot` ya los expone; sólo faltaba pasárselo.
        try:
            self.preserver.save_full_state(self.system_snapshot)
        except Exception as exc:  # un apagado no debe morir por no poder guardar
            logger.warning("Homeostasis: no se pudo preservar el estado: %s", exc)
        self.governor.initiate_cooling(3.0)
        logger.info("🧊 Homeostasis apagada correctamente.")
