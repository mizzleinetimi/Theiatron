"""Operator annotations and provisional crossing-event evaluation.

Coverage is self-declared, never inferred from opening a video. These reports
do not promote camera/network profiles to reviewed or validate traffic impact.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
import re

from .artifacts import fingerprint, load_artifact
from .io import atomic_json
from .provenance import file_hash
from .recount import counting_source

TOLERANCE_S = 0.5
LIMITATIONS = [
    'Operator-entered labels and self-declared coverage; not independently verified ground truth',
    'This is commissioning-set evaluation, not blinded or held-out validation',
    'Only the selected detectors and closed time interval are scored; unreviewed traffic is excluded',
    'Nominal source-video clock alignment is assumed; variable-frame-rate and boundary cases need inspection',
    'Matches require the same detector and timestamps within 0.5 seconds; each event can match only once',
    'Zero denominators are unavailable, not perfect precision or recall',
    'Counting accuracy is not metric-road, turning-demand, queue, controller or traffic-impact validation',
]


def review_source(root: Path, run_id: str) -> dict:
    source = counting_source(root, run_id)
    return {k: deepcopy(source[k]) for k in ('source_run', 'source_artifact_id', 'source_sha256',
                                            'duration', 'approaches')} | {
        'rois': {a['name']: a.get('roi') for a in source['config']['approaches']},
        'classes': source['config']['vision']['classes'],
        'tolerance_s': TOLERANCE_S,
        'review_kind': 'operator-annotations-provisional',
    }


def _directory(root: Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,120}', run_id):
        raise ValueError('invalid review source')
    base = root / 'out' / '.event-reviews'
    path = base / run_id
    if base.is_symlink() or path.is_symlink():
        raise ValueError('review symlinks are not allowed')
    return path


def load_review(root: Path, run_id: str, revision: str) -> dict:
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{64}', revision):
        raise ValueError('invalid review revision')
    path = _directory(root, run_id) / (revision + '.json')
    if path.is_symlink():
        raise ValueError('review symlinks are not allowed')
    review = json.loads(path.read_text())
    if review.pop('revision', None) != revision or fingerprint(review) != revision:
        raise ValueError('review checksum mismatch')
    if review['source']['source_run'] != run_id:
        raise ValueError('review source mismatch')
    return {**review, 'revision': revision}


def list_reviews(root: Path, run_id: str) -> list[dict]:
    directory = _directory(root, run_id)
    if not directory.exists():
        return []
    results = []
    for path in sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        review = load_review(root, run_id, path.stem)
        results.append({k: review[k] for k in ('revision', 'reviewer', 'status', 'window', 'approaches')})
    return results


def _match(detections: list[dict], labels: list[dict]) -> dict:
    """Maximum-cardinality ordered matching with a constant timestamp tolerance.

    Earliest-feasible pairing avoids nearest-neighbour stealing a later label.
    Sorted interval matching is linear after sorting. It does not claim minimum
    total timestamp error or vehicle-identity association.
    """
    detections = sorted(detections, key=lambda e: (e['t'], e['id']))
    labels = sorted(labels, key=lambda e: (e['t'], e['id']))
    pairs, extra, missed = [], [], []
    i = j = 0
    while i < len(detections) and j < len(labels):
        d, label = detections[i], labels[j]
        # Six-decimal source clocks; rounding avoids false exclusion at exactly 0.5s.
        delta = round(d['t'] - label['t'], 6)
        if delta < -TOLERANCE_S:
            extra.append(d); i += 1
        elif delta > TOLERANCE_S:
            missed.append(label); j += 1
        else:
            pairs.append({'detected': d, 'label': label, 'offset_s': delta})
            i += 1; j += 1
    extra.extend(detections[i:]); missed.extend(labels[j:])
    tp, fp, fn = len(pairs), len(extra), len(missed)
    return {'matched': tp, 'unmatched_detections': fp, 'unmatched_labels': fn,
            'detected_count': len(detections), 'labelled_count': len(labels),
            'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            'signed_count_error': fp - fn, 'absolute_count_error': abs(fp - fn),
            'pairs': pairs, 'extra': extra, 'missed': missed}


def evaluate(detections: list[dict], labels: list[dict], names: list[str], window: dict) -> dict:
    inside = lambda e: e['approach'] in names and window['start'] <= e['t'] <= window['end']
    selected = [e for e in detections if inside(e)]
    per_approach = {n: _match([e for e in selected if e['approach'] == n],
                              [e for e in labels if e['approach'] == n and inside(e)]) for n in names}
    totals = {key: sum(m[key] for m in per_approach.values()) for key in
              ('matched', 'unmatched_detections', 'unmatched_labels', 'detected_count', 'labelled_count')}
    tp, fp, fn = (totals[k] for k in ('matched', 'unmatched_detections', 'unmatched_labels'))
    totals.update(precision=tp / (tp + fp) if tp + fp else None,
                  recall=tp / (tp + fn) if tp + fn else None,
                  f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
                  sum_absolute_approach_count_error=sum(m['absolute_count_error'] for m in per_approach.values()))
    return {'totals': totals, 'per_approach': per_approach,
            'excluded_detection_count': len(detections) - len(selected),
            'method': 'same-approach earliest-feasible maximum-cardinality timestamp matching',
            'tolerance_s': TOLERANCE_S, 'window_boundary': 'both endpoints included'}


def save_review(root: Path, run_id: str, data: dict) -> dict:
    if not isinstance(data, dict) or set(data) != {'reviewer', 'window', 'approaches', 'labels',
                                                 'coverage_complete', 'notes', 'parent_revision'}:
        raise ValueError('review has unknown or missing fields')
    source = review_source(root, run_id)
    if not isinstance(data['reviewer'], str) or not 1 <= len(data['reviewer'].strip()) <= 80:
        raise ValueError('enter a reviewer name or identifier (1–80 characters)')
    if not isinstance(data['notes'], str) or len(data['notes']) > 2000:
        raise ValueError('review notes must be at most 2000 characters')
    number = lambda v: type(v) in {int, float} and math.isfinite(v)
    window = data['window']
    if not isinstance(window, dict) or set(window) != {'start', 'end'} or not all(number(v) for v in window.values()):
        raise ValueError('review window needs finite start/end seconds')
    if not 0 <= window['start'] < window['end'] <= source['duration'] or window['end'] - window['start'] < 5:
        raise ValueError('review at least 5 seconds within the recorded source window')
    names = data['approaches']
    source_names = [a['name'] for a in source['approaches']]
    if not isinstance(names, list) or not names or any(not isinstance(n, str) or n not in source_names for n in names) or len(names) != len(set(names)):
        raise ValueError('select unique detectors from this source')
    if type(data['coverage_complete']) is not bool:
        raise ValueError('coverage must be explicitly true or false')
    labels = data['labels']
    if not isinstance(labels, list) or len(labels) > 1000:
        raise ValueError('review supports at most 1000 marked crossings')
    ids = set()
    for e in labels:
        if not isinstance(e, dict) or set(e) != {'id', 'approach', 't', 'note'}:
            raise ValueError('crossing has unknown or missing fields')
        if not isinstance(e['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', e['id']) or e['id'] in ids:
            raise ValueError('crossing identifiers must be unique')
        ids.add(e['id'])
        if e['approach'] not in names or not number(e['t']) or not window['start'] <= e['t'] <= window['end']:
            raise ValueError('all labels must be inside the selected window and detectors')
        if not isinstance(e['note'], str) or len(e['note']) > 200:
            raise ValueError('crossing notes must be at most 200 characters')
    if data['parent_revision'] is not None:
        parent = load_review(root, run_id, data['parent_revision'])
        if parent['source']['source_artifact_id'] != source['source_artifact_id']:
            raise ValueError('parent review used a different source artifact')
    artifact = load_artifact(root / 'out' / run_id / 'simulation.json')
    events = [{'id': e['id'], 'approach': e['a'], 't': e['t0']}
              for e in artifact['scenarios']['theiatron']['vehicles']]
    review = {**deepcopy(data), 'source': source, 'schema_version': 1,
              'status': 'operator-labelled-provisional' if data['coverage_complete'] else 'draft-unscored',
              'simulation_impact_validated': False, 'limitations': LIMITATIONS,
              'detected_events': events,
              'metrics': evaluate(events, labels, names, window) if data['coverage_complete'] else None,
              'evaluator_sha256': file_hash(Path(__file__))}
    review['revision'] = fingerprint(review)
    path = _directory(root, run_id) / (review['revision'] + '.json')
    if path.is_symlink():
        raise ValueError('review symlinks are not allowed')
    if not path.exists():
        atomic_json(path, review)
    return review
