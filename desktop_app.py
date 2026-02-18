#!/usr/bin/env python3
"""
Majic Movie Selector - Desktop App
Launches the web app in a native window using PyWebView.
"""

import sys
import time
import threading
import socket

import webview
import uvicorn


def is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_server(port: int):
    """Start the FastAPI server."""
    from app.main import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()


def wait_for_server(port: int, timeout: int = 30):
    """Wait for the server to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        if is_port_in_use(port):
            return True
        time.sleep(0.1)
    return False


def main():
    port = 8443
    url = f"http://127.0.0.1:{port}"

    # Check if server is already running
    server_was_running = is_port_in_use(port)

    if not server_was_running:
        # Start server in background thread
        print(f"Starting Majic server on port {port}...")
        server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
        server_thread.start()

        # Wait for server to be ready
        if not wait_for_server(port):
            print("Error: Server failed to start")
            sys.exit(1)

        print("Server ready!")
    else:
        print(f"Using existing server on port {port}")

    # Create native window
    window = webview.create_window(
        title="Majic Movie Selector",
        url=url,
        width=1400,
        height=900,
        min_size=(800, 600),
        background_color="#0d0d15",
        text_select=True,
    )

    # Start the GUI (blocks until window is closed)
    webview.start()

    print("Window closed. Goodbye!")


if __name__ == "__main__":
    main()
