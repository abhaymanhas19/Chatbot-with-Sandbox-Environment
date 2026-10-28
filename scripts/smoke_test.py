"""Run against the real services and Docker after completing README setup."""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"
EXECUTOR = "http://127.0.0.1:8001"


def get(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def chat(code):
    payload = json.dumps({"message": "Run this Python", "mode": "demo", "code": code}).encode()
    request = urllib.request.Request(
        BASE + "/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    assert get(EXECUTOR + "/ready")["status"] == "ready"
    assert get(BASE + "/health")["status"] == "ok"
    success = chat("print(2 + 2)")
    assert success["execution"]["exit_code"] == 0, success
    assert success["answer"] == "4\n", success

    readonly = chat("open('/probe', 'w').write('x')")
    assert readonly["execution"]["exit_code"] != 0, readonly
    assert "Read-only file system" in readonly["execution"]["stderr"], readonly

    network = chat("import socket\ntry:\n socket.create_connection(('1.1.1.1', 80), timeout=1)\n print('network available')\nexcept OSError:\n print('network blocked')")
    assert network["answer"] == "network blocked\n", network

    timeout = chat("while True: pass")
    assert timeout["execution"]["timed_out"] is True, timeout
    print("PASS: services, execution, read-only filesystem, network isolation, timeout")


if __name__ == "__main__":
    main()
