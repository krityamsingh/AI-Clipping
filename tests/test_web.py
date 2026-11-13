"""
Web Interface Test
Verifies FastAPI routes, health check, video listing, and export serving.
"""

import sys
from pathlib import Path
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from web.app import app

client = TestClient(app)


def test_web_routes():
    print("Testing GET / (Home page)... ", end="")
    res = client.get("/")
    assert res.status_code == 200
    assert "AI Video Clipping Engine" in res.text
    print("PASS")

    print("Testing GET /api/health... ", end="")
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    print(f"PASS (CPU Cores: {data['cpu_cores']}, Threads: {data['cpu_threads_configured']})")

    print("Testing GET /api/raw-videos... ", end="")
    res = client.get("/api/raw-videos")
    assert res.status_code == 200
    assert "videos" in res.json()
    print("PASS")

    print("Testing GET /api/exports... ", end="")
    res = client.get("/api/exports")
    assert res.status_code == 200
    assert "clips" in res.json()
    print("PASS")

    print("Testing POST /api/analyze-style... ", end="")
    res = client.post("/api/analyze-style")
    assert res.status_code == 200
    assert "markdown" in res.json()
    print("PASS")


if __name__ == "__main__":
    print("--- RUNNING WEB INTERFACE TESTS ---")
    test_web_routes()
    print("--- ALL WEB TESTS PASSED ---")
