# Clothe API

把虛擬試穿做成給合作方串接的 HTTP API，以及 Python / TypeScript SDK。串接規格（業務邏輯、上下行格式、串接方式）見 [SPEC.md](SPEC.md)。

這包不包含網站的帳號、點數、衣櫃。呼叫端自己上傳一張人物照和一張衣服照。

## 介面

`POST /v1/tryon`（`multipart/form-data`）

| 欄位 | 說明 |
| --- | --- |
| `person_image` | 人物全身照，JPEG / PNG / WebP，最大 10MB |
| `garment_image` | 衣服照 |
| `engine` | `standard` 或 `premium`，預設 `standard` |

標頭：`Authorization: Bearer <API 金鑰>`

回傳 `202`：

```json
{ "id": "…", "status": "pending", "engine": "standard", "error": null }
```

`GET /v1/tryon/{id}` 查狀態。`status` 為 `pending`、`processing`、`completed`、`failed`。

`GET /v1/tryon/{id}/result` 在完成後回傳 PNG。

`standard` 較快，`premium` 細節較高。回應不會出現底層供應商名稱。

## 啟動

在 `clothes/clotheapi`：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
export DATABASE_URL="postgresql+psycopg://…"
export OPENAI_API_KEY="…"    # standard
export FASHN_API_KEY="…"     # premium
python -m clotheapi.issue "示範店"
clotheapi-server
```

預設聽 `0.0.0.0:8090`。可用 `CLOTHE_PORT`、`CLOTHE_DATA_DIR` 調整。工作紀錄與結果圖寫在資料夾裡，重開機還在。

`CLOTHE_API_MOCK=1` 不呼叫付費引擎，只回傳測試圖。

## Python

```python
from clotheapi import ClotheClient

with ClotheClient("店家編號", "示範店", "合作方金鑰", base_url="https://你的網址") as client:
    job = client.tryon("person.jpg", "garment.jpg", engine="premium")
    job.save("result.png")
```

## TypeScript

程式在 `sdk/typescript/src/index.ts`，沒有額外依賴，用瀏覽器或 Node 的 `fetch`。

```ts
import { ClotheClient } from "./index";

const client = new ClotheClient("店家編號", "示範店", "合作方金鑰", "https://你的網址");
const job = await client.tryon(personBlob, garmentBlob, "standard");
const image = await client.result(job.id);
```
