# KBA — World Manufacturer Identifier allocation (SV 3.1)

**Publisher:** Kraftfahrt-Bundesamt (KBA), the German federal motor transport authority.

**Source page:** <https://www.kba.de/DE/Themen/Typgenehmigung/CoC_Daten_Fahrzeugtypdaten/Veroeffentlichungen/SV3.html>

**File:** `SV 3.1` — "Verzeichnis der Hersteller von Kraftfahrzeugen und
Kraftfahrzeuganhängern - alphabetisch -", Stand: 15. Januar 2026, linked from that page as
<https://www.kba.de/SharedDocs/Downloads/DE/SV/sv31_pdf.pdf>

**Retrieved:** 2026-09-18. `sha256` of the PDF as retrieved:
`d4a7daa14f46571fbcbe1e242567f0c1b79dd49793ea916e57b740c0495440f8`

**Retrieval note.** The download URL carries a `?__blob=publicationFile&v=6` query string
that the KBA increments on republication, so the hash pins the 15 January 2026 edition
rather than whatever the link currently serves. The PDF is 151 pages; only the two
statements and the rows quoted below are reproduced. The file itself is not committed —
it is public, reconstructable and carries a reproduction restriction on its cover page.

---

## Why this publisher

The source page states:

> Das Kraftfahrt-Bundesamt (KBA) teilt Herstellern eine 4-stellige nationale
> Herstellerschlüsselnummer zu. Zudem ist das KBA die Vergabestelle für die
> Weltherstellerschüsselnummer (WMI) für in Deutschland ansässige Hersteller.

The KBA is therefore not a secondary commentator on these codes. It is the body that
allocates them for manufacturers established in Germany, which is what makes its
directory the primary record for a German WMI.

## What the directory's WMI column is

Preliminary remarks, German original and the publication's own English rendering:

> Außer den nationalen HSN (4stellig) sind - soweit bekannt World manufacturer identifier
> (WMI) (3-stellig bzw. 6-stellig) gem. DIN- ISO 3780 in Verbindung mit DIN-ISO 3779
> aufgenommen worden.

> Beside the national HSN (4 digit) are –as far as known - the World manufacturer
> identifier (WMI) (3-digit or 6-digit) according to DIN ISO 3780 in connection with
> DIN ISO 3779 is stated.

Columns are *Vollständige Herstellerbezeichnung* (full manufacturer's name), *WMI*,
*Herstellerstandort* (manufacturer location), and the KBA national HSN.

## Rows cited by this project

Recorded verbatim, in the directory's own spelling and capitalisation.

| WMI | Manufacturer | Location | HSN |
|---|---|---|---:|
| `W1K` | Mercedes-Benz AG | Stuttgart | 2222 |
| `W1N` | Mercedes-Benz AG | Stuttgart | 2222 |
| `WDD` | Daimler AG (ALLE FAHRZEUGARTEN) | STUTTGART | 1313 |
| `WDD` | DAIMLERCHRYSLER AG (PERSONENKRAFTWAGEN) | STUTTGART-UNTERTUERKHEIM | 0710 |
| `WMX` | Mercedes-AMG GmbH | Affalterbach | 2222 |

The directory records twenty-two further `W1*` and `W2*` codes against Mercedes-Benz AG
(`W1A`, `W1L`, `W1M`, `W1P`, `W1R`, `W1V`, `W1W`, `W1X`, `W1Y`, `W1Z`, `W10`–`W14`,
`W2W`–`W2Z`), and the `WD*` block against Daimler AG and its predecessor names. Only the
rows above are cited.

## What this establishes, and what it does not

**Establishes.** `W1K` is allocated to Mercedes-Benz AG of Stuttgart. `WDD` is allocated
to the same Stuttgart passenger-car manufacturer under its earlier corporate names, and
the 0710 row states its vehicle class explicitly as *Personenkraftwagen*. A `W1K` VIN and
a `WDD` VIN therefore come from one manufacturer recorded under successive names, on the
authority of the body that issues both codes.

**Does not establish.** Nothing here describes the *content* of any VIN position. DIN ISO
3779 fixes characters 4–9 as the Vehicle Descriptor Section, but what a manufacturer puts
in that section is the manufacturer's own convention, and the KBA does not publish it.
The claim this project needs — that Mercedes populates characters 4–9 with the
Grundbaumuster under `W1K` exactly as it documents for `WDD` — is **not** supported by
this source, and Mercedes' own parts documentation
([`../manufacturers/mercedes_c_class_205_type_codes.md`](../manufacturers/mercedes_c_class_205_type_codes.md))
still does not name `W1K`. The `WDD`-scoped decoder is therefore left unchanged; see that
note for the decision and the re-check that produced it.
