"""Start local FastAPI dashboard (paper only).

Default bind 127.0.0.1:8080 for local use.
In Docker set HOST=0.0.0.0 (see docker-compose.yml).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1") or "127.0.0.1"
    port = int(os.getenv("PORT", "8080") or "8080")
    uvicorn.run(
        "api.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())