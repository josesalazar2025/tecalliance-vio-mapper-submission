# NZTA VIN layouts — the two assigned-VIN diagrams

**Source URL:** <https://www.nzta.govt.nz/vehicles/vehicle-registration/vin>

**Retrieved:** 2026-09-13

The page states the VIN layouts **only as two images**. Its text says nothing about
`7A8`, `7AT`, character positions, the filler character, the year code or the serial:
every position meaning this project records comes from reading those two pictures. They
are transcribed below, box by box, so a reviewer can check a recorded value without
opening an image — and so that a redrawn diagram fails the checksum instead of changing
a claim silently.

The live site refuses automated requests (HTTP 403), so the images were retrieved from
the Internet Archive's capture of the page. They are byte-identical in the captures of
2025-02-12 and 2026-02-21, which is the stability evidence available:

| Image | Caption on the page | URL | sha256 as retrieved |
|---|---|---|---|
| VIN-pic-1.jpg | Used import: Waka Kotahi-assigned VIN before 29 November 2009 | <https://www.nzta.govt.nz/assets/Vehicles/images/VIN-pic-1.jpg> | `e2ded28ca9332eada6dabc1ef8b1af8d6816cd54e429fe8fcce6928cd899ed9a` |
| VIN-pic-2.jpg | Used import: Waka Kotahi-assigned VIN from 29 November 2009 | <https://www.nzta.govt.nz/assets/Vehicles/images/VIN-pic-2.jpg> | `ed4c983e03cc734d3d37915efbe8066b21d967e603f73eb34fdd69915afed365` |

Archive captures used:
<https://web.archive.org/web/20250212095436/https://www.nzta.govt.nz/vehicles/vehicle-registration/vin/>
and <https://web.archive.org/web/20260221042959/https://www.nzta.govt.nz/vehicles/vehicle-registration/vin/>.

## Diagram 1 — assigned before 29 November 2009 (`VIN-pic-1.jpg`)

Six boxes, left to right, with the caption printed beneath each. Box contents and
caption text are verbatim; line breaks inside a caption are rendered as spaces.

| Positions | Box | Caption beneath the box |
|---|---|---|
| 1–3 | `7A8` | World Manufacturer Identifier (WMI) 7A8 denotes NZTA |
| 4–5 | `DH` | NZTA make code 0DH denotes Nissan |
| 6–7 | `1E` | NZTA model code 1E denotes Bluebird |
| 8–9 | `07` | NZTA vehicle type code |
| 10–11 | `01` | Year the VIN assigned |
| 12–17 | `123456` | Number derived from the last six digits of the OE chassis number or randomly derived if no chassis number or VIN already exists |

## Diagram 2 — assigned from 29 November 2009 (`VIN-pic-2.jpg`)

| Positions | Box | Caption beneath the box |
|---|---|---|
| 1–3 | `7AT` | World Manufacturer Identifier (WMI) 7AT denotes NZTA |
| 4–6 | `0DH` | NZTA make code 0DH denotes Nissan |
| 7–8 | `1E` | NZTA model code 1E denotes Bluebird |
| 9 | `X` | No meaning always X |
| 10–11 | `09` | Year the VIN assigned |
| 12–17 | `123456` | Number derived from the last six digits of the OE chassis number or randomly derived if no chassis number or VIN already exists |

## What the diagrams do and do not settle

**Settled.** The two schemes and the date that separates them; the position boundaries
of both layouts, which sum to 17 characters in each; that position 9 of the newer
layout is a fixed `X` with no meaning; that positions 10–11 record the year the VIN was
*assigned*, not a manufacture or model year; and that positions 12–17 are derived from
the OE chassis number or randomly, so they identify nothing about the vehicle.

**An inconsistency in the source, carried rather than resolved.** In diagram 1 the make
box holds two characters, `DH`, while the caption beneath it reads "0DH denotes Nissan"
— the three-character form used in the newer layout. The box and its own caption
disagree. This project records `DH` for the 4–5 slot, because the box is the layout and
the caption's example is drawn from the other diagram; the discrepancy is noted in the
profile rather than smoothed over.

**Not stated anywhere on the page.** That the year code is numeric — both examples are
(`01`, `09`), and nothing says a letter is impossible. That the serial is six *digits* —
"Number derived from the last six digits" implies it, and the example is `123456`, but
no rule is printed. The decoder once rejected both unless numeric; it no longer does.
Neither field is constrained, and each is recorded as written, because a rule the
publisher never stated would refuse VINs the register may legitimately carry.

**Not enumerable from this page.** The NZTA make codes, model codes and vehicle type
codes. One example of each is given (`0DH` Nissan, `1E` Bluebird) and no list is
published here, so the recorded value tables hold exactly those examples and nothing
else. An unrecognised code yields no value rather than a guess.

## What grounds the checks the decoder does enforce

NZTA states the length and the character set in its own words, on the VIRM page
*1-1 VIN and chassis number* (in-service WoF and CoF, general), retrieved 2026-09-13 from
<https://vehicleinspection.nzta.govt.nz/virms/in-service-wof-and-cof/general/vehicle-identification/vin-and-chassis-number>:

> A valid VIN is a unique number that has been assigned to the vehicle in the vehicle's
> country of origin or by a person appointed by the NZTA. It consists of 17 characters
> that never contain the letters I, O or Q, and that is capable of being decoded to
> provide identifying information about the vehicle.

That sentence, plus "No meaning always X" in diagram 2, is the whole of what this
project enforces. Nothing else about the content of a position is checked.

## Supporting statements from the VIN page

Quoted because they ground the decoder's general behaviour, not a position:

- "A VIN is a 17 character ID number that identifies your vehicle."
- VINs "must conform to International standards as well as New Zealand Legislation",
  naming "ISO 3779 – Road Vehicles – VIN Content and Structure" and "ISO 3780 – Road
  Vehicles – World Manufacturer Identifier (WMI) code."
- Acceptable manufacturer decode information "will show the VIN structure and the decode
  data for each position of the VIN as in the examples below for Chevrolet and Jaguar" —
  i.e. a factory VIN needs its own manufacturer's decode, which is why every non-NZTA
  WMI is returned as `manufacturer_data_required` here.

The VIRM page *3-1 Assigning a VIN*
(<https://vehicleinspection.nzta.govt.nz/virms/entry-certification/pre-reg-and-vin/vin-assignment/assigning-a-vin>)
confirms the assignment rule in words: "A vehicle may have an original VIN assigned by
the manufacturer, or it may need to have an NZTA '7AT' VIN assigned to it", and
"LANDATA will assign a '7AT' VIN to the vehicle" where no valid manufacturer VIN can be
decoded. It prints no character positions.
