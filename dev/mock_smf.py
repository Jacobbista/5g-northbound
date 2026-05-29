"""Minimal SMF stub — stdlib only, no pip install required."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

SESSIONS = {
    "sessions": [
        {
            "imsi": "001010123456786",
            "dnn": "internet",
            "ipv4": "10.45.0.3",
            "ipv6": "",
            "snssai": {"sst": 1, "sd": "000001"},
            "up_cnx_state": "NULL",
        },
        {
            "imsi": "001010123456787",
            "dnn": "internet",
            "ipv4": "10.45.0.4",
            "ipv6": "",
            "snssai": {"sst": 1, "sd": "000001"},
            "up_cnx_state": "ACTIVATED",
        },
    ]
}

PAYLOAD = json.dumps(SESSIONS).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/session-info":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        print(f"mock-smf {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 9090), Handler)
    print("mock-smf listening on :9090")
    server.serve_forever()
