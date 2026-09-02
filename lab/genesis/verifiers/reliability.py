from dataclasses import dataclass,field
from enum import Enum
from lab.genesis.contracts.serialization import canonical_sha256
class ReliabilityStatus(str,Enum):UNCHARACTERIZED="UNCHARACTERIZED";CHARACTERIZED="CHARACTERIZED";DEGRADED="DEGRADED"
@dataclass(frozen=True,slots=True)
class VerifierReliabilityProfile:
 profile_id:str;verifier_descriptor_hash:str;domain_id:str;truth_known_cases:int;correct_cases:int;incorrect_cases:int;unknown_cases:int;error_cases:int;mutation_cases:int;mutations_detected:int;replay_cases:int;replay_consistent:int;adversarial_cases:int;adversarial_detected:int;status:ReliabilityStatus;profile_hash:str=field(init=False)
 def __post_init__(self):object.__setattr__(self,"status",ReliabilityStatus(self.status));object.__setattr__(self,"profile_hash",canonical_sha256(self.canonical_payload()))
 def canonical_payload(self):return {k:(getattr(self,k).value if hasattr(getattr(self,k),'value') else getattr(self,k)) for k in self.__dataclass_fields__ if k!="profile_hash"}
