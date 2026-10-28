# life_monitor.py (versión híbrida optimizada)
import time
import logging
from typing import Optional, Dict, Any, List, Tuple, Callable
from enum import Enum, auto
from collections import deque
from threading import Lock
from dataclasses import asdict
from runtime.control.homeostasis.shutdown_logic import PhasedShutdown, CrisisLevel
from runtime.memory.persistence import StatePreserver
from runtime.telemetry.episteme.episteme_meter import EpistemeMeter
from contracts.types.aeon_types import HealthStatus
from runtime.utils.resilience import ResilienceMechanism
from runtime.control.homeostasis.thermodynamic_governor import ThermodynamicGovernor

logger = logging.getLogger("LifeMonitor")
logger.setLevel(logging.INFO)

class RecoveryPhase(Enum):
    NONE = auto()
    COOLING = auto()
    STABILIZATION = auto()
    NORMALIZATION = auto()

class LifeMonitor:
    """
    Sistema de monitoreo vital con diagnóstico predictivo, recuperación post-crisis y manejo de VRAM.
    Combina funcionalidades avanzadas de `life_monitor3d.txt` y `shutdown_logic4d.txt`.
    """
    def __init__(self,
                shutdown_system: PhasedShutdown,
                episteme_meter: EpistemeMeter,
                governor: ThermodynamicGovernor,
                preserver: Optional[StatePreserver] = None,
                config: Optional[Dict[str, Any]] = None):
        self.shutdown = shutdown_system
        self.episteme_meter = episteme_meter
        self.preserver = preserver
        self.governor = governor
        self.config = config or {}
        
        # Parámetros configurables
        self.check_interval = self.config.get("check_interval", 5.0)
        self.energy_limit = self.config.get("energy_limit", 1.0)
        self.entropy_threshold = self.config.get("entropy_threshold", 0.98)
        self.thermal_gradient_threshold = self.config.get("thermal_gradient_threshold", 0.05)
        self.stability_threshold = self.config.get("stability_threshold", 0.7)
        self.max_crisis_history = self.config.get("max_crisis_history", 50)
        self.base_learning_rate = self.config.get("base_learning_rate", 0.001)
        
        # Historial de crisis con tamaño limitado
        self.crisis_history = deque(maxlen=self.max_crisis_history)
        self.recovery_phase = RecoveryPhase.NONE
        self.running = False

        # B21: vitales epistémicas NO MEDIDAS (el EpistemeMeter devuelve None).
        # Arranca declarando que todavía no se midió nada: el organismo no se
        # cree epistémicamente sano por defecto.
        self.unmeasured_vitals: List[str] = ["efficiency", "accumulated_energy"]
        self.epistemic_abstentions = 0
        self.resilience = ResilienceMechanism(self.config, self.preserver)
        self.lock = Lock()
        
        # Modelo predictivo de entropía
        self.entropy_predictor = self._init_entropy_predictor()
        
        # Validación de dependencias
        self._validate_dependencies()
        logger.info("[LifeMonitor] Inicializado con configuración avanzada")

    def _validate_dependencies(self):
        """Verifica que las dependencias críticas estén disponibles."""
        dependencies = {
            "shutdown_system": self.shutdown,
            "episteme_meter": self.episteme_meter,
            "governor": self.governor
        }
        missing = [name for name, obj in dependencies.items() if obj is None]
        if missing:
            logger.critical(f"[LifeMonitor] Falta dependencia crítica: {', '.join(missing)}")
            raise ImportError(f"Dependencias faltantes: {missing}")

    def _init_entropy_predictor(self) -> Callable[[float, float], float]:
        """Inicializa un modelo predictivo simple de entropía."""
        return lambda current, trend: min(1.0, current + (trend * 1.2))  # Predicción lineal

    def start(self):
        """Inicia el monitoreo vital con validación de estado inicial."""
        with self.lock:
            if self.running:
                logger.warning("[LifeMonitor] El monitoreo ya está activo")
                return
            self.running = True
            logger.info("[LifeMonitor] Iniciando monitoreo vital...")
        
        # Evaluar estado inicial
        initial_health = self._get_current_health()
        if self._initial_health_check(initial_health):
            # Iniciar bucle principal
            while self.running:
                sleep_time = self._get_adjusted_sleep_time()
                time.sleep(sleep_time)
                self._check_life_signs()
        else:
            logger.fatal("[LifeMonitor] Fallo en evaluación inicial, sistema no seguro para iniciar")
            self._emergency_shutdown()

    def stop(self):
        """Detiene el monitoreo y ejecuta protocolos de cierre seguro."""
        with self.lock:
            self.running = False
            logger.info("[LifeMonitor] Deteniendo monitoreo vital...")
            self._execute_closing_protocols()

    def _get_current_health(self) -> HealthStatus:
        """Obtiene el estado de salud actual del sistema."""
        return self.governor.assess_health()

    def _initial_health_check(self, health: HealthStatus) -> bool:
        """Verifica que el sistema esté en condiciones seguras para iniciar."""
        safe_start = True
        if health.temperature > 0.95:
            logger.critical("[LifeMonitor] Temperatura crítica en inicio")
            safe_start = False
        if health.vram_usage > 0.92:
            logger.warning("[LifeMonitor] Uso alto de VRAM en inicio")
            self._initiate_preemptive_pruning()
        if health.stability_index < self.stability_threshold:
            logger.warning(f"[LifeMonitor] Estabilidad crítica en inicio: {health.stability_index:.3f}")
            self._activate_defensive_mode()
        return safe_start

    def _initiate_preemptive_pruning(self):
        """Poda proactiva de memoria en condiciones iniciales de estrés."""
        logger.info("[LifeMonitor] Iniciando poda proactiva de VRAM")
        self.resilience.initiate_memory_pruning(aggressiveness=0.3)
        self.governor.reset_thermal_model()

    def _activate_defensive_mode(self):
        """Activa modo defensivo en condiciones iniciales inestables."""
        logger.info("[LifeMonitor] Activando modo defensivo")
        self.shutdown._switch_mode("defensive")

    def _check_life_signs(self):
        """Evalúa señales vitales con diagnóstico predictivo."""
        try:
            health = self._get_current_health()
            metrics = self.governor.get_thermal_metrics()

            # Evaluar eficiencia y energía acumulada.
            # B21: el EpistemeMeter puede devolver None = NO MEDIDO. `None` no es
            # 0.0 ni 1.0: es ausencia de evidencia. No se rellena con un número.
            efficiency = self.episteme_meter.get_global_efficiency()
            energy_accum = self.episteme_meter.get_accumulated_energy()
            self._record_epistemic_vitals(efficiency, energy_accum)

            # Evaluar crisis con múltiples dimensiones
            crisis_level = self._assess_crisis_level(health, metrics, efficiency, energy_accum)
            
            # Registrar crisis y tomar acción
            if crisis_level != CrisisLevel.NONE:
                self._handle_crisis(crisis_level, health)
            elif self.crisis_history:
                # Comprobar si necesitamos entrar en recuperación post-crisis
                last_crisis_time = self.crisis_history[-1]["timestamp"]
                if time.time() - last_crisis_time < 60:  # 1 minuto desde última crisis
                    self.recovery_phase = RecoveryPhase.COOLING
                    logger.info("[LifeMonitor] Entrando en fase de recuperación post-crisis")
        except Exception as e:
            logger.error(f"[LifeMonitor] Error en monitoreo: {str(e)}")
            self._emergency_shutdown()

    def _record_epistemic_vitals(self,
                                 efficiency: Optional[float],
                                 energy_accum: Optional[float]) -> None:
        """Deja VISIBLE si las vitales epistémicas fueron medidas o no (B21).

        No convierte la ausencia de medición en crisis (sería falso pánico) ni la
        oculta (sería creerse sano por defecto): la registra.
        """
        unmeasured = [
            name
            for name, value in (("efficiency", efficiency), ("accumulated_energy", energy_accum))
            if value is None
        ]
        self.unmeasured_vitals = unmeasured
        if unmeasured:
            self.epistemic_abstentions += 1
            logger.warning(
                "[LIFE] Vitales epistémicas NO MEDIDAS: %s -> el umbral de colapso "
                "epistémico se ABSTIENE (no hay evidencia; esto NO cuenta como salud)",
                ", ".join(unmeasured),
            )
        else:
            logger.debug(
                f"[LIFE] Eficiencia: {efficiency:.4f} | Energía: {energy_accum:.2f}"
            )

    def epistemic_vitals_measured(self) -> bool:
        """False si la última lectura de vitales epistémicas no fue una medición."""
        return not self.unmeasured_vitals

    def _assess_crisis_level(self,
                           health: HealthStatus,
                           metrics: Dict[str, float],
                           efficiency: Optional[float],
                           energy_accum: Optional[float]) -> CrisisLevel:
        """Evalúa nivel de crisis usando múltiples métricas y predicción de entropía.

        B21: `efficiency`/`energy_accum` pueden ser None (= NO MEDIDO por el
        EpistemeMeter). En ese caso el umbral de colapso epistémico **se abstiene**
        en vez de evaluarse contra un valor inventado. Antes el meter devolvía
        `1.0`/`0.0` fijos, así que la condición `efficiency <= 0.0` era
        **inalcanzable**: el organismo no podía detectar una crisis de eficiencia
        y se veía epistémicamente perfecto siempre.

        Abstenerse NO es declarar salud. La no-medición queda registrada en
        `unmeasured_vitals` y visible en `get_current_status()`.

        LETRA CHICA (no te creas que las otras dimensiones sí miden): entropía,
        gradiente térmico y estabilidad **tampoco** se evalúan hoy con datos reales.
        Vienen del `ThermodynamicGovernor`, que las **fabrica**:
        `get_thermal_metrics()` devuelve `thermal_gradient`/`entropy_trend` constantes
        en `0.0` (su propio log dice "valores simulados",
        `thermodynamic_governor.py:130-136`); `stability_index` está **hardcodeado en
        1.0** (`:110`); y `energy_consumption()` es `psutil.cpu_percent()/100 * tdp` con
        fallback `tdp * 0.65` (`:56-58`) — exactamente los **vatios fabricados** que B21
        mató en el medidor. Consecuencia: esas tres crisis son HOY tan **inalcanzables**
        como lo era la epistémica (umbrales 0.05 y 0.7, contra constantes 0.0 y 1.0).
        Arreglar el governor está FUERA del alcance de B21 → **backlog B79**.

        Lo único que esta abstención garantiza es que la dimensión epistémica **deja de
        mentir**. El resto del monitor sigue mintiendo, y ahora está dicho.
        """
        crisis_level = CrisisLevel.NONE

        # Crisis por eficiencia cognitiva (solo si HAY medición de ambas).
        if efficiency is None or energy_accum is None:
            logger.warning(
                "[LifeMonitor] Colapso epistémico NO EVALUADO: eficiencia/energía no medidas "
                "(abstención, no veredicto de salud)"
            )
        elif efficiency <= 0.0 and energy_accum >= self.energy_limit:
            logger.critical("[LifeMonitor] 🚨 Colapso epistémico detectado.")
            return CrisisLevel.CRITICAL


        # Crisis por entropía (actual y predicha)
        current_entropy = health.entropy_rate
        predicted_entropy = self.entropy_predictor(
            current_entropy, 
            metrics.get("entropy_trend", 0.0)
        )
        if current_entropy > self.entropy_threshold or predicted_entropy > self.entropy_threshold:
            logger.warning(f"[LifeMonitor] ⚠️ Entropía crítica: actual={current_entropy:.3f}, predicha={predicted_entropy:.3f}")
            if crisis_level.value < CrisisLevel.OPTIMIZATION.value:
                crisis_level = CrisisLevel.OPTIMIZATION
            
        # Crisis por gradiente térmico
        thermal_gradient = metrics.get("thermal_gradient", 0.0)
        if thermal_gradient > self.thermal_gradient_threshold:
            logger.warning(f"[LifeMonitor] 🔥 Gradiente térmico alto: {thermal_gradient:.3f}")
            if crisis_level.value < CrisisLevel.OPTIMIZATION.value:
                crisis_level = CrisisLevel.OPTIMIZATION
            
        # Crisis por estabilidad
        if health.stability_index < self.stability_threshold:
            logger.warning(f"[LifeMonitor] 📉 Estabilidad baja: {health.stability_index:.3f}")
            if crisis_level.value < CrisisLevel.OPTIMIZATION.value:
                crisis_level = CrisisLevel.OPTIMIZATION
            
        return crisis_level

    def _handle_crisis(self, level: CrisisLevel, health: HealthStatus):
        """Gestiona crisis con respuestas graduales y preservación de estado."""
        # B21: puede ser None (= NO MEDIDA). Se registra tal cual, con la bandera
        # que impide que un lector del historial la confunda con una medición.
        efficiency = self.episteme_meter.get_global_efficiency()
        crisis_record = {
            "timestamp": time.time(),
            "level": level.name,
            "efficiency": efficiency,
            "efficiency_measured": efficiency is not None,
            "health": asdict(health),
            "metrics": self.governor.get_thermal_metrics()
        }
        with self.lock:
            self.crisis_history.append(crisis_record)
        
        # Preservar estado antes de acciones críticas
        if self.preserver and level != CrisisLevel.NONE:
            try:
                # B8: save_critical_state acepta un único dict posicional (no un
                # keyword `metadata`) y devuelve bool; mismo ajuste que shutdown_logic.
                saved = self.preserver.save_critical_state({"crisis_level": level.name})
                if saved:
                    logger.info("[LifeMonitor] Estado crítico preservado (tag='critical')")
                else:
                    logger.error("[LifeMonitor] Falla en preservación: save_critical_state devolvió False")
                    if level.value < CrisisLevel.CRITICAL.value:
                        level = CrisisLevel.CRITICAL  # Escalar crisis si falla guardado
            except Exception as e:
                logger.error(f"[LifeMonitor] Falla en preservación: {str(e)}")
                if level.value < CrisisLevel.CRITICAL.value:
                    level = CrisisLevel.CRITICAL  # Escalar crisis si falla guardado
        
        # Ejecutar protocolo de crisis
        if level == CrisisLevel.CRITICAL:
            # Llamar a initiate_shutdown como espera el test
            self.shutdown.initiate_shutdown(
                level=level,
                preserver=self.preserver,
                health_snapshot=health
            )
            self._execute_safely(self._initiate_emergency_protocol, health)
        elif level == CrisisLevel.OPTIMIZATION:
            self._execute_safely(self._initiate_optimization_protocol, health)

    def _execute_safely(self, func: Callable, *args, **kwargs):
        """Ejecuta una función con manejo seguro de excepciones."""
        try:
            func(*args, **kwargs)
        except Exception as e:
            logger.error(f"[LifeMonitor] Error en ejecución segura: {str(e)}")
            self._emergency_shutdown()

    def _initiate_optimization_protocol(self, health: HealthStatus):
        """Protocolo de optimización proactiva."""
        logger.warning("[LifeMonitor] Iniciando optimización proactiva")
        # B8: `_phase_optimize` no existe en PhasedShutdown; la fase de optimización
        # son los protocolos reversibles de CrisisLevel.OPTIMIZATION (su ejecución
        # deja `executed=True`, que es lo que revierte rollback_shutdown(OPTIMIZATION)
        # en el protocolo de emergencia).
        self.shutdown._execute_protocols(CrisisLevel.OPTIMIZATION)
        self._adjust_learning_rate(health)
        self._compress_memory()
        logger.info("[LifeMonitor] Optimización completada")

    def _initiate_emergency_protocol(self, health: HealthStatus):
        """Protocolo de emergencia con reversión parcial."""
        logger.fatal("[LifeMonitor] Iniciando protocolo de emergencia")
        # Revertir acciones anteriores
        self.shutdown.rollback_shutdown(CrisisLevel.OPTIMIZATION)
        # Preservar estado final
        if self.preserver:
            try:
                self.preserver.save_full_state(lambda: {"emergency_shutdown": True})
                logger.info("[LifeMonitor] Estado de emergencia guardado")
            except Exception as e:
                logger.error(f"[LifeMonitor] Falla en guardado de emergencia: {str(e)}")
        # Ejecutar protocolo de emergencia
        # B8: _emergency_protocol exige el posicional `preserver` (acepta None);
        # omitirlo lanzaba TypeError silenciado por _execute_safely.
        self.shutdown._emergency_protocol(self.preserver)
        logger.info("[LifeMonitor] Sistema detenido por emergencia")

    def _adjust_learning_rate(self, health: HealthStatus):
        """Ajusta tasa de aprendizaje según estabilidad del sistema."""
        stability_factor = max(0.1, health.stability_index)  # Evitar valores cero
        new_lr = self.base_learning_rate * stability_factor
        logger.info(f"[LifeMonitor] Ajustando tasa de aprendizaje a {new_lr:.6f}")
        # Implementación real interactuaría con el sistema de aprendizaje

    def _compress_memory(self):
        """Comprime memoria para reducir uso de VRAM."""
        logger.info("[LifeMonitor] Comprimiendo memoria...")
        self.resilience.compress_memory(self._get_current_health())
        logger.info("[LifeMonitor] Compresión completada")

    def _emergency_shutdown(self):
        """Apagado de emergencia con notificación a subsistemas."""
        logger.fatal("[LifeMonitor] 🚨 Apagado de emergencia inmediato")
        self.shutdown._safe_power_down()
        self.shutdown._broadcast_emergency()
        self.running = False

    def _execute_closing_protocols(self):
        """Ejecuta protocolos de cierre seguro."""
        logger.info("[LifeMonitor] Ejecutando protocolos de cierre")
        self._compress_memory()
        self._save_final_state()
        self._initiate_cooling()

    def _save_final_state(self):
        """Guarda estado final antes del apagado."""
        if self.preserver:
            try:
                self.preserver.save_full_state(lambda: {"shutdown": True})
                logger.info("[LifeMonitor] Estado final preservado")
            except Exception as e:
                logger.error(f"[LifeMonitor] Falla en guardado final: {str(e)}")

    def _initiate_cooling(self):
        """Inicia enfriamiento post-crisis."""
        logger.info("[LifeMonitor] Iniciando enfriamiento post-crisis")
        self.governor.initiate_cooling(2.0)  # Intensidad de enfriamiento

    def _manage_recovery_phase(self, health: HealthStatus):
        """Maneja las fases de recuperación post-crisis."""
        if self.recovery_phase == RecoveryPhase.COOLING:
            logger.info("[LifeMonitor] Recuperación: Fase de enfriamiento")
            self.governor.initiate_cooling(1.0)
            # Comprobar si el enfriamiento es suficiente
            if health.temperature < 0.7:
                self.recovery_phase = RecoveryPhase.STABILIZATION
        elif self.recovery_phase == RecoveryPhase.STABILIZATION:
            logger.info("[LifeMonitor] Recuperación: Fase de estabilización")
            # Restaurar gradualmente la carga cognitiva
            self._restore_cognitive_load()
            if health.stability_index > 0.85:
                self.recovery_phase = RecoveryPhase.NORMALIZATION
        elif self.recovery_phase == RecoveryPhase.NORMALIZATION:
            logger.info("[LifeMonitor] Recuperación: Fase de normalización")
            # Volver a modo operativo normal
            self._deactivate_defensive_mode()
            self.recovery_phase = RecoveryPhase.NONE
            logger.info("[LifeMonitor] Recuperación completada")

    def _restore_cognitive_load(self):
        """Restaura gradualmente la carga cognitiva."""
        logger.info("[LifeMonitor] Restaurando carga cognitiva")
        # Implementación real interactuaría con neurogenesis.py

    def _deactivate_defensive_mode(self):
        """Desactiva el modo defensivo."""
        logger.info("[LifeMonitor] Desactivando modo defensivo")
        self.shutdown._switch_mode("normal")

    def manual_check(self):
        """Permite validación manual del estado vital (útil en pruebas)."""
        logger.info("[LifeMonitor] Ejecutando verificación manual")
        self._check_life_signs()

    def get_crisis_history(self) -> List[Dict]:
        """Retorna historial de crisis para análisis posterior."""
        with self.lock:
            return list(self.crisis_history)

    def clear_crisis_history(self):
        """Limpia historial de crisis."""
        with self.lock:
            self.crisis_history.clear()
            logger.info("[LifeMonitor] Historial de crisis limpiado")

    def get_current_status(self) -> Dict[str, Any]:
        """Retorna el estado actual del monitor.

        B21: expone qué vitales epistémicas NO están medidas. Ausencia de crisis
        no equivale a salud si el organismo no está midiendo.
        """
        return {
            "running": self.running,
            "recovery_phase": self.recovery_phase.name,
            "last_crisis": self.crisis_history[-1] if self.crisis_history else None,
            "check_interval": self.check_interval,
            "unmeasured_vitals": list(self.unmeasured_vitals),
            "epistemic_vitals_measured": self.epistemic_vitals_measured(),
            "epistemic_abstentions": self.epistemic_abstentions,
        }

    def _get_adjusted_sleep_time(self) -> float:
        """Ajusta el intervalo de monitoreo según el estado del sistema."""
        base_interval = self.check_interval
        if self.recovery_phase != RecoveryPhase.NONE:
            return max(1.0, base_interval * 0.5)  # Monitoreo más frecuente
        health = self._get_current_health()
        if health.stability_index < 0.8:
            logger.warning("[LifeMonitor] Estabilidad baja durante la recuperación")
            return max(0.5, base_interval * 0.3)
        return base_interval