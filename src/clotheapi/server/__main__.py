import os

import uvicorn

from clotheapi.server.app import create_app


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.environ.get("CLOTHE_HOST", "0.0.0.0"),
        port=int(os.environ.get("CLOTHE_PORT", "8090")),
    )


if __name__ == "__main__":
    main()
