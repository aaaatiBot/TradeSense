import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app

def test_live_health():
    app = create_app("development")
    client = app.test_client()
    response = client.get("/api/v1/health")
    print(f"HTTP Status: {response.status_code}")
    print("Response Headers:")
    for header, value in response.headers.items():
        if header in ["Content-Type", "X-Request-ID"]:
            print(f"  {header}: {value}")
    print("\nResponse Body:")
    print(json.dumps(response.get_json(), indent=2))

if __name__ == "__main__":
    test_live_health()
