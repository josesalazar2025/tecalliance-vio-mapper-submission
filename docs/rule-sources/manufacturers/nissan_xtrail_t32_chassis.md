# Nissan X-Trail T32 chassis model codes

Retrieved 15 September 2026 from Nissan Motor Co. official publications.

## Facts used by the decoder

The Nissan X-Trail specification table identifies the hybrid model codes by drive:

| Configuration | Nissan vehicle model code |
|---|---|
| Hybrid, 2WD | DAA-HT32 |
| Hybrid, 4WD | DAA-HNT32 |

Source: [Nissan X-Trail specifications, October 2018](https://www3.nissan.co.jp/content/dam/Nissan/jp/vehicles/x-trail/1810/specifications/pdf/x-trail_specsheet.pdf), row labelled `車名型式`.

Nissan's recall record identifies an affected vehicle as model `DAA-HNT32` with chassis
number `HNT32-160025`. This establishes that the characters before the hyphen are the
model-code portion of this chassis-number format.

Source: [Nissan recall report 4682](https://www.nissan.co.jp/RECALL/DATA/report4682.html).

## Scoped decoding rule

For a Nissan X-Trail source value matching `HNT32-[A-Z0-9]`, extract `HNT32` as the
manufacturer model code. The source registry supplies only the first seven chassis
characters, so `HNT32-1` is a truncated chassis number rather than a complete serial.

The rule does not infer codes for other Nissan models or other manufacturers. Further
profiles must provide their own manufacturer source, input pattern, reference field and
known model-code vocabulary.
