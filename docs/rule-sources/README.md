# Rule sources

These local transcriptions pin the public sources used to define NZ registry fields,
vehicle vocabularies, VIN layouts and the compared attribute groups. Each source URL,
retrieval date and content hash is recorded in the corresponding JSON file under
`vio_mapper/rules/`.

| Folder | Publisher and use |
|---|---|
| `nz/` | NZTA field definitions, vehicle classes, body/engine types and VIN layouts |
| `eu/` | EU/UNECE definitions used to group vehicle attributes and bound power reasoning |

The proprietary RDM workbook and TecDoc Data Format PDF are not reproduced here. The
TecDoc JSON vocabulary records only the terms required by the mapper and their origin;
the authorized workbook is supplied separately for execution.

These sources identify what fields mean. They do not publish a kType matching
algorithm, confidence threshold or proof that available attribute agreement uniquely
identifies a vehicle. The selection policy remains a documented engineering judgment.
