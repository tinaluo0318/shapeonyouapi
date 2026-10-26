"""發給一組店家憑證：python -m clotheapi.issue 店家名稱"""

import os
import sys

from clotheapi.partners import PartnerDirectory, PartnerStoreError


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("用法：python -m clotheapi.issue 店家名稱")
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("請先設定 DATABASE_URL，店家憑證寫進這個資料庫")
    try:
        store_id, api_key = PartnerDirectory(database_url).issue(sys.argv[1])
    except PartnerStoreError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"store_id={store_id}")
    print(f"store_name={sys.argv[1].strip()}")
    print(f"api_key={api_key}")


if __name__ == "__main__":
    main()
