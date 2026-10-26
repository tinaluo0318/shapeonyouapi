# Clothe API 串接規格

版本 0.1.0。這份文件給要串虛擬試穿的合作方。網站本身的帳號、點數、衣櫃不在這支 API 裡。

基底網址由我們提供，本機預設是 `http://127.0.0.1:8090`。除了健康檢查，每個請求都要帶 API 金鑰。

## 業務邏輯

一次試穿就是一張人物照加上一張衣服照。服務把衣服換到人物身上，保留這個人的臉、身材、姿勢和原本背景，只替換對應的衣物，並盡量對上衣服的顏色、花紋和版型。結果是一張寫實 PNG，不會多出其他人，也不會加文字或浮水印。

一次只換一件衣服。要疊穿（先上衣、再褲子）時，把上一張完成圖再當成下一筆的 `person_image`。

建立試穿後不會當場回圖。服務先收下檔案、建立一筆工作，再在背景生成。呼叫端用工作編號輪詢，完成後另外下載圖片。

狀態只會往下走：

```
pending → processing → completed
                     → failed
```

`pending` 是已收下、還沒開始。`processing` 是生成中。`completed` 才能下載結果。`failed` 不會重試，要重送一筆新的試穿。失敗原因寫在 `error`，成功時 `error` 是 `null`。

### 引擎

| engine | 什麼時候用 | 呼叫端要預留的時間 |
| --- | --- | --- |
| `standard` | 預設。速度較快，輸出直幅圖 | 最多約 3 分鐘 |
| `premium` | 細節較高，輸出較大 | 最多約 2 分鐘 |

不認識的 `engine` 會直接拒絕，不會建立工作。回應裡只有這兩個名稱。

### 圖片規則

兩張圖都要是 JPEG、PNG 或 WebP，單張最大 10MB。服務看檔案內容，不只看副檔名。內容和宣告的 `Content-Type` 對不上會拒絕；宣告成 `application/octet-stream` 時以內容為準。

人物照建議用單人、全身、光線清楚的正面或三分身。衣服照建議是單件、背景乾淨的商品圖。這支 API 不檢查姿勢，也不做內容審核。

### 這支 API 不做的事

不登入、不扣點、不查衣櫃、不提供歷史列表、不能改或刪某一筆、也沒有完成時的 webhook。工作紀錄和結果圖存在服務本機，由我們保管；合作方要自己保存下載到的圖。

同時處理的試穿有限。請求被接受只代表已排隊，不代表立刻開始畫。

## 認證

每次呼叫都要帶三個值，而且必須對上資料庫 `partnerapiclient` 的同一列：店家編號、店家名稱、金鑰。少一個、或任一個對不上，都不會建立試穿。

| 帶在哪 | 欄位 | 說明 |
| --- | --- | --- |
| 查詢字串 | `store_id` | 店家編號 |
| 查詢字串 | `store_name` | 店家名稱，要和資料庫裡的名稱完全一致 |
| 標頭 | `Authorization: Bearer <金鑰>` | 發給該店的金鑰 |

金鑰由我們產生後交給合作方。不要放進前端頁面或公開的 App。資料庫只存金鑰的 SHA-256，不存原文。

`GET /v1/health` 不用這三個值，只用來確認服務有沒有起來。

### 金鑰怎麼產生

`key_hash` 不是自己填的亂數。亂數是金鑰原文，`key_hash` 是這把原文算出來的結果。

新店家執行：

```bash
python -m clotheapi.issue "示範店"
```

這支指令做三件事：

1. 店家編號用隨機的 32 位十六進位字串，寫進 `partnerapiclient.id`。
2. 金鑰原文用 `secrets.token_urlsafe(32)` 產生。這把原文印在畫面上，交給店家，之後放在 `Authorization: Bearer …`。原文不寫進資料庫。
3. 把金鑰原文做 SHA-256，得到 64 位十六進位字串，寫進 `key_hash`。店家名稱寫進 `name`。

店家呼叫時，服務用 `store_id` 找到那一列，確認 `name` 和 `store_name` 完全一致、`revoked_at` 是空的，再把帶來的金鑰做一次 SHA-256，和 `key_hash` 比對。所以不能只在資料庫放一個亂數：沒有對應的原文，店家就沒有東西可以帶。金鑰原文只在產生的那一次看得到。

## 上下行格式

錯誤一律是 JSON：

```json
{ "detail": "店家名稱、編號或金鑰不符" }
```

成功建立或查詢試穿時，正文是同一個 JSON 物件。

### 試穿工作

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | string | 工作編號，32 位十六進位 |
| `status` | string | `pending`、`processing`、`completed`、`failed` |
| `engine` | string | 建立時指定的 `standard` 或 `premium` |
| `error` | string 或 null | 只有 `failed` 才有文字 |

### 建立試穿

`POST /v1/tryon`

上行 `Content-Type: multipart/form-data`。

| 欄位 | 必填 | 型別 | 說明 |
| --- | --- | --- | --- |
| `person_image` | 是 | 檔案 | 人物照 |
| `garment_image` | 是 | 檔案 | 衣服照 |
| `engine` | 否 | 文字 | 預設 `standard` |

下行 `202`，正文是試穿工作，此時 `status` 為 `pending`。

上行範例：

```http
POST /v1/tryon?store_id=8c1a0d5e2b7f4a6c9e0d1f2a3b4c5d6e&store_name=%E7%A4%BA%E7%AF%84%E5%BA%97 HTTP/1.1
Host: 127.0.0.1:8090
Authorization: Bearer sk_partner_example
Content-Type: multipart/form-data; boundary=----Boundary

------Boundary
Content-Disposition: form-data; name="person_image"; filename="person.jpg"
Content-Type: image/jpeg

<人物照二進位>
------Boundary
Content-Disposition: form-data; name="garment_image"; filename="garment.jpg"
Content-Type: image/jpeg

<衣服照二進位>
------Boundary
Content-Disposition: form-data; name="engine"

premium
------Boundary--
```

下行範例：

```http
HTTP/1.1 202 Accepted
Content-Type: application/json

{
  "id": "8c1a0d5e2b7f4a6c9e0d1f2a3b4c5d6e",
  "status": "pending",
  "engine": "premium",
  "error": null
}
```

被拒絕時不會建立工作。下行範例（`engine` 不合法）：

```http
HTTP/1.1 400 Bad Request
Content-Type: application/json

{ "detail": "engine 只接受 standard 或 premium" }
```

| HTTP | 何時 |
| --- | --- |
| 400 | 缺圖、空檔、不是 JPEG / PNG / WebP、格式與內容不符、`engine` 不是允許值 |
| 401 | 沒帶齊店家編號、店家名稱、金鑰，或三者對不上資料庫 |
| 413 | 單張超過 10MB |
| 503 | 服務端還沒設定可接受的金鑰 |

### 查詢狀態

`GET /v1/tryon/{id}`

上行只有路徑裡的工作編號和認證標頭，沒有正文。下行 `200`，正文是試穿工作。

上行範例：

```http
GET /v1/tryon/8c1a0d5e2b7f4a6c9e0d1f2a3b4c5d6e?store_id=8c1a0d5e2b7f4a6c9e0d1f2a3b4c5d6e&store_name=%E7%A4%BA%E7%AF%84%E5%BA%97 HTTP/1.1
Host: 127.0.0.1:8090
Authorization: Bearer sk_partner_example
```

下行範例（完成）：

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "id": "8c1a0d5e2b7f4a6c9e0d1f2a3b4c5d6e",
  "status": "completed",
  "engine": "premium",
  "error": null
}
```

下行範例（失敗）：

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "id": "8c1a0d5e2b7f4a6c9e0d1f2a3b4c5d6e",
  "status": "failed",
  "engine": "premium",
  "error": "premium 引擎逾時"
}
```

下行範例（編號不存在）：

```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{ "detail": "找不到這筆試穿" }
```

| HTTP | 何時 |
| --- | --- |
| 200 | 找得到這筆工作，含 `pending`、`processing`、`completed`、`failed` |
| 401 | 沒帶齊店家編號、店家名稱、金鑰，或三者對不上資料庫 |
| 404 | 編號不存在 |

### 下載結果

`GET /v1/tryon/{id}/result`

上行同樣只有路徑和認證標頭。下行 `200` 時正文是圖片位元組，不是 JSON。

| 標頭 | 值 |
| --- | --- |
| `Content-Type` | `image/png` |
| `Content-Disposition` | `attachment; filename="{id}.png"` |

上行範例：

```http
GET /v1/tryon/8c1a0d5e2b7f4a6c9e0d1f2a3b4c5d6e/result?store_id=8c1a0d5e2b7f4a6c9e0d1f2a3b4c5d6e&store_name=%E7%A4%BA%E7%AF%84%E5%BA%97 HTTP/1.1
Host: 127.0.0.1:8090
Authorization: Bearer sk_partner_example
```

下行範例：

```http
HTTP/1.1 200 OK
Content-Type: image/png
Content-Disposition: attachment; filename="8c1a0d5e2b7f4a6c9e0d1f2a3b4c5d6e.png"

<PNG 二進位>
```

下行範例（尚未完成）：

```http
HTTP/1.1 409 Conflict
Content-Type: application/json

{ "detail": "試穿尚未完成" }
```

編號不存在是 `404`。店家編號、名稱或金鑰不符是 `401`。

### 健康檢查

`GET /v1/health`

不用 API 金鑰。

上行範例：

```http
GET /v1/health HTTP/1.1
Host: 127.0.0.1:8090
```

下行範例：

```http
HTTP/1.1 200 OK
Content-Type: application/json

{ "status": "ok" }
```

## 串接方式

建議間隔 2 到 3 秒查一次狀態。`standard` 請等到 3 分鐘，`premium` 請等到 2 分鐘；超過仍是 `pending` 或 `processing` 就當成逾時，停止輪詢。看到 `completed` 再下載，看到 `failed` 就讀 `error`，不要呼叫結果網址。

`store_name=%E7%A4%BA%E7%AF%84%E5%BA%97` 就是「示範店」。查詢字串裡的店家名稱要做 URL 編碼。

```bash
curl -X POST "$BASE/v1/tryon?store_id=$STORE_ID&store_name=示範店" \
  -H "Authorization: Bearer $API_KEY" \
  -F "person_image=@person.jpg" \
  -F "garment_image=@garment.jpg" \
  -F "engine=standard"

curl "$BASE/v1/tryon/$JOB_ID?store_id=$STORE_ID&store_name=示範店" \
  -H "Authorization: Bearer $API_KEY"

curl -L "$BASE/v1/tryon/$JOB_ID/result?store_id=$STORE_ID&store_name=示範店" \
  -H "Authorization: Bearer $API_KEY" \
  -o result.png
```

### Python

```python
from clotheapi import ClotheClient

with ClotheClient("店家編號", "示範店", "合作方金鑰", base_url="https://試穿服務網址") as client:
    job = client.tryon("person.jpg", "garment.jpg", engine="premium")
    job.save("result.png")
```

`tryon` 會建立工作並每 2 秒查一次，預設最多等 180 秒。失敗或逾時丟出 `ClotheApiError`。若要自己決定輪詢，改呼叫 `create_tryon`，再用 `job.refresh()` 看狀態，完成後 `job.result_bytes()` 取圖。

圖也可以直接給 bytes，不一定是檔案路徑。

### TypeScript

客戶端在 `sdk/typescript/src/index.ts`，使用環境自帶的 `fetch`。

```ts
import { ClotheClient } from "./index";

const client = new ClotheClient("店家編號", "示範店", "合作方金鑰", "https://試穿服務網址");
const job = await client.tryon(personBlob, garmentBlob, "standard");
const image = await client.result(job.id);
```

`tryon` 同樣每 2 秒查一次，預設最多等 180 秒。未完成就抓 `result` 會丟出 `ClotheApiError`。

### 我們這邊怎麼啟動

給合作方串之前，服務要先設好環境變數再啟動：

| 變數 | 用途 |
| --- | --- |
| `DATABASE_URL` | 網站資料庫。店家憑證寫在 `partnerapiclient` |
| `OPENAI_API_KEY` | `standard` 使用 |
| `FASHN_API_KEY` | `premium` 使用 |
| `CLOTHE_PORT` | 預設 `8090` |
| `CLOTHE_DATA_DIR` | 工作與結果圖目錄，預設 `./clotheapi-data` |

新店家用 `python -m clotheapi.issue 店家名稱` 寫進資料庫。編號、金鑰原文和 `key_hash` 的演算法見上面「金鑰怎麼產生」。

`CLOTHE_API_MOCK=1` 不呼叫生成引擎，只回測試圖，用來確認串接流程。
