"""Prepare the governed eBay-derived capacity-test reference.

This adapter intentionally preserves the exact transformation used for the
published 5.905-million-row baseline.  The resulting catalogue is a throughput
fixture, not independently adjudicated ground truth.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .normalization import normalized_text
from .sources import prepare_reference


def _modal_row(group: pd.DataFrame) -> pd.Series:
    fields = ['Make', 'Model', 'Submodel', 'Variant', 'Plat_Gen', 'Engine', 'Body', 'Type']
    signatures = group[fields].fillna('').astype(str).agg('\x1f'.join, axis=1)
    signature = signatures.value_counts().index[0]
    return group.loc[signatures.eq(signature)].sort_values('Year').iloc[0]


def build_ebay_reference(path: Path | str, *,
                         sheet_name: str = 'AU_MVL_2026_07') -> tuple[pd.DataFrame, dict]:
    """Collapse year-expanded rows by kType and normalized make/model alias."""
    raw = pd.read_excel(path, sheet_name=sheet_name, dtype=object)
    raw['Year'] = pd.to_numeric(raw['Year'], errors='raise').astype(int)
    raw['Ktype'] = pd.to_numeric(raw['Ktype'], errors='raise').astype(int)
    raw['_make_alias'] = raw['Make'].map(normalized_text)
    raw['_model_alias'] = raw['Model'].map(normalized_text)

    records = []
    for candidate_id, ((_, _, _), group) in enumerate(
            raw.groupby(['Ktype', '_make_alias', '_model_alias'], sort=True), start=1):
        representative = _modal_row(group)
        engine, variant = str(representative['Engine']), str(representative['Variant'])
        engine_match = re.search(
            r'(?P<cc>\d+)cc\s+(?P<kw>\d+(?:\.\d+)?)kW\s+\((?P<fuel>[^()]*)\)\s*$',
            engine)
        drive_match = re.match(r'^(FWD|RWD|AWD)\b', variant)
        code_match = re.search(r'\d+(?:\.\d+)?kW(?:\s+(.+))?$', variant)
        cylinder_match = re.search(r'\b(\d+)cyl\b', variant)
        cc = int(engine_match.group('cc')) if engine_match else None
        kw = float(engine_match.group('kw')) if engine_match else None
        fuel = engine_match.group('fuel') if engine_match else None
        drive = {'FWD': 'Front-Wheel Drive', 'RWD': 'Rear-Wheel Drive',
                 'AWD': 'All-wheel Drive'}.get(
                     drive_match.group(1) if drive_match else '')
        engine_codes = code_match.group(1) if code_match and code_match.group(1) else ''
        engine_codes = '; '.join(part.strip() for part in engine_codes.split(',') if part.strip())
        first_year, last_year = int(group['Year'].min()), int(group['Year'].max())
        records.append({
            'KType': candidate_id,
            'Brand': representative['Make'],
            'Sales_designation': representative['Model'],
            'Model_generation': pd.NA,
            'Kind_of_structure': representative['Body'],
            'Structure_synonym': pd.NA,
            'Model_design': representative['Plat_Gen'],
            'Capacity_litre': (cc / 1000) if cc is not None else pd.NA,
            'Type_designation': representative['Type'],
            'Drive_system': drive,
            'Drive_system_synonym': pd.NA,
            # Plat_Gen is not asserted to be TecDoc Type_design. Keeping this
            # blank prevents manufacturer-code rules gaining false authority.
            'Type_design': pd.NA,
            'Capacity_cubic': cc,
            'Maximum_output_KW': kw,
            'Maximum_output_PS': pd.NA,
            'Cylinder': int(cylinder_match.group(1)) if cylinder_match else pd.NA,
            'Number_of_valves_per_cylinder': pd.NA,
            'Kind_of_engine': fuel,
            'Fuel_type': fuel,
            'Mixture_preperation': pd.NA,
            'Construction_from': first_year * 100 + 1,
            'Construction_to': last_year * 100 + 12,
            'Engine_code': engine_codes,
        })

    diagnostics = {
        'source_rows': int(len(raw)),
        'source_ktypes': int(raw['Ktype'].nunique()),
        'candidate_aliases': int(len(records)),
        'make_model_alias_ktypes': int(sum(
            raw.groupby('Ktype')[['_make_alias', '_model_alias']]
            .apply(lambda data: len(data.drop_duplicates()) > 1))),
    }
    return prepare_reference(pd.DataFrame(records)), diagnostics
