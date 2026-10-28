from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from competitive_intel.domain.analytical_writing import digest
from competitive_intel.services.saved_evidence_writing import StoredCandidateWriter


def test_editorial_replay_pins_source_and_packet_without_mutating_history():
    packet={'facts': 'fixed evidence'}
    candidate={'units': ['original']}
    audit={'origin':'model','candidate':candidate,'packet_hash':digest(packet)}
    row={'summary_json':json.dumps({'content_json':{'presentation':{'writing':{'analytical':audit}}}})}
    @contextmanager
    def transaction():
        yield None
    persistence=SimpleNamespace(transaction=transaction,reports=SimpleNamespace(get=lambda tx,rid:row))
    revision=dict(source_report_id=12,source_candidate_hash=digest(candidate),packet_hash=digest(packet),
                  reviewer='Independent evidence review',changes=[{'index':0,'reason':'Limit unsupported claim'}],payload={'units':['reviewed']})
    original=deepcopy(row)
    writer=StoredCandidateWriter(persistence,12,revision=revision)
    assert writer.write(packet)==revision['payload'] and writer.origin=='model_replay'
    assert row==original
    assert StoredCandidateWriter(persistence,12).write(packet)==candidate
    with pytest.raises(ValueError,match='REVIEWED_EVIDENCE_CHANGED'):
        writer.write({'facts':'changed'})
    for field in ['packet_hash','source_candidate_hash','source_report_id','reviewer','changes']:
        bad=deepcopy(revision);bad[field]=None
        with pytest.raises(ValueError,match='REVIEWED_REVISION_MISMATCH'):
            StoredCandidateWriter(persistence,12,revision=bad)
