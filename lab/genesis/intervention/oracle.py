from __future__ import annotations
from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.intervention.receipts import DecisionSeal,OracleReceipt
class SyntheticOracle:
 """Target stays private until OracleGate opens; candidates receive inputs only."""
 def __init__(self,oracle_spec_hash:str,evaluator_version="synthetic-v1"):self.oracle_spec_hash=oracle_spec_hash;self.evaluator_version=evaluator_version
 def evaluate(self,outputs,inputs):
  targets=[x+1 for x in inputs];score=sum(a==b for a,b in zip(outputs,targets))/len(targets);return score,canonical_sha256({"outputs":tuple(outputs),"targets":tuple(targets)})
class OracleGate:
 def __init__(self):self.opened=False
 def open(self,seal:DecisionSeal,oracle:SyntheticOracle,outputs,inputs):
  if self.opened or not seal.oracle_unopened or seal.seal_hash!=canonical_sha256(seal.canonical_payload()):raise ValueError("genesis_oracle_gate_rejected")
  if canonical_sha256(tuple(outputs))!=seal.candidate_output_hash:raise ValueError("genesis_candidate_after_seal_mutated")
  self.opened=True;score,outcome=oracle.evaluate(outputs,inputs)
  return OracleReceipt("oracle-"+seal.arm_id,"genesis.m5",seal.experiment_id,seal.arm_id,seal.seal_hash,oracle.oracle_spec_hash,oracle.evaluator_version,outcome,score,True)
