# Local review UI

The optional browser interface demonstrates the same mapping and review workflow as
the CLI. Start it with `uv sync --extra web` followed by `uv run vio-mapper-ui`, then
open `http://127.0.0.1:8000`.

The interface lets a reviewer:

- upload an authorized registry workbook or delimited file;
- inspect accepted and unresolved totals;
- review grouped questions and candidate-level evidence;
- inspect review-only text similarity used to order otherwise tied candidates;
- inspect rule and audit information; 
- download the generated workbook.

The UI is a local demonstration, and runs are temporary, retained
only in process memory and local temporary directories, and limited to 20,000 source
rows. The proprietary reference workbook remains on the local machine under `data/`
and is never served as a download. The result workbook is generated lazily on the first
download request so XLSX serialization does not delay the initial analysis response.
