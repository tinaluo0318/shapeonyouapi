"""python examples/tryon.py person.jpg garment.jpg out.png"""

import sys

from clotheapi import ClotheClient


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("用法：python examples/tryon.py 人物照 衣服照 輸出路徑")
    person, garment, output = sys.argv[1:]
    with ClotheClient("店家編號", "店家名稱", "換成你的金鑰", base_url="http://127.0.0.1:8090") as client:
        job = client.tryon(person, garment, engine="standard")
        job.save(output)
        print(job.id, output)


if __name__ == "__main__":
    main()
