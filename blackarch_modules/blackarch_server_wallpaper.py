#!/usr/bin/env python3
import http.server, os, socketserver, sys
from pathlib import Path

def main(argv=None):
    os.chdir(Path.home() / ".local/state/blackarch/current")
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", 8000), handler) as httpd:
        print("Serving on port 8000...")
        httpd.serve_forever()
    return 0

if __name__ == "__main__":
    sys.exit(main())
