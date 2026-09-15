"""The HTTP surface: upload a registry file, read the run back, download the workbook.

Runs are executed in a worker thread rather than on the event loop. The mapper is
synchronous and CPU-bound, and running it inline would stall every other request
-- including the browser's own poll for the result -- for the length of the run.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from vio_mapper.config import ALGORITHM_VERSION, DEFAULT_REFERENCE_PATH, Policy

from . import payload, runner

FRONTEND_DIR = Path(__file__).resolve().parent / 'frontend'
# Big enough for the demonstration subsets, small enough that a misdropped
# archive is refused before it is read into memory.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

logger = logging.getLogger(__name__)

app = FastAPI(title='TecAlliance VIO Mapper', version=ALGORITHM_VERSION,
              description='Live demonstration of evidence-based kType mapping for the NZ vehicle register.')
store = runner.RunStore()


@app.exception_handler(runner.RunError)
async def _run_error(request, error: runner.RunError):
    return JSONResponse({'detail': str(error)}, status_code=400)


@app.get('/api/defaults')
async def defaults() -> dict:
    """Describe the fixed review policy and the local reference availability."""
    return {
        'algorithm_version': ALGORITHM_VERSION,
        'payload_version': payload.PAYLOAD_VERSION,
        'reference_name': DEFAULT_REFERENCE_PATH.name,
        'reference_available': DEFAULT_REFERENCE_PATH.exists(),
        'accepted_suffixes': list(runner.SUPPORTED_SUFFIXES),
        'max_source_rows': runner.MAX_SOURCE_ROWS,
        'policy': payload.primary_policy(Policy()),
        'rules': payload.rules(Policy()),
    }


@app.post('/api/run')
async def create_run(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """Map an uploaded registry file under the documented default policy."""
    form = await request.form()
    overrides = sorted(set(form) - {'file'})
    if overrides:
        raise runner.RunError('Policy overrides are not supported by the primary API: '
                              + ', '.join(overrides))
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise runner.RunError(f'File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.')
    run = await run_in_threadpool(runner.execute, file.filename or 'upload.xlsx', content,
                                  Policy(), store)
    logger.info('run %s: %s rows from %s', run.id, len(run.results), run.source_name)
    return run.data


def _require(run_id: str) -> runner.Run:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404,
                            detail='That run is no longer held in memory. Re-run the file.')
    return run


@app.get('/api/run/{run_id}')
async def read_run(run_id: str) -> dict:
    return _require(run_id).data


@app.get('/api/run/{run_id}/row')
async def read_row(run_id: str, source_key: str) -> dict:
    """One row with every candidate it was compared against, for the drawer."""
    return runner.row_detail(_require(run_id), source_key)


@app.get('/api/run/{run_id}/download')
async def download(run_id: str) -> FileResponse:
    run = _require(run_id)
    workbook = await run_in_threadpool(runner.ensure_workbook, run)
    return FileResponse(workbook, filename=workbook.name,
                        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.get('/api/run/{run_id}/report')
async def report(run_id: str) -> dict:
    return {'markdown': _require(run_id).report}


@app.get('/api/health')
async def health() -> dict:
    return {'status': 'ok', 'algorithm_version': ALGORITHM_VERSION}


# Mounted last so every /api route above wins over a same-named static file.
if FRONTEND_DIR.is_dir():
    app.mount('/', StaticFiles(directory=FRONTEND_DIR, html=True), name='frontend')
