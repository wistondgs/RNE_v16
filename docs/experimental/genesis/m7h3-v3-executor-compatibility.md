# M7-H3A0-E2: matriz de compatibilidad del ejecutor V3

Esta matriz separa la procedencia histórica de una implementación de su
autoridad contractual. Un módulo llamado `v2_*` puede aportar un motor, pero
ningún payload V2 puede definir identidad, recuperación, attestation o cierre
de una campaña V3.

| Componente | Tipo actual | Identidad V2/H2 en payload | Reutilización V3 | Modo |
| --- | --- | --- | --- | --- |
| `RankCanonicalProgramSynthesizer` | motor de búsqueda | no; semántica `RANK_CANONICAL_BEHAVIOR_REPRESENTATIVE-v2` | sí | DIRECT |
| supervisor de `v2_execution.py` | ejecución/recursos | sí, en `V2ExecutionBinding` y receipts | sí, sólo tras binding/receipt V3 | GENERALIZE_VERSION_NEUTRAL |
| `DurableAuditClaimRegistry` | infraestructura one-shot | sí, depende de `AcquisitionCampaignManifest` y política histórica | sí, sólo tras slot/claim V3 | ADAPTER |
| CAS y serialización canónica | infraestructura | no | sí | DIRECT |
| kernel M5/M6 y replay de trazas | motor/evidencia compartida | depende del adaptador de campaña | sí, con raíces V3 | ADAPTER |
| composición | motor de medición | bindings V2 en el camino H2B1 | sí, con bindings V3 | ADAPTER |
| `V2ConfirmatoryCampaignManifest` | control plane H2B1 | sí | no | V3_REPLACEMENT |
| `V2ExecutionLaunch` | control plane H2B1 | sí | no | V3_REPLACEMENT |
| `execute_v2_confirmatory_campaign` | orquestación H2B1 | sí | no | V3_REPLACEMENT |
| `execute_v2_confirmatory_battery` | cierre/orquestación H2B1 | sí | no | V3_REPLACEMENT |
| `V2GEICampaignAttestation` | evidencia/control plane H2B1 | sí | no | V3_REPLACEMENT |
| `close_confirmatory_battery` con batería H2 | cierre H2 | sí | no | V3_REPLACEMENT |
| `V3ConfirmatoryCampaignManifest` | control plane V3 | V3 | sí | DIRECT |
| `V3CampaignAttestation` / `V3BatteryClosure` | evidencia/cierre V3 | V3 | sí | DIRECT |

## Regla de integración

El ejecutor V3 sólo puede invocar un componente `DIRECT` o un `ADAPTER` cuyo
payload de salida esté ligado a `predeclaration_hash`, `battery_manifest_hash`,
`campaign_hash`, `launch_hash`, fuente y entorno V3. Una llamada a las filas
`V3_REPLACEMENT` es una violación de control plane, incluso si después se
intenta envolver el resultado con un hash V3.
