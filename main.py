import sys
import os

sys.path.insert(0, "/home/runner/workspace")

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("bot.server:web", host="0.0.0.0", port=port)
