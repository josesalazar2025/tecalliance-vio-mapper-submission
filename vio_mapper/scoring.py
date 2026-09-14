"""Uncalibrated candidate support scoring and ranking.

The score sums how much evidence supports a candidate, up to the group caps'
total -- config.attainable_score(), currently 75. It is not a probability and it
is not calibrated against measured accuracy.
Contradictions are vetoes handled elsewhere, never penalties subtracted here, so
a high score can never buy its way past a disagreement.
"""
from __future__ import annotations

import json

from .config import identifiers_where, score_rules

SCORE_COLUMNS = ('match_score', 'score_powertrain', 'score_configuration',
                 'score_identity', 'score_temporal', 'score_components_before_caps')


def score_candidate(evidence) -> dict:
    """Score one candidate, counting identity once however many fields repeat it."""
    rules = score_rules()
    weights, caps, members = rules['field_weights'], rules['group_caps'], rules['group_members']
    components = {field: weight if evidence[field] == 'agree' else 0
                  for field, weight in weights.items()}
    powertrain = min(caps['powertrain'], sum(components[f] for f in members['powertrain']))
    configuration = min(caps['configuration'], sum(components[f] for f in members['configuration']))
    identity = caps['identity'] if any(evidence[f'{field}_tokens']
                                       for field in identifiers_where('authoritative')) else 0
    temporal = evidence['temporal_points']
    return {'match_score': powertrain + configuration + identity + temporal,
            'score_powertrain': powertrain, 'score_configuration': configuration,
            'score_identity': identity, 'score_temporal': temporal,
            'score_components_before_caps': json.dumps(components, sort_keys=True)}


def rank_candidates(details, policy) -> tuple[dict, list[int]]:
    """Compare with all specification-compatible rivals, even weak/unknown ones.

    Ranking is diagnostic until the row-level conflict checks and evidence floor
    also pass. A sole candidate has no invented runner-up or infinite margin.
    """
    pool = [entry for entry in details if entry['compatible']]
    scores = sorted((entry['match_score'] for entry in pool), reverse=True)
    best = scores[0] if scores else None
    runner_up = scores[1] if len(scores) > 1 else None
    leaders = sorted(entry['KType'] for entry in pool if entry['match_score'] == best)
    margin = best - runner_up if runner_up is not None else None
    distinct_scores = sorted(set(scores), reverse=True)
    for entry in details:
        entry['score_rank'] = (distinct_scores.index(entry['match_score']) + 1
                               if entry['compatible'] else None)
        entry['score_band'] = ('rejected: specification conflict' if not entry['compatible'] else
                               'meets score threshold' if entry['match_score'] >= policy.accept_score else
                               'below score threshold')
    ranking = {'top_candidate_kTypes': '; '.join(map(str, leaders)),
               'top_match_score': best, 'runner_up_score': runner_up, 'score_margin': margin,
               'score_threshold_met': best is not None and best >= policy.accept_score,
               'score_margin_met': len(leaders) == 1 and (runner_up is None or margin >= policy.min_margin),
               'accept_score_threshold': policy.accept_score,
               'minimum_score_margin': policy.min_margin}
    return ranking, leaders
