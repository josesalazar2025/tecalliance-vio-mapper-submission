# Holden Colorado RG identifier evidence

Accessed 2026-09-15.

This note transcribes only the claims used by the conservative VIN profile. It
does not turn a model/type code into a kType and it does not claim that Holden
published a complete VIN-position chart.

## Australian government approval

Source: Australian Department of Infrastructure approval 49093, issued
14 February 2018:

https://mvsa-api.infrastructure.gov.au/api/v1/file/view/3/14Feb2018200029.pdf

- Schedule 2 identifies the make as `WCS HOLDEN`, model as
  `WCS HOLDEN COLORADO`, and gives typical VIN `MMU147CK0HH000007`.
- Schedule 5 says this second-stage approval is based on first-stage approval
  47708, `HOLDEN RG`, first issued 3 May 2016.

This directly grounds an MMU-form VIN in the Holden Colorado RG approval
family. It does not assign meanings to individual characters after MMU.

## Approved second-stage manufacturer's fitment catalogue

Source: Pedders Suspension & Brakes, GVM+ Kit for Holden Colorado RG2,
identified on the page with approval 47708:

https://www.pedders.com.au/product/gvm-kit-holden-colorado-rg2-gvm-3450kg-app-48965-gvm-rg2colorado

The page's fitment table lists:

| Make | Model | Years | Variant | Series |
|---|---|---:|---|---|
| HOLDEN | COLORADO | 2013–2020 | 2.8 TD 4x4 (`U143BK`, `U143DK`, `U145DK`, `U147DK`) | RG |

The supplied NZ VIN11 begins `MMU143DK`. Reading its positions 4–8 as the
embedded portion of type code `U143DK` is therefore useful supporting evidence,
but remains an inference until a Holden/GM Thailand VIN chart or the complete
first-stage RVD is retrieved.

## Deliberate limits

- No meaning is assigned to position 9 `0`, position 10 `L`, or position 11
  `H`.
- `143DK` supports RG / 2.8 turbo-diesel / 4x4 only. It does not establish trim,
  transmission, exact body construction, or a TecDoc kType.
- The profile may corroborate or shorten a candidate list. It must not accept a
  kType by itself.
