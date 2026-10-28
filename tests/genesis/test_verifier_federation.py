from lab.genesis.contracts.serialization import canonical_sha256
from lab.genesis.verifiers import *
def d(name,impl,kind=VerifierKind.EXACT_EXECUTABLE,sovereignty=VerifierSovereignty.SOVEREIGN):return VerifierDescriptor(name,"m6","1",kind,AuthorityClass.EXACT if kind is VerifierKind.EXACT_EXECUTABLE else AuthorityClass.HEURISTIC,sovereignty,("EXACT_FUNCTION",),("exact",),impl,canonical_sha256(name),"low",True)
def integrity(x):return VerifierIntegrityReceipt("i",x.descriptor_hash,x.implementation_identity_hash,x.implementation_identity_hash,x.dependency_manifest_hash,"p",IntegrityStatus.PASS,())
def req(n=1,ind=1,sovereign=True,cfi=False):return FederatedVerificationRequirement("r","o",(AuthorityClass.EXACT,),(VerifierKind.EXACT_EXECUTABLE,),n,ind,sovereign,cfi)
def test_same_implementation_is_dependent_and_no_false_independence():
 a,b=d("a","same"),d("b","same");g=VerifierDependencyGraph();g.add(a);g.add(b);assert g.independence(a,b) is IndependenceStatus.DEPENDENT;assert adjudicate(req(2,2),[(a,integrity(a),"PASS"),(b,integrity(b),"PASS")],g) is FederationVerdict.INCONCLUSIVE
def test_exact_fail_dominates_heuristic_and_conflict_not_voted():
 a,b=d("a","a"),d("b","b");g=VerifierDependencyGraph();g.add(a);g.add(b);assert adjudicate(req(),[(a,integrity(a),"FAIL"),(b,integrity(b),"PASS")],g) is FederationVerdict.CONFLICT
def test_non_sovereign_and_cfi_unknown_cannot_pass():
 h=d("h","h",VerifierKind.HEURISTIC,VerifierSovereignty.NON_SOVEREIGN);g=VerifierDependencyGraph();g.add(h);assert adjudicate(req(),[(h,integrity(h),"PASS")],g) is FederationVerdict.INCONCLUSIVE
 a=d("a","a");g=VerifierDependencyGraph();g.add(a);assert adjudicate(req(cfi=True),[(a,integrity(a),"PASS")],g,False) is FederationVerdict.INCONCLUSIVE
