import socket
import threading
import time
import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.network_utils import kill_process_on_port

def start_dummy_server(port):
    """Starts a dummy server that listens on the given port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', port))
        s.listen()
        print(f"Dummy server started on port {port} (PID: {os.getpid()})")
        while True:
            conn, addr = s.accept()
            with conn:
                pass

if __name__ == "__main__":
    TEST_PORT = 9999
    
    # 1. Start a dummy server in a separate process or thread
    # Since we want to test killing a process, we should start it in a way that it has its own PID if possible, 
    # but for simplicity of the test script, we'll just check if we can kill a socket held by another process if we had one.
    # Actually, let's just use subprocess to start another instance of this script as a dummy server.
    
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        start_dummy_server(TEST_PORT)
    else:
        import subprocess
        
        print("Starting dummy server process...")
        server_proc = subprocess.Popen([sys.executable, __file__, "--server"])
        time.sleep(2) # Wait for it to bind
        
        print(f"Verifying port {TEST_PORT} is in use...")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', TEST_PORT))
                print("Error: Port is NOT in use as expected.")
                server_proc.terminate()
                sys.exit(1)
            except OSError:
                print("Confirmed: Port is in use.")
        
        print(f"Attempting to kill process on port {TEST_PORT}...")
        success = kill_process_on_port(TEST_PORT)
        
        if success:
            print("Kill utility reported success.")
            time.sleep(1) # Wait for OS to release socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('127.0.0.1', TEST_PORT))
                    print("SUCCESS: Port is now free!")
                except OSError as e:
                    print(f"FAILURE: Port is still in use. Error: {e}")
                    sys.exit(1)
        else:
            print("Kill utility reported failure.")
            sys.exit(1)
        
        print("Verification complete.")
