import requests
import json
import time

url = "http://localhost:8000/mcp"
payload = {
    "jsonrpc": "2.0",
    "method": "tools/list",
    "params": {},
    "id": 1
}

def test_headers(headers):
    print(f"Testing with headers: {headers}")
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10, stream=True)
        print(f"Status: {response.status_code}")
        print(f"Full Headers: {dict(response.headers)}")
        if response.status_code == 200:
            count = 0
            for line in response.iter_lines():
                if line:
                    print(f"Line {count}: {line.decode('utf-8')[:200]}")
                    count += 1
                    if count >= 5: break
    except Exception as e:
        print(f"Error: {e}")
    print("-" * 20)

print("Diagnostic Start")
test_headers({"Content-Type": "application/json"})
test_headers({"Content-Type": "application/json", "Accept": "application/json"})
test_headers({"Content-Type": "application/json", "Accept": "*/*"})
test_headers({"Content-Type": "application/json", "Accept": "text/event-stream"})
