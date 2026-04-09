import sys
import os
from pywinauto import Application, Desktop

def test_connection():
    path = r"C:\Program Files\Notepad++\notepad++.exe"
    title_re = r".*Notepad\+\+.*"  # Raw string
    
    print(f"Testing connection to: {path}")
    
    # 1. Try by path
    try:
        app = Application(backend="uia").connect(path=path)
        print("SUCCESS: Connected by path")
        print(f"Windows: {[w.window_text() for w in app.windows()]}")
        return
    except Exception as e:
        print(f"FAILED: Connection by path: {e}")

    # 2. Try by title_re (Desktop level)
    try:
        app = Application(backend="uia").connect(title_re=title_re, timeout=5)
        print("SUCCESS: Connected by title_re")
        print(f"Windows: {[w.window_text() for w in app.windows()]}")
        return
    except Exception as e:
        print(f"FAILED: Connection by title_re: {e}")

    # 3. List all windows for debugging
    print("\nAvailable windows on Desktop:")
    for w in Desktop(backend="uia").windows():
        if w.window_text():
            print(f"- {w.window_text()}")

if __name__ == "__main__":
    test_connection()
