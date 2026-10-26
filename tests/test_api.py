import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clotheapi.engines import ImageInput
from clotheapi.partners import PartnerDirectory
from clotheapi.server.app import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"
STORE_NAME = "示範店"


@pytest.fixture
def client(tmp_path: Path):
    calls: list[str] = []

    def runner(engine: str, person: ImageInput, garment: ImageInput) -> bytes:
        calls.append(engine)
        assert person.data.startswith(b"\x89PNG")
        assert garment.data.startswith(b"\x89PNG")
        return b"\x89PNG\r\n\x1a\nresult"

    database_url = f"sqlite:///{tmp_path}/app.db"
    store_id, api_key = PartnerDirectory(database_url).issue(STORE_NAME)
    app = create_app(data_dir=tmp_path, database_url=database_url, runner=runner)
    with TestClient(app) as http:
        yield http, calls, app, {"store_id": store_id, "store_name": STORE_NAME}, api_key


def _files():
    return {
        "person_image": ("person.png", io.BytesIO(PNG), "image/png"),
        "garment_image": ("garment.png", io.BytesIO(PNG), "image/png"),
    }


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_tryon_completes(client):
    http, calls, app, params, api_key = client
    created = http.post(
        "/v1/tryon",
        headers=_auth(api_key),
        params=params,
        files=_files(),
        data={"engine": "premium"},
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    app.state.pool.shutdown(wait=True)
    status = http.get(f"/v1/tryon/{job_id}", headers=_auth(api_key), params=params)
    assert status.json()["status"] == "completed"
    assert calls == ["premium"]
    result = http.get(f"/v1/tryon/{job_id}/result", headers=_auth(api_key), params=params)
    assert result.status_code == 200
    assert result.content.startswith(b"\x89PNG")


def test_rejects_missing_credentials(client):
    http, _, _, _, _ = client
    response = http.post("/v1/tryon", files=_files())
    assert response.status_code == 401
    assert response.json()["detail"] == "請帶入店家編號、店家名稱與金鑰"


def test_rejects_wrong_name(client):
    http, _, _, params, api_key = client
    response = http.post(
        "/v1/tryon",
        headers=_auth(api_key),
        params={**params, "store_name": "別家"},
        files=_files(),
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "店家名稱、編號或金鑰不符"


def test_rejects_bad_engine(client):
    http, _, _, params, api_key = client
    response = http.post(
        "/v1/tryon",
        headers=_auth(api_key),
        params=params,
        files=_files(),
        data={"engine": "gpt"},
    )
    assert response.status_code == 400


def test_rejects_non_image(client):
    http, _, _, params, api_key = client
    files = {
        "person_image": ("a.txt", io.BytesIO(b"hello"), "text/plain"),
        "garment_image": ("garment.png", io.BytesIO(PNG), "image/png"),
    }
    response = http.post("/v1/tryon", headers=_auth(api_key), params=params, files=files)
    assert response.status_code == 400
