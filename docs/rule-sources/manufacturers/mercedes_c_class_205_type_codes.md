# Mercedes-Benz C-Class 205 type codes

Retrieved 15 September 2026. This note records only the facts used by the
manufacturer-code decoder. It does not claim that a type code alone identifies a
kType outside the supplied TecAlliance reference extract.

## Registry model-code field

NZTA's official Motor Vehicle Register field description defines `MVMA_MODEL_CODE` as
a model code assigned by the manufacturer when a VIN is allocated to an NZ-new
vehicle. The stored, hashed transcription is at
[`docs/rule-sources/nz/nzta_mvr_fields.md`](../nz/nzta_mvr_fields.md).

The supplied Mercedes rows carry values such as `20508022-NZ5` and `20538022-NZ5`.
Their leading six characters equal type numbers independently published by Mercedes
below. Treating that leading value as a candidate hint is an explicit, review-only
format interpretation: NZTA does not publish the internal format of the remaining
characters. No character of `VIN11` is decoded by this rule.

## Mercedes FIN structure

Mercedes-Benz's official German original-parts site explains its FIN using
`WDB 245208 1A 123456`. It identifies the three-character first block as the world
manufacturer code and the following six-character block, `245208`, as the
`Grundbaumuster` used for parts assignment. Mercedes says that this block describes
the series, body form and engine. The page explicitly names `WDD` among the other
Mercedes world-manufacturer codes to which the explanation applies:

<https://www.originalteile.mercedes-benz.de/originalteile/baumuster-finden/>

This establishes positions 4-9 as the six-character vehicle type for the `WDD`
FINs handled here. It does not explicitly name the newer `W1K` WMI, so this rule
does not extrapolate the same layout to `W1K`; those VINs remain neutral.

## Official Mercedes-Benz model/type pairs

The following official Mercedes-Benz owner manuals print the model and type number
together in their technical-data tables:

| Body manual | Recorded model/type | Relevant PDF page | Official source |
|---|---|---:|---|
| C-Class Saloon | C 200 (205.080) | 400 | <https://static.oneweb.mercedes-benz.com/css-oom-assets/en-mt/pdf/mercedes-c-class-sedan-2020-march-w205-audio20-owners-manual-1.pdf> |
| C-Class Estate | C 200 (205.280) | 482 | <https://static.oneweb.mercedes-benz.com/css-oom-assets/en-bd/pdf/mercedes-c-class-estate-2018-september-s205-comand-owners-manual-1.pdf> |
| C-Class Coupe | C 200 (205.380) | 431 | <https://static.oneweb.mercedes-benz.com/css-oom-assets/en-do/pdf/mercedes-c-class-coupe-2018-september-c205-audio20-owners-manual-1.pdf> |
| C-Class Cabriolet | C 200 (205.480) | 463 | <https://static.oneweb.mercedes-benz.com/css-oom-assets/en-lk/pdf/mercedes-c-class-cabriolet-2018-september-a205-comand-owners-manual-1.pdf> |

The supplied TecAlliance extract independently records those same dotted values in
`Type_design`. The helper removes punctuation before comparison, so the leading MVMA
value `205080` compares with reference `205.080` without treating formatting as
evidence.

## Decision boundary

Only the four enumerated type codes above are comparable. An unknown code remains
unknown. Agreement from the composite `MVMA_MODEL_CODE` can name a likely candidate
for review, but it cannot veto another candidate, satisfy the evidence floor or
populate `mapped kType`. A supported `WDD` VIN may compare its documented
six-character `Grundbaumuster` with `Type_design`; unfamiliar codes, other WMIs and
malformed VIN11 values remain unknown.
