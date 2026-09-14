"""Conservative structural decoder for VINs encountered in New Zealand.

Source: https://www.nzta.govt.nz/vehicles/vehicle-registration/vin
NZTA's before/from 29 November 2009 diagrams define DIFFERENT layouts.
The factory truck/car diagrams are examples, not universal make/model tables.
This helper parses all syntactically supported VINs, but does not certify that
a VIN exists or infer a kType. Manufacturer-specific semantics need OEM data.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import vin_rules_path


SOURCE_URL = "https://www.nzta.govt.nz/vehicles/vehicle-registration/vin"


@dataclass(frozen=True)
class VinDecode:
    vin: str
    is_prefix: bool
    scheme: str
    status: str
    fields: dict[str, str | None] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    # Everything below is filled in by decode_nz_vin through replace(), never
    # positionally, and is keyword-only so that appending another decoded
    # attribute cannot shift the meaning of an existing argument.
    source_url: str = field(default=SOURCE_URL, kw_only=True)
    profile: str | None = field(default=None, kw_only=True)
    segments: tuple[dict[str, Any], ...] = field(default=(), kw_only=True)
    positions: tuple[dict[str, Any], ...] = field(default=(), kw_only=True)
    sources: dict[str, Any] = field(default_factory=dict, kw_only=True)


def _decode_structure(value: str, *, allow_prefix: bool = False) -> VinDecode:
    """Parse a 17-character VIN, or explicitly allow an 11-character prefix.

    Invalid syntax/layout raises ValueError; non-string inputs raise TypeError.
    A manufacturer VIN returns raw fields with status 'manufacturer_data_required'.
    'structure_decoded' means NZTA field boundaries were decoded, NOT that its
    make/model codes are all known or that the VIN is authentic.
    """
    if not isinstance(value, str):
        raise TypeError("VIN must be a string; preserve leading zeroes.")
    vin = value.strip().upper()
    if len(vin) != 17 and not (allow_prefix and len(vin) == 11):
        raise ValueError("Expected 17 characters (or 11 with allow_prefix=True).")
    # Do not silently delete punctuation/internal spaces or repair O to 0.
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]+", vin):
        raise ValueError("VIN must use ASCII letters/digits, excluding I, O and Q.")
    prefix = len(vin) == 11
    wmi = vin[:3]
    notes = ["Structural decoding does not establish authenticity or registration status."]
    if prefix:
        notes.append("VIN11 is incomplete and may be shared by multiple vehicles.")

    if wmi not in {"7A8", "7AT"}:
        # NZ registration does not imply an NZTA-issued VIN. Retain factory VINs
        # from every origin, including local manufacturers, without guessing a
        # manufacturer from a partial WMI list. Positions 4-9 and 10-17 are raw
        # descriptor/identifier sections; their internal meanings depend on OEM.
        # In particular: position 9 is NOT universally a check digit, position
        # 10 is NOT universally model year, and 11 is NOT universally a plant.
        # The Jaguar/Chevrolet examples must not be applied to Nissan/Mercedes
        # (or even other years/models from the same manufacturer) without data.
        return VinDecode(
            vin, prefix, "manufacturer", "manufacturer_data_required",
            {"wmi": wmi, "vehicle_descriptor_section": vin[3:9],
             "vehicle_identifier_section": None if prefix else vin[9:17],
             "vehicle_identifier_section_prefix": vin[9:11] if prefix else None},
            tuple(notes + ["OEM decode information is required for make, model, year, engine and plant."]),
        )

    # These slices use zero-based, end-exclusive indexes; comments use the
    # ONE-based positions printed in NZTA's diagrams. An 11-character prefix
    # preserves those positions: truncating the suffix never shifts a field.
    if wmi == "7A8":
        scheme = "nzta_before_2009_11_29"
        make_code, model_code = vin[3:5], vin[5:7]  # 4-5, 6-7
        vehicle_type_code, filler = vin[7:9], None  # 8-9: type, NOT filler
        # The legacy example is 7A8|DH|1E|07|01|123456. Do not slice 0DH
        # here or move the model by one character using the newer layout.
    else:
        scheme = "nzta_from_2009_11_29"
        make_code, model_code = vin[3:6], vin[6:8]  # 4-6, 7-8
        vehicle_type_code, filler = None, vin[8]  # 9: always X, no meaning
        if filler != "X":
            raise ValueError("NZTA 7AT format requires filler X at position 9.")
        # 0DH is a single make code (Nissan), NOT category 0 + make D + tag H.
        # In 7AT0DH6LX22, model code is 6L; LX is not a chassis/batch code.

    # 10-11: year VIN ASSIGNED, never manufacture year. Recorded as written.
    # NZTA prints "Year the VIN assigned" with the examples 01 and 09 and states
    # no format rule, so none is enforced here: rejecting a code the publisher
    # never forbade would refuse a VIN the register may legitimately carry, and
    # this helper's job is to read what is there, not to police the register.
    # Preserve YY: the diagram supplies no universal century rollover rule.
    # E.g. 22 in the contemporary example means assignment in 2022, but this
    # helper does not invent a 19xx/20xx pivot or equate it to NZ registration.
    # The 2009 cutoff includes a day/month that cannot be checked from YY alone.
    year_code = vin[9:11]
    # 12-17: NZTA says this number comes from the last six OE chassis digits OR
    # is randomly derived when no chassis/VIN exists. "Number" is as far as the
    # source goes -- it states no rule that the result is numeric -- so the six
    # characters are kept as written. Never label it a recovered full chassis
    # number, and retain leading zeroes.
    serial = None if prefix else vin[11:17]
    return VinDecode(
        vin, prefix, scheme, "structure_decoded",
        {"wmi": wmi, "assigning_authority": "NZ transport authority",
         "make_code": make_code, "model_code": model_code,
         "vehicle_type_code": vehicle_type_code, "filler": filler,
         "vin_assignment_year_code": year_code, "serial_component": serial,
         # Only the source's example codes are resolved. Unknown is preferable
         # to inventing a complete LANDATA dictionary, especially for kTypes.
         "make": "Nissan" if make_code == ("DH" if wmi == "7A8" else "0DH") else None,
         "model": "Bluebird" if make_code == ("DH" if wmi == "7A8" else "0DH") and model_code == "1E" else None},
        tuple(notes + [
            "Assignment-year code is not model, manufacture or first-registration year; century is not inferred.",
            "NZTA assignment does not prove country of origin or used-import status.",
            "Unresolved make/model/type codes require an authoritative LANDATA lookup.",
        ]),
    )


def RULES_PATH() -> Path:
    """The active registry's VIN layout file.

    A function rather than a constant: the registry is selected per run, so a
    path captured at import time would pin the decoder to whichever registry was
    the default when this module was first loaded.
    """
    path = vin_rules_path()
    if path is None:
        raise ValueError('The selected registry carries no VIN layout file')
    return path


def load_rules(path: str | Path | None = None) -> dict:
    """Validate editable lookup data before allowing it to interpret a VIN.

    Returns a freshly parsed structure every call, so a caller may edit the
    result without affecting anyone else. Decoding uses
    :func:`rules_for_decoding` instead, which shares one validated copy.
    """
    rules = json.loads(Path(path or RULES_PATH()).read_text())
    if rules.get("schema_version") != 1:
        raise ValueError("Unsupported VIN rules schema.")
    ids = set()
    for profile in rules["profiles"]:
        if profile["id"] in ids:
            raise ValueError("Duplicate VIN profile ID.")
        ids.add(profile["id"])
        re.compile(profile["pattern"])
        covered = []
        for segment in profile["segments"]:
            covered.extend(range(segment["start"], segment["end"] + 1))
            if segment["evidence_status"] not in {"documented", "inferred"}:
                raise ValueError("Invalid evidence status.")
            if any(s not in rules["sources"] for s in segment["source_ids"]):
                raise ValueError("Unknown source ID.")
        if sorted(covered) != list(range(1, 12)):
            raise ValueError("Every profile must cover positions 1–11 exactly once.")
    return rules


@lru_cache(maxsize=None)
def _validated_rules(path: Path, revision: tuple[int, int]) -> dict:
    """One validated copy per file revision.

    ``revision`` is never read: it is part of the cache key so that editing the
    file produces a different key and the edit is picked up.
    """
    del revision
    return load_rules(path)


EMPTY_RULES = {'schema_version': 1, 'sources': {}, 'profiles': []}


def rules_for_decoding(path: str | Path | None = None) -> dict:
    """The shared, validated rule set. Read-only: callers must not mutate it.

    Decoding consults the rules once per VIN, so re-reading and re-validating
    a 20 KB JSON file on every call would dominate the decoder's runtime. The
    cache is keyed on the file's modification time and size, so editing the
    rules and decoding again picks the edit up.

    A registry that records no VIN layouts yields no profiles rather than an
    error: there is nothing to decode with, so every VIN field stays unknown.
    """
    if path is None and vin_rules_path() is None:
        return EMPTY_RULES
    resolved = Path(path or RULES_PATH())
    info = resolved.stat()
    return _validated_rules(resolved, (info.st_mtime_ns, info.st_size))


def decode_nz_vin(value: str, *, allow_prefix: bool = False,
                  rules_path: str | Path | None = None) -> VinDecode:
    """Decode structure plus sourced fields; unknown codes never inherit values.

    Positions are one-based and refer to the ORIGINAL VIN, including VIN11.
    Composite codes span characters: a character within '0DH' has no separate
    make/category meaning. Evidence quality is per segment, not per VIN.
    Inspect segments for evidence quality; inferred values are never confirmed.
    """
    base = _decode_structure(value, allow_prefix=allow_prefix)
    rules = rules_for_decoding(rules_path)
    matches = [p for p in rules["profiles"] if re.match(p["pattern"], base.vin)]
    if len(matches) > 1:
        raise ValueError("Ambiguous VIN profiles; refine the JSON patterns.")
    profile = matches[0] if matches else None
    definitions = profile["segments"] if profile else [
        {"start": a, "end": b, "key": key, "values": {},
         "source_ids": [], "evidence_status": "documented",
         "note": "Manufacturer-specific lookup required."}
        for a, b, key in [(1, 3, "wmi"), (4, 9, "manufacturer_descriptor"),
                          (10, 11, "identifier_prefix")]]
    segments, positions, used = [], [], set()
    for definition in definitions:
        a, b = definition["start"], definition["end"]
        raw = base.vin[a - 1:b]
        meaning = definition["values"].get(raw)
        # Assignment YY is itself a documented value; no century is supplied.
        if definition["key"] == "vin_assignment_year_code":
            meaning = "Assignment year ending in " + raw + "; century unspecified"
        if (definition["key"] == "model_code" and raw == "1E"
                and base.fields.get("make") == "Nissan"):
            meaning = "Bluebird"
        status = definition["evidence_status"] if meaning is not None else "unresolved"
        segment = {k: v for k, v in definition.items() if k not in {"values", "evidence_status"}}
        segment.update(raw=raw, meaning=meaning, status=status,
                       role_status=definition["evidence_status"] if definition["source_ids"] else "unresolved")
        segments.append(segment)
        used.update(definition["source_ids"])
        for position in range(a, b + 1):
            positions.append(dict(position=position, character=base.vin[position - 1],
                                  segment=definition["key"], segment_start=a,
                                  segment_end=b, status=status))
    statuses = {s["status"] for s in segments}
    status = ("documented_prefix" if statuses == {"documented"} else
              "partial_decode" if statuses & {"documented", "inferred"} else
              "manufacturer_data_required")
    notes = tuple(n for n in base.notes if not n.startswith("OEM decode information"))
    return replace(base, status=status, profile=profile["id"] if profile else None,
                   segments=tuple(segments), positions=tuple(positions),
                   sources={key: rules["sources"][key] for key in sorted(used)},
                   notes=notes + ((profile["note"],) if profile and profile["note"] else ()))


def decode_vin11(value: str, *, rules_path: str | Path | None = None) -> VinDecode:
    """Decode exactly eleven characters, with one entry for every position."""
    if not isinstance(value, str):
        raise TypeError("VIN11 must be a string.")
    if len(value.strip()) != 11:
        raise ValueError("Expected exactly eleven characters.")
    return decode_nz_vin(value, allow_prefix=True, rules_path=rules_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vin")
    parser.add_argument("--allow-prefix", action="store_true")
    parser.add_argument("--rules", type=Path, default=None)
    args = parser.parse_args()
    try:
        result = decode_nz_vin(args.vin, allow_prefix=args.allow_prefix, rules_path=args.rules)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
