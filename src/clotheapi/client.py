"""Python SDK。合作方安裝這個套件後，不用自己組 multipart。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx


class ClotheApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _as_bytes(source: bytes | str | Path, fallback_name: str) -> tuple[str, bytes]:
    if isinstance(source, bytes):
        return fallback_name, source
    path = Path(source)
    return path.name, path.read_bytes()


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    return str(body)


@dataclass
class TryonJob:
    id: str
    status: str
    engine: str
    error: str | None
    _client: ClotheClient

    def refresh(self) -> TryonJob:
        return self._client.get(self.id)

    def wait(self, *, timeout: float = 180, interval: float = 2) -> TryonJob:
        deadline = time.monotonic() + timeout
        current = self
        while current.status in {"pending", "processing"}:
            if time.monotonic() >= deadline:
                raise ClotheApiError("試穿逾時")
            time.sleep(interval)
            current = current.refresh()
        if current.status == "failed":
            raise ClotheApiError(current.error or "試穿失敗")
        return current

    def result_bytes(self) -> bytes:
        return self._client.result_bytes(self.id)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_bytes(self.result_bytes())
        return target


class ClotheClient:
    def __init__(
        self,
        store_id: str,
        store_name: str,
        api_key: str,
        base_url: str = "http://127.0.0.1:8090",
        timeout: float = 60,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            params={"store_id": store_id, "store_name": store_name},
            timeout=timeout,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ClotheClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _job(self, body: dict) -> TryonJob:
        return TryonJob(
            id=body["id"],
            status=body["status"],
            engine=body["engine"],
            error=body.get("error"),
            _client=self,
        )

    def create_tryon(
        self,
        person: bytes | str | Path,
        garment: bytes | str | Path,
        *,
        engine: str = "standard",
    ) -> TryonJob:
        person_name, person_bytes = _as_bytes(person, "person.jpg")
        garment_name, garment_bytes = _as_bytes(garment, "garment.jpg")
        response = self._http.post(
            "/v1/tryon",
            data={"engine": engine},
            files={
                "person_image": (person_name, person_bytes),
                "garment_image": (garment_name, garment_bytes),
            },
        )
        if response.status_code >= 400:
            raise ClotheApiError(_detail(response), response.status_code)
        return self._job(response.json())

    def get(self, job_id: str) -> TryonJob:
        response = self._http.get(f"/v1/tryon/{job_id}")
        if response.status_code >= 400:
            raise ClotheApiError(_detail(response), response.status_code)
        return self._job(response.json())

    def result_bytes(self, job_id: str) -> bytes:
        response = self._http.get(f"/v1/tryon/{job_id}/result")
        if response.status_code >= 400:
            raise ClotheApiError(_detail(response), response.status_code)
        return response.content

    def tryon(
        self,
        person: bytes | str | Path,
        garment: bytes | str | Path,
        *,
        engine: str = "standard",
        timeout: float = 180,
    ) -> TryonJob:
        """建立試穿並等到完成。"""
        return self.create_tryon(person, garment, engine=engine).wait(timeout=timeout)
