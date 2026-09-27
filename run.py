import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
