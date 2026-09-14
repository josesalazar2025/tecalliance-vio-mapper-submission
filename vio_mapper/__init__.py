"""Evidence-based kType matching for the New Zealand vehicle register.

The public surface is deliberately small: load the two catalogues, map them
under a :class:`Policy`, and write the outputs.
"""
from .config import (ALGORITHM_VERSION, ALL_CANDIDATES_CONTRADICTED, AMBIGUOUS, CONFLICT,
                     INSUFFICIENT, MATCHED, NO_CANDIDATE_IN_REFERENCE, PROPOSED,
                     SOLE_CANDIDATE_INCOMPLETE, Policy)
from .pipeline import map_vehicles, map_vehicles_streaming
from .sources import load_source, prepare_reference, prepare_source

__all__ = ['ALGORITHM_VERSION', 'ALL_CANDIDATES_CONTRADICTED', 'AMBIGUOUS', 'CONFLICT',
           'INSUFFICIENT', 'MATCHED', 'NO_CANDIDATE_IN_REFERENCE',
           'SOLE_CANDIDATE_INCOMPLETE', 'PROPOSED', 'Policy', 'load_source', 'map_vehicles',
           'map_vehicles_streaming', 'prepare_reference', 'prepare_source']
