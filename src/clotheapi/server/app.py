"""給合作方呼叫的試穿 HTTP API。"""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from clotheapi.engines import (
    ALLOWED_TYPES,
    MAX_IMAGE_BYTES,
    EngineError,
    ImageInput,
    run_tryon,
)
from clotheapi.partners import PartnerDirectory, PartnerStoreError
from clotheapi.server.store import JobStore

ENGINES = {"standard", "premium"}


def _sniff_type(data: bytes, declared: str | None) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        kind = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        kind = "image/png"
    elif len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = "image/webp"
    else:
        raise HTTPException(status_code=400, detail="僅支援 JPEG / PNG / WebP 圖片")
    if declared and declared != "application/octet-stream" and declared != kind:
        raise HTTPException(status_code=400, detail="圖片格式與內容不符")
    if kind not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="僅支援 JPEG / PNG / WebP 圖片")
    return kind


async def _read_image(upload: UploadFile, fallback_name: str) -> ImageInput:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail="圖片是空的")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="檔案大小不可超過 10MB")
    content_type = _sniff_type(data, upload.content_type)
    filename = upload.filename or fallback_name
    return ImageInput(data=data, content_type=content_type, filename=filename)


def create_app(
    *,
    data_dir: Path | None = None,
    database_url: str | None = None,
    openai_key: str | None = None,
    fashn_key: str | None = None,
    mock: bool | None = None,
    runner: Callable[..., bytes] | None = None,
) -> FastAPI:
    store = JobStore(data_dir or Path(os.environ.get("CLOTHE_DATA_DIR", "./clotheapi-data")))
    url = database_url if database_url is not None else os.environ.get("DATABASE_URL", "")
    partners = PartnerDirectory(url) if url.strip() else None
    openai = openai_key if openai_key is not None else os.environ.get("OPENAI_API_KEY", "")
    fashn = fashn_key if fashn_key is not None else os.environ.get("FASHN_API_KEY", "")
    use_mock = mock if mock is not None else os.environ.get("CLOTHE_API_MOCK") == "1"
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="clotheapi")

    app = FastAPI(
        title="Clothe API",
        version="0.1.0",
        description="上傳人物照與衣服照，取得虛擬試穿結果。engine 使用 standard 或 premium。",
    )

    bearer = HTTPBearer(auto_error=False)

    def authorize(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
        store_id: str = Query(default=""),
        store_name: str = Query(default=""),
    ) -> None:
        if partners is None:
            raise HTTPException(status_code=503, detail="伺服器尚未設定資料庫")
        token = credentials.credentials.strip() if credentials else ""
        store_id = store_id.strip()
        store_name = store_name.strip()
        if not store_id or not store_name or not token:
            raise HTTPException(status_code=401, detail="請帶入店家編號、店家名稱與金鑰")
        try:
            ok = partners.verify(store_id, store_name, token)
        except PartnerStoreError as exc:
            raise HTTPException(status_code=503, detail="無法驗證店家金鑰") from exc
        if not ok:
            raise HTTPException(status_code=401, detail="店家名稱、編號或金鑰不符")

    def execute(engine: str, person: ImageInput, garment: ImageInput) -> bytes:
        if runner is not None:
            return runner(engine, person, garment)
        if use_mock:
            return b"\x89PNG\r\n\x1a\nmock"
        return run_tryon(engine, person, garment, openai_key=openai, fashn_key=fashn)

    def work(job_id: str, engine: str, person: ImageInput, garment: ImageInput) -> None:
        store.update(job_id, status="processing")
        try:
            image = execute(engine, person, garment)
            path = store.result_file(job_id)
            path.write_bytes(image)
            store.update(job_id, status="completed", result_path=str(path))
        except EngineError as exc:
            store.update(job_id, status="failed", error=str(exc))
        except Exception:
            store.update(job_id, status="failed", error="試穿失敗")

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/tryon", status_code=202, dependencies=[Depends(authorize)])
    async def create_tryon(
        person_image: UploadFile = File(...),
        garment_image: UploadFile = File(...),
        engine: str = Form("standard"),
    ) -> dict[str, str | None]:
        if engine not in ENGINES:
            raise HTTPException(status_code=400, detail="engine 只接受 standard 或 premium")
        person = await _read_image(person_image, "person.jpg")
        garment = await _read_image(garment_image, "garment.jpg")
        job = store.create(engine)
        store.save_upload(job.id, "person", person.data)
        store.save_upload(job.id, "garment", garment.data)
        pool.submit(work, job.id, engine, person, garment)
        return {"id": job.id, "status": job.status, "engine": engine, "error": None}

    @app.get("/v1/tryon/{job_id}", dependencies=[Depends(authorize)])
    def get_tryon(job_id: str) -> dict[str, str | None]:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="找不到這筆試穿")
        return {"id": job.id, "status": job.status, "engine": job.engine, "error": job.error}

    @app.get("/v1/tryon/{job_id}/result", dependencies=[Depends(authorize)])
    def get_result(job_id: str) -> FileResponse:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="找不到這筆試穿")
        if job.status != "completed" or not job.result_path:
            raise HTTPException(status_code=409, detail="試穿尚未完成")
        return FileResponse(job.result_path, media_type="image/png", filename=f"{job_id}.png")

    app.state.store = store
    app.state.pool = pool
    # 讓測試可以等背景工作做完。
    app.state.wait_jobs = lambda: pool.shutdown(wait=True, cancel_futures=False)
    return app
