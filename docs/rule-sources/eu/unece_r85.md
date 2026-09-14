# UN/ECE Regulation No 85 — measurement of net power, paragraph 5.4

**Source URL:** <https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:42014X1107(01)>

**Retrieved:** 2026-09-13

**Full title.** "Regulation No 85 of the Economic Commission for Europe of the United
Nations (UN/ECE) — Uniform provisions concerning the approval of internal combustion
engines or electric drive trains intended for the propulsion of motor vehicles of
categories M and N with regard to the measurement of net power and the maximum 30 minutes
power of electric drive trains".

**Official Journal reference.** OJ L 323, 7.11.2014, pp. 52–90.

**Retrieval note.** The UNECE-hosted PDF at
<https://unece.org/fileadmin/DAM/trans/main/wp29/wp29regs/2013/R085r1e.pdf> refuses
automated requests (HTTP 403), so the text was taken from the EUR-Lex publication of the
same Regulation. Only paragraph 5.4 is reproduced — the single statement this project
cites. Paragraphs 5.1 to 5.3 describe the test procedure and Annexes 1 and 5 the
measurement conditions; none of that is cited here.

---

## 5.4. Interpretation of results

> The net power and the maximum 30 minutes power for electric drive trains indicated by
> the manufacturer for the type of drive train shall be accepted if it does not differ by
> more than ± 2 per cent for maximum power and more than ± 4 per cent at the other
> measurement points on the curve with a tolerance of ± 2 per cent for engine or motor
> speed.

---

**What this project cites it for, and what it does not.** The ± 2 per cent band is the
tolerance between a *measurement* and the figure the *manufacturer declares* for a drive
train type. It is not a statement that two catalogues recording the same vehicle may
differ by 2 per cent, and this project does not read it as one. It is cited for two narrower
things, both recorded in the `grounding` block of `vio_mapper/rules/scoring.json`:

1. A vehicle type's net power is not a single exact number even in law — the approval
   process itself admits a band around the declared figure. That a power band can exist at
   all is therefore not this project's invention.
2. It gives that band a ceiling. A difference wider than 2 per cent is wider than type
   approval admits between a measurement and a declaration, so it is evidence of a
   different vehicle rather than of a differently-recorded one.

The units are kilowatts throughout; the Regulation states no rounding or decimal
convention, which is why the integer-rounding argument is grounded on the two registers'
own field definitions instead — see `columns` in `vio_mapper/rules/registries/nz.json`, where
NZTA defines `POWER_RATING` as an Integer in kW.
