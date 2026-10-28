from __future__ import annotations
import random
from dataclasses import dataclass
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.causal.cfi import CFIReport,CFIStatus
from lab.genesis.causal.fork import RootSnapshot,SyntheticForkableStateAdapter
from lab.genesis.causal.isolation import AllowedDeltaReceipt,ArmIsolationReceipt
from lab.genesis.intervention.specs import *
from lab.genesis.intervention.oracle import OracleGate,SyntheticOracle
from lab.genesis.intervention.receipts import *
from lab.genesis.intervention.effects import summarize,CausalEffectSummary
@dataclass
class ArmContext:
 arm_spec:ArmSpec;root_snapshot:RootSnapshot;local_state:dict;rng:random.Random;budget:ComputeBudgetSpec;visible_context:dict;oracle_access_state:str="CLOSED"
@dataclass(frozen=True,slots=True)
class KernelResult:
 root:RootSnapshot;manifest:CausalExperimentManifest;receipts:tuple[ArmExecutionReceipt,...];cfi:CFIReport;summary:CausalEffectSummary;trace:ExecutionTrace;delta_receipts:tuple[AllowedDeltaReceipt,...];isolation_receipts:tuple[ArmIsolationReceipt,...];seals:tuple[DecisionSeal,...];oracles:tuple[OracleReceipt,...];budgets:tuple[BudgetReceipt,...]
class GenericInterventionKernel:
 def run(self,manifest,root,interventions,budget,adapter,oracle,arm_order=None,runtime=None):
  if root.root_hash!=manifest.root_snapshot_hash:raise ValueError("genesis_manifest_root_mismatch")
  adapter.seal_root(root); specs={x.arm_id:x for x in manifest.arm_specs}; order=tuple(arm_order or specs)
  if set(order)!=set(specs):raise ValueError("genesis_arm_order_invalid")
  by_spec={x.spec_hash:x for x in interventions}; results=[];deltas=[];isolations=[];seals=[];oracles=[];budgets=[];violations=[]
  unknown=tuple(x for x in manifest.required_surfaces if adapter.required_surfaces.get(x)=="UNKNOWN")
  root_before=adapter.fingerprint(root.state)
  for arm_id in order:
   arm=specs[arm_id]; state=adapter.fork(root,arm_id); pre=adapter.fingerprint(state); spec=by_spec[arm.intervention_spec_hash]
   # Trusted registry, never user-supplied executable code. An optional
   # declarative runtime still uses this M5 lifecycle for fork, isolation,
   # sealing, oracle access, budget and CFI; it does not create a second
   # intervention kernel.
   if runtime is None:
    if spec.intervention_type=="increment_operator":state["capabilities"]["operator"]="INCREMENT"
    elif spec.intervention_type=="placebo_marker":state["capabilities"]["placebo_marker"]=True
    elif spec.intervention_type!="none":raise ValueError("genesis_intervention_unregistered")
    inputs=tuple(root.state["inputs"]);op=state["capabilities"]["operator"];outputs=tuple(x+1 if op=="INCREMENT" else x for x in inputs)
   else:
    state=runtime.apply(state,spec)
    inputs=tuple(runtime.inputs(root,state))
    outputs=tuple(runtime.execute(state,inputs))
   observed=adapter.delta_paths(root,state); undeclared=tuple(x for x in observed if x not in arm.allowed_delta_paths); ds=AllowedDeltaReceipt(arm_id,root.root_hash,pre,arm.allowed_delta_paths,observed,undeclared,"FAIL" if undeclared else "PASS");deltas.append(ds)
   seal=DecisionSeal("seal-"+arm_id,"genesis.m5",manifest.experiment_id,arm_id,canonical_sha256(outputs),adapter.fingerprint(state),True,canonical_sha256({"inputs":inputs,"outputs":outputs}));seals.append(seal)
   gate=OracleGate(); oracle_receipt=gate.open(seal,oracle,outputs,inputs);oracles.append(oracle_receipt)
   root_after=adapter.fingerprint(root.state); shared=() if root_after==root_before else ("root_state",); iso=ArmIsolationReceipt(arm_id,root_before,root_after,pre,adapter.fingerprint(state),shared,"PASS" if not shared else "FAIL",canonical_sha256({"arm":arm_id}),"FAIL" if shared else "PASS");isolations.append(iso)
   br=BudgetReceipt(arm_id,budget.budget_hash,budget.logical_steps,1,1,0,"PASS" if arm.budget_spec_hash==budget.budget_hash else "FAIL");budgets.append(br)
   if undeclared:violations.append("undeclared_delta:"+arm_id)
   if shared:violations.append("root_drift:"+arm_id)
   if br.status!="PASS":violations.append("budget:"+arm_id)
   results.append((arm,pre,adapter.fingerprint(state),ds,iso,seal,oracle_receipt,br))
  status=CFIStatus.FAIL if violations else (CFIStatus.INCOMPLETE if unknown else CFIStatus.PASS)
  receipts=tuple(ArmExecutionReceipt(manifest.experiment_id,a.arm_id,a.arm_spec_hash,root.root_hash,d.receipt_hash,i.receipt_hash,s.seal_hash,o.receipt_hash,b.receipt_hash,pre,post,status,o.score) for a,pre,post,d,i,s,o,b in results)
  cfi=CFIReport(manifest.experiment_id,manifest.required_surfaces,unknown,tuple(violations),manifest.rng_policy.value,tuple(x.receipt_hash for x in receipts),status)
  return KernelResult(root,manifest,tuple(sorted(receipts,key=lambda x:x.arm_id)),cfi,summarize(manifest.experiment_id,receipts,cfi),ExecutionTrace(manifest.experiment_id,order),tuple(deltas),tuple(isolations),tuple(seals),tuple(oracles),tuple(budgets))
