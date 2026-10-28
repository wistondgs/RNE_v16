# M7-H3A: preregistración materializada y recuperación V3

## Motivo

La auditoría H2B1-R0 clasificó la V2 como `RUNTIME_BOUND`: sus compromisos de
código y entorno eran parámetros del constructor y cambiaban la identidad de
la batería. La campaña V2 `m7h2-confirmatory-abs_affine-0` se conserva como
`TECHNICALLY_VALID_BUT_NONCONFIRMATORY`; no participa en ningún agregado V3.

## Límite H3A

H3A no ejecuta campañas canónicas ni abre AUDIT. Define el objeto que H3B debe
cargar, verificar y ejecutar. El launcher V3 no recibe hashes de código,
entorno, batería, frontera, política ni lista de campañas como parámetros.

## Dos congelamientos

`C_IMPL` contiene el contrato y sus validadores. `C_SEAL` sólo añade artefactos
concretos creados desde `C_IMPL`: manifiesto de fuente, manifiesto de entorno y
predeclaración. Los blobs ejecutables deben ser idénticos en ambos commits. En
lanzamiento, `C_SEAL` es exclusivamente un punto de autorización externo: el
loader exige el blob Git exacto de la predeclaración y prueba que `C_IMPL` es
su ancestro. Esto evita la autorreferencia sin introducir un parámetro
científico libre.

## Contratos nuevos

- `ExecutionSourceManifestV3` lista blobs Git de los imports locales realmente
  alcanzables desde los entrypoints. Antes de sellar debe incluir el ejecutor
  que H3B invocará, no sólo este loader; agregar lógica ejecutable después de
  `C_IMPL` invalida la batería y exige una V4.
- El cierre se versiona como `EXECUTION_SOURCE_CLOSURE-v1`: incluye
  inicializadores de paquetes, imports locales transitivos y dependencias
  dinámicas literales. Un import local dinámico con destino calculado es un
  blocker. Los testigos de importación de procesos padre/hijo sólo pueden
  confirmar que lo cargado es subconjunto del manifiesto; nunca pueden
  ampliarlo durante la ejecución.
- `EnvironmentManifestV3` usa Python, plataforma, paquetes y hashes de fuentes
  de dependencias; excluye rutas absolutas, PID, hostname y tiempo.
- `GEIConfirmatoryPredeclarationV3` fija una batería V3, seis IDs
  `m7h3-confirmatory-*`, el dominio H2 ya establecido y una exposición V2
  excluida.
- `V3RunLedger` y `RecoveryReceiptV3` formalizan recuperación sin seleccionar
  otro candidato, reabrir AUDIT o reintentar un resultado terminal.
- `V3ConfirmatoryCampaignManifest`, `V3CampaignAttestation` y
  `V3BatteryClosure` son contratos de autoridad V3. Pueden reutilizar motores
  de rango, supervisor, CAS, AUDIT, M5 y M6, pero nunca aceptan ni relabelan
  manifests, campañas, attestations o cierres V2.

## Política de recuperación

La misma fuente y el mismo entorno son obligatorios para los seis slots. Un
journal terminal se valida y se omite; un AUDIT durable se reutiliza, nunca se
evalúa otra vez. Si se modifica código ejecutable tras `C_IMPL`, la batería se
invalida y requiere una nueva versión.

## Estado

Este documento no declara un resultado GE-I. La autorización de ejecución sólo
existirá cuando el artefacto concreto sea sellado en `C_SEAL`.
