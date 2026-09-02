from tests.genesis._m5_helpers import run
from lab.genesis.evidence.artifacts import ContentAddressedArtifactStore
from lab.genesis.intervention.replay import evidence_bundle,CausalExperimentReplay
def test_m5_artifacts_are_content_addressed_and_ledger_sealed(tmp_path):
 result,_=run();bundle=evidence_bundle(ContentAddressedArtifactStore(tmp_path),result);assert bundle.ledger_seal.event_count==len(bundle.artifact_hashes);assert not bundle.graph.verify() and bundle.ledger_seal.verify_against(bundle.events);assert CausalExperimentReplay.verify(result).status=="PASS"
