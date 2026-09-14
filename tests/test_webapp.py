"""Self-contained checks for the packaged local review interface."""
from pathlib import Path

import pandas as pd
import pytest

fastapi = pytest.importorskip('fastapi', reason='the web dependencies are not installed')
from fastapi.testclient import TestClient  # noqa: E402

from vio_mapper.config import Policy  # noqa: E402
from webapp import payload, runner  # noqa: E402
from webapp.api import app  # noqa: E402


SOURCE_ROW = {
    'ID': 1,
    'MAKE': 'HYUNDAI',
    'MODEL': 'KONA',
    'SUBMODEL': '',
    'VEHICLE_YEAR': 2020,
    'CC_RATING': 1999,
    'MOTIVE_POWER': 'PETROL',
    'POWER_RATING': 110,
    'ENGINE_NUMBER': 'G4NA123456',
    'BODY_TYPE': 'HATCHBACK',
    'IMPORT_STATUS': 'NEW',
    'PREVIOUS_COUNTRY': '',
}

REFERENCE_ROWS = [
    {
        'KType': 1,
        'Brand': 'HYUNDAI',
        'Sales_designation': 'KONA',
        'Construction_from': 201801,
        'Construction_to': 202212,
        'Capacity_cubic': 1999,
        'Fuel_type': 'Petrol',
        'Maximum_output_KW': 110,
        'Engine_code': 'G4NA',
        'Kind_of_structure': 'Hatchback',
        'Drive_system': 'Front-Wheel Drive',
        'Type_designation': 'OS',
        'Model_design': 'OS',
    },
    {
        'KType': 2,
        'Brand': 'HYUNDAI',
        'Sales_designation': 'KONA',
        'Construction_from': 201801,
        'Construction_to': 202212,
        'Capacity_cubic': 1999,
        'Fuel_type': 'Petrol',
        'Maximum_output_KW': 120,
        'Engine_code': 'G4NB',
        'Kind_of_structure': 'Hatchback',
        'Drive_system': 'Front-Wheel Drive',
        'Type_designation': 'OS',
        'Model_design': 'OS',
    },
]


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_frontend_is_served_and_matches_the_payload_version(client):
    assert client.get('/').status_code == 200
    defaults = client.get('/api/defaults').json()
    assert defaults['algorithm_version'] == '1.0.0'
    assert defaults['payload_version'] == payload.PAYLOAD_VERSION
    script = (Path(__file__).parents[1] / 'webapp/frontend/app.js').read_text()
    assert f'const EXPECTED_PAYLOAD_VERSION = {payload.PAYLOAD_VERSION};' in script


def test_health_endpoint(client):
    assert client.get('/api/health').json() == {
        'status': 'ok',
        'algorithm_version': '1.0.0',
    }


def test_primary_api_rejects_policy_overrides(client):
    response = client.post(
        '/api/run',
        files={'file': ('source.csv', b'ID,MAKE,MODEL,VEHICLE_YEAR\n1,A,B,2020\n')},
        data={'accept_score': '0'},
    )
    assert response.status_code == 400
    assert 'Policy overrides are not supported' in response.json()['detail']


def test_runner_builds_the_same_review_artifacts_without_proprietary_fixtures(
        tmp_path: Path, monkeypatch):
    reference = tmp_path / 'reference.xlsx'
    pd.DataFrame(REFERENCE_ROWS).to_excel(reference, index=False)
    monkeypatch.setattr(runner, 'DEFAULT_REFERENCE_PATH', reference)
    source_bytes = pd.DataFrame([SOURCE_ROW]).to_csv(index=False).encode()

    run = runner.execute('source.csv', source_bytes, Policy(), runner.RunStore())
    try:
        assert run.workbook.exists()
        assert run.data['summary']['accepted'] == 1
        assert run.data['summary']['unresolved'] == 0
        assert run.data['results'][0]['mapped kType'] == 1
        assert run.data['download_name'] == 'mapped_source.xlsx'
        detail = runner.row_detail(run, 'source.csv!2')
        assert detail['row']['mapped kType'] == 1
        assert len(detail['candidates']) == 2
    finally:
        run.dispose()
