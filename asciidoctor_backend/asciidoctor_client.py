# asciidoctor_backend/asciidoctor_client.py

"""
Client for communicating with the long-running AsciiDoctor server
"""

import json
import logging
import pathlib
import socket
import struct
import subprocess
import time
from typing import Dict, Optional

log = logging.getLogger("mkdocs.plugins.asciidoctor_backend.server")


class AsciidoctorServerClient:
    def __init__(self, socket_path: str = "/tmp/asciidoctor.sock",
                 server_script: Optional[pathlib.Path] = None,
                 auto_start: bool = True):
        self.socket_path = socket_path
        self.server_script = server_script
        self.auto_start = auto_start
        self._server_process = None

    def __enter__(self):
        if self.auto_start:
            self.ensure_server_running()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.auto_start and self._server_process:
            self.shutdown_server()

    def ensure_server_running(self, max_retries: int = 3):
        """Ensure the server is running, start it if necessary."""
        if self._is_server_alive():
            log.info("AsciiDoctor backend server ready - watching for AsciiDoc changes...")
            return

        if not self.server_script:
            raise RuntimeError("Server script path not provided")

        log.info("Starting AsciiDoctor backend server...")

        # Start the server
        self._server_process = subprocess.Popen(
            ["ruby", str(self.server_script), self.socket_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Wait for server to be ready
        for _ in range(max_retries):
            time.sleep(0.2)
            if self._is_server_alive():
                log.info("AsciiDoctor backend server ready - watching for AsciiDoc changes...")
                return

        raise RuntimeError("Failed to start AsciiDoctor backend server")

    def _is_server_alive(self) -> bool:
        """Check if the server is responding."""
        try:
            response = self._send_request({"action": "ping"}, timeout=1.0)
            return response.get("status") == "ok"
        except (ConnectionRefusedError, FileNotFoundError, OSError, TimeoutError):
            return False

    def convert_file(self, file_path: pathlib.Path,
        safe_mode: str = "safe",
        attributes: Optional[Dict] = None,
        requires: Optional[list] = None,
        base_dir: Optional[pathlib.Path] = None) -> Dict:
        """Convert an AsciiDoc file using the server."""
        options = {
            "safe_mode": safe_mode,
            "attributes": attributes or {},
        }

        if requires:
            options["requires"] = requires

        if base_dir:
            options["base_dir"] = str(base_dir)

        request = {
            "action": "convert",
            "file_path": str(file_path),
            "options": options
        }

        return self._send_request(request)

    def shutdown_server(self):
        """Request the server to shut down."""
        try:
            self._send_request({"action": "shutdown"}, timeout=1.0)
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            pass

        if self._server_process:
            try:
                self._server_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
                self._server_process.wait()
            self._server_process = None

    def _send_request(self, request: Dict, timeout: float = 30.0) -> Dict:
        """Send a request to the server and return the response."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            sock.connect(self.socket_path)

            # Send request
            request_json = json.dumps(request).encode('utf-8')
            length = struct.pack('!I', len(request_json))
            sock.sendall(length + request_json)

            # Receive response length
            length_bytes = sock.recv(4)
            if not length_bytes:
                raise ConnectionError("Server closed connection")

            response_length = struct.unpack('!I', length_bytes)[0]

            # Receive response
            response_data = b''
            while len(response_data) < response_length:
                chunk = sock.recv(min(4096, response_length - len(response_data)))
                if not chunk:
                    raise ConnectionError("Incomplete response from server")
                response_data += chunk

            response = json.loads(response_data.decode('utf-8'))

            if response.get("status") == "error":
                raise RuntimeError(f"Server error: {response.get('message')}")

            return response

        finally:
            sock.close()
