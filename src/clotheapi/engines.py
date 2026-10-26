"""試穿引擎。對外只分 standard / premium，供應商名稱留在這個檔案。"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import httpx

FASHN_RUN_URL = "https://api.fashn.ai/v1/run"
OPENAI_EDITS_URL = "https://api.openai.com/v1/images/edits"
GPT_TRYON_PROMPT = (
    "Edit the person photo (image 1) so they are wearing the garment shown in "
    "image 2. Keep the person's identity, face, body, pose, and the original "
    "background. Replace only the relevant clothing with the garment, matching "
    "its color, pattern, and shape. Photorealistic, no extra people, no text, "
    "no watermark."
)

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class EngineError(Exception):
    """供應商失敗時丟出，訊息給呼叫端看，不含金鑰。"""


@dataclass(frozen=True)
class ImageInput:
    data: bytes
    content_type: str
    filename: str


def data_uri(image: ImageInput) -> str:
    encoded = base64.b64encode(image.data).decode("ascii")
    return f"data:{image.content_type};base64,{encoded}"


def _decode_data_uri(value: str) -> bytes:
    payload = value.split(",", 1)[1] if "," in value else value
    return base64.b64decode(payload)


def run_standard(person: ImageInput, garment: ImageInput, api_key: str) -> bytes:
    """OpenAI images/edits。合作方的 standard 固定用 medium。"""
    if not api_key:
        raise EngineError("尚未設定 standard 引擎金鑰")
    files = [
        ("image[]", (person.filename, person.data, person.content_type)),
        ("image[]", (garment.filename, garment.data, garment.content_type)),
    ]
    data = {
        "model": "gpt-image-2",
        "prompt": GPT_TRYON_PROMPT,
        "size": "1024x1536",
        "quality": "medium",
        "output_format": "png",
    }
    try:
        with httpx.Client(timeout=180) as client:
            response = client.post(
                OPENAI_EDITS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                data=data,
                files=files,
            )
    except httpx.HTTPError as exc:
        raise EngineError("standard 引擎連線失敗") from exc
    if response.status_code >= 400:
        raise EngineError(f"standard 引擎失敗（{response.status_code}）")
    body = response.json()
    b64 = (body.get("data") or [{}])[0].get("b64_json")
    if not b64:
        raise EngineError("standard 引擎沒有回傳圖片")
    return base64.b64decode(b64)


def run_premium(person: ImageInput, garment: ImageInput, api_key: str) -> bytes:
    """Fashn tryon-max，quality + 2k。圖片以 data URI 送出，結果要 base64。"""
    if not api_key:
        raise EngineError("尚未設定 premium 引擎金鑰")
    payload = {
        "model_name": "tryon-max",
        "inputs": {
            "model_image": data_uri(person),
            "product_image": data_uri(garment),
            "resolution": "2k",
            "generation_mode": "quality",
            "output_format": "png",
            "return_base64": True,
        },
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=60) as client:
            created = client.post(FASHN_RUN_URL, headers=headers, json=payload)
            if created.status_code == 429:
                time.sleep(2)
                created = client.post(FASHN_RUN_URL, headers=headers, json=payload)
            if created.status_code >= 400:
                raise EngineError(f"premium 引擎失敗（{created.status_code}）")
            prediction_id = created.json().get("id")
            if not prediction_id:
                raise EngineError("premium 引擎沒有回傳工作編號")
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                status = client.get(
                    f"https://api.fashn.ai/v1/status/{prediction_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if status.status_code >= 400:
                    raise EngineError(f"premium 引擎查詢失敗（{status.status_code}）")
                body = status.json()
                state = body.get("status")
                if state == "completed":
                    output = body.get("output")
                    if isinstance(output, list):
                        output = output[0] if output else None
                    if not isinstance(output, str) or not output:
                        raise EngineError("premium 引擎沒有回傳圖片")
                    if output.startswith("data:") or output.startswith("/9j") or output.startswith("iVBOR"):
                        return _decode_data_uri(output)
                    image = client.get(output)
                    if image.status_code >= 400:
                        raise EngineError("premium 引擎圖片下載失敗")
                    return image.content
                if state in {"failed", "canceled", "error"}:
                    raise EngineError("premium 引擎生成失敗")
                time.sleep(3)
    except EngineError:
        raise
    except httpx.HTTPError as exc:
        raise EngineError("premium 引擎連線失敗") from exc
    raise EngineError("premium 引擎逾時")


def run_tryon(engine: str, person: ImageInput, garment: ImageInput, *, openai_key: str, fashn_key: str) -> bytes:
    if engine == "premium":
        return run_premium(person, garment, fashn_key)
    if engine == "standard":
        return run_standard(person, garment, openai_key)
    raise EngineError("engine 只接受 standard 或 premium")
