import requests
import json

url = "http://localhost:8000/mcp"
payload = {
    "jsonrpc": "2.0",
    "method": "tools/list",
    "params": {},
    "id": 1
}

headers = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json"
}

with open("debug_log.txt", "w", encoding="utf-8") as log:
    try:
        # 1. Get Session ID
        res1 = requests.post(url, headers=headers, timeout=10)
        session_id = res1.headers.get("mcp-session-id")
        log.write(f"Session ID: {session_id}\n")
        
        if session_id:
            # 2. Try Headers
            log.write("Trying mcp-session-id header...\n")
            h2 = headers.copy()
            h2["mcp-session-id"] = session_id
            res2 = requests.post(url, json=payload, headers=h2, timeout=10)
            log.write(f"Header result: {res2.status_code} {res2.text[:100]}\n")
            
            # 3. Try sessionId query
            log.write("Trying sessionId query...\n")
            res3 = requests.post(f"{url}?sessionId={session_id}", json=payload, headers=headers, timeout=10)
            log.write(f"sessionId query result: {res3.status_code} {res3.text[:100]}\n")
            
            # 4. Try session_id query
            log.write("Trying session_id query...\n")
            res4 = requests.post(f"{url}?session_id={session_id}", json=payload, headers=headers, timeout=10)
            log.write(f"session_id query result: {res4.status_code} {res4.text[:100]}\n")
            
    except Exception as e:
        log.write(f"Error: {e}\n")
