from __future__ import annotations

import uvicorn

from .app import create_app


def main() -> None:
    print("Competitive Intelligence Agent is running")
    print("Open: http://127.0.0.1:8000")
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
