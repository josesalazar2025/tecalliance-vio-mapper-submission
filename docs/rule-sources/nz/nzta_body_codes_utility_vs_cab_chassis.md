# NZ `UTILITY` and the TecDoc `Platform/Chassis` question

This note records what the published sources do and do not settle about one
unresolved group: the ten Holden Colorado vehicles whose two candidate kTypes,
100868 and 100871, are identical on every technical field and differ only in
`Kind_of_structure` — `Platform/Chassis` against `Pickup`.

No rule in `vio_mapper/rules/` acts on anything below. The body correspondence
table still pairs a registration body with a reference structure only where both
publishers print the same word, and `UTILITY` matches no TecDoc value by name.
This note exists so that the open half of the question is written down with its
source, rather than being rediscovered.

## What NZTA settles

**Source:** NZTA VIRM entry certification 2-2, *Vehicle attributes definitions*,
Table 2-2-8 (vehicle and body type combinations). Transcribed and hash-recorded at
[`nzta_virm_attributes.md`](nzta_virm_attributes.md); retrieved 2026-09-12.

For vehicle type **08, Goods van/truck/utility**, Table 2-2-8 lists eight body type
codes:

| Code | Body type |
|---|---|
| AT | Articulated truck |
| **CC** | **Cab/chassis** |
| FT | Flat-deck truck |
| HV | Heavy van |
| LV | Light van |
| OT | Other truck |
| SW | Station wagon |
| **UT** | **Utility** |

`UT` and `CC` are separate, mutually exclusive entries in the same publisher's
table, for the same vehicle type. The supplied Colorado rows carry
`VEHICLE_TYPE = GOODS VAN/TRUCK/UTILITY` and `BODY_TYPE = UTILITY`, so NZTA had a
cab/chassis code available for exactly these vehicles and recorded a different one.

The distinction is used in practice, not merely defined. In the published 2020
motor vehicle register (181,790 vehicles) **1,376 vehicles are recorded
`CAB AND CHASSIS ONLY`**, every one of them within `GOODS VAN/TRUCK/UTILITY`,
alongside 26,307 recorded `UTILITY`. All 2,427 Colorados in that file are
`UTILITY`; none is cab/chassis.

**What this establishes:** an NZ vehicle recorded `UTILITY` is, by NZTA's own
taxonomy and practice, not a cab-chassis. It is a negative, not a positive: it says
nothing about whether `UTILITY` corresponds to TecDoc `Pickup`.

## What no published source settles

The reference values `Pickup` and `Platform/Chassis` are read from the
`Kind_of_structure` column of the supplied extract. Their definitions belong to
TecDoc key table **KT 086**, which the project does not hold.

The public TecDoc Data Format specification
(<https://dwnld.aws.tecalliance.com/TecDoc/Downloads/TecDoc-Data-Format.pdf>,
checked 2026-09-17) defines the schema — field names, key table numbers, data
types — and names KT 086, but does not enumerate its values. It contains no
occurrence of `Pickup`, `Platform`, `Kind of structure` or `body type`.

EU Regulation 2018/858 Annex I Part C defines EU bodywork codes, including `BE`
pick-up truck, and Part B of that Annex is transcribed at
[`../eu/eu_2018_858_annex_i_part_b.md`](../eu/eu_2018_858_annex_i_part_b.md). It
does not close the question either: TecDoc's structure vocabulary (`Pickup`,
`Platform/Chassis`, `Estate`, `MPV`, `Closed Off-Road Vehicle`) is not the EU code
set, and no publisher states that one follows the other. Treating the resemblance
as a mapping would be the judgement this project removed from the body table in the
first place.

## What would close it

One line from KT 086. If TecAlliance's own key table defines `Platform/Chassis` as
a cab-chassis or otherwise incomplete body, then:

- NZTA records these vehicles as `UT`, not `CC` — sourced above;
- `Platform/Chassis` denotes the body NZTA would have recorded as `CC`;
- therefore the source contradicts kType 100868, leaving 100871 uniquely
  compatible, and the ten Colorado vehicles resolve.

That is a veto derived from two publishers' own statements, not a correspondence
invented here. Until the KT 086 definition is produced, the rows stay ambiguous and
both candidates remain compatible, which is the current behaviour.

**Scope:** this argument is specific to a candidate pair separated only by
`Platform/Chassis` against another structure. It does not create a general
`UTILITY` correspondence, and it would not on its own resolve the Ford Ranger
group, where excluding `Platform/Chassis` still leaves more than one candidate.
