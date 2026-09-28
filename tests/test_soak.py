import hashlib
import json

import pytest

from scripts.soak_live import summarize
from theiatron.artifacts import fingerprint


def fixture():
    rows=[{'age_ms': 10, 'sequence': 1, 'source_epoch': 0, 'namespace': 'a'},
          {'age_ms': 400, 'sequence': 2, 'source_epoch': 1, 'namespace': 'b'}]
    trace='\n'.join(map(json.dumps,rows)).encode()
    report={'files': {'observations.jsonl': hashlib.sha256(trace).hexdigest()},
            'metrics': {'processed': 2, 'stale_rejected': 1},
            'buffer': {'offered': 5, 'taken': 3, 'overwritten': 1, 'pending': 1}}
    report['artifact_id']=fingerprint(report)
    return report,trace


def test_soak_checks_full_trace_and_preserves_bad_latency():
    report,trace=fixture()
    result=summarize(report,trace,[{'worker_rss_kib': 1024},{'worker_rss_kib': 2048}])
    assert result['trace_p95_ms']==400 and result['observations_over_300_ms']==1
    assert result['source_loops_observed']==1 and result['rss_max_mib']==2
    report['buffer']['offered']=99
    with pytest.raises(ValueError,match='checksum'): summarize(report,trace,[])


def test_soak_rejects_trace_tampering_and_missing_counts():
    report,trace=fixture()
    with pytest.raises(ValueError,match='trace checksum'): summarize(report,trace+b' ',[])
    report['metrics']['processed']=3
    report['artifact_id']=fingerprint({k:v for k,v in report.items() if k!='artifact_id'})
    with pytest.raises(ValueError,match='count'): summarize(report,trace,[])
