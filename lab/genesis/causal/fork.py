"""Neutral forkable state primitives for Genesis causal experiments."""
from __future__ import annotations
import copy, json
from dataclasses import dataclass, field
from typing import Any, Mapping
from lab.genesis.contracts.serialization import canonical_json_bytes, canonical_sha256, freeze

@dataclass(frozen=True, slots=True)
class RootSnapshot:
    schema_version:str; state:Mapping[str,Any]; root_hash:str=field(init=False)
    def __post_init__(self): object.__setattr__(self,"state",freeze(self.state)); object.__setattr__(self,"root_hash",canonical_sha256(self.canonical_payload()))
    def canonical_payload(self): return {"schema_version":self.schema_version,"state":self.state}

class SyntheticForkableStateAdapter:
    """Trusted test adapter: every fork reconstructs detached JSON state."""
    def __init__(self, required_surfaces:Mapping[str,str]|None=None): self.required_surfaces=dict(required_surfaces or {}); self.trace=[]
    def capture_root(self,state:Mapping[str,Any])->RootSnapshot: self.trace.append("ROOT_CAPTURE"); return RootSnapshot("genesis.m5.root",state)
    def seal_root(self,root:RootSnapshot)->str: self.trace.append("ROOT_SEAL"); return root.root_hash
    def fork(self,root:RootSnapshot,arm_id:str)->dict[str,Any]: self.trace.append(f"ARM_{arm_id}_DERIVE"); return json.loads(canonical_json_bytes(root.state))
    def fingerprint(self,state:Mapping[str,Any])->str: return canonical_sha256(state)
    def delta_paths(self,root:RootSnapshot,arm:Mapping[str,Any])->tuple[str,...]:
        def flat(value:Any,prefix=""):
            if isinstance(value,Mapping):
                return {f"{prefix}.{k}".strip("."):v for k,x in value.items() for v in ([] if isinstance(x,Mapping) else [x])} | {k:v for k,x in value.items() if isinstance(x,Mapping) for k,v in flat(x,f"{prefix}.{k}".strip(".")).items()}
            return {prefix:value}
        a=json.loads(canonical_json_bytes(root.state)); b=json.loads(canonical_json_bytes(arm))
        return tuple(sorted(key for key in set(flat(a))|set(flat(b)) if flat(a).get(key)!=flat(b).get(key)))
