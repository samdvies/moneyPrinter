"""Entry point: launch the dashboard service with uvicorn."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "dashboard.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8080,
        reload=False,
    )
