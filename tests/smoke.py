#!/usr/bin/env python3
"""Bounded behavior checks for the patched runtime, using only Python's stdlib."""

import json
import pathlib
import socket
import struct
import subprocess
import sys
import time


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)


def record(kind, body=b""):
    padding = (-len(body)) % 8
    return struct.pack("!BBHHBB", 1, kind, 1, len(body), padding, 0) + body + b"\0" * padding


def length(value):
    return bytes([value]) if value < 128 else struct.pack("!I", value | 0x80000000)


def read_exact(sock, count):
    result = b""
    while len(result) < count:
        part = sock.recv(count - len(result))
        if not part:
            raise ConnectionError("FPM closed the connection")
        result += part
    return result


def request(port, query="", cookie="", body=b"", content_type=""):
    params = {
        "SCRIPT_FILENAME": "/var/www/html/index.php",
        "SCRIPT_NAME": "/index.php",
        "REQUEST_METHOD": "POST" if body else "GET",
        "QUERY_STRING": query,
        "REQUEST_URI": "/index.php" + ("?" + query if query else ""),
        "SERVER_PROTOCOL": "HTTP/1.1",
        "GATEWAY_INTERFACE": "CGI/1.1",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
        "REMOTE_ADDR": "127.0.0.1",
        "HTTP_COOKIE": cookie,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
    }
    encoded = b""
    for key, value in params.items():
        key, value = key.encode(), value.encode()
        encoded += length(len(key)) + length(len(value)) + key + value
    data = record(1, struct.pack("!HB5x", 1, 0))
    data += record(4, encoded) + record(4) + record(5, body) + record(5)
    stdout, stderr = b"", b""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(data)
        while True:
            version, kind, request_id, size, padding, _ = struct.unpack("!BBHHBB", read_exact(sock, 8))
            assert version == 1 and request_id == 1
            payload = read_exact(sock, size)
            read_exact(sock, padding)
            if kind == 6:
                stdout += payload
            elif kind == 7:
                stderr += payload
            elif kind == 3:
                return stdout, stderr


def response_json(port, **kwargs):
    stdout, stderr = request(port, **kwargs)
    assert not stderr, stderr.decode(errors="replace")
    headers, body = stdout.split(b"\r\n\r\n", 1)
    assert b"Status: 500" not in headers, headers
    data = json.loads(body)
    assert data["version"] == "7.4.33", data
    assert data["sapi"] == "fpm-fcgi", data
    assert data["multipart_limit"] == "-1", data
    return data


def main():
    image = sys.argv[1]
    expected_sha = "712e60f9edfd03f0960fc4fc3c2c375f42b90aa2"
    metadata = json.loads(run("docker", "run", "--rm", "--entrypoint", "cat", image,
                              "/usr/local/share/php-backport/build-info.json").stdout)
    assert metadata["backport_commit"] == expected_sha, metadata
    run("docker", "run", "--rm", "--entrypoint", "php-fpm", image, "-t")
    code = '''
    if (PHP_VERSION !== "7.4.33" || ini_get("max_multipart_body_parts") === false) { exit(2); }
    foreach (["curl", "mbstring", "openssl", "PDO", "pdo_sqlite", "session", "sodium"] as $ext) {
        if (!extension_loaded($ext)) { fwrite(STDERR, "Missing extension: $ext"); exit(3); }
    }
    echo "CLI and base extensions OK\\n";
    '''
    print(run("docker", "run", "--rm", "--entrypoint", "php", image, "-r", code).stdout.strip())

    oom = subprocess.run(["docker", "run", "--rm", "--entrypoint", "php", image,
                          "-d", "memory_limit=16M", "-r",
                          "register_shutdown_function(function () { echo 'SHUTDOWN_CALLBACK_RAN'; }); "
                          "str_repeat('x', 32 * 1024 * 1024);"],
                         text=True, capture_output=True, timeout=30)
    assert oom.returncode == 1, (oom.returncode, oom.stdout, oom.stderr)
    assert "Allowed memory size" in oom.stderr, oom.stderr
    assert "SHUTDOWN_CALLBACK_RAN" not in oom.stdout, oom.stdout
    print("Patched CLI memory-exhaustion behavior OK")

    tests = pathlib.Path(__file__).resolve().parent
    container = run("docker", "run", "--detach", "--rm", "--publish", "127.0.0.1::9000",
                    "--mount", f"type=bind,src={tests},dst=/var/www/html,readonly", image).stdout.strip()
    try:
        inspect = json.loads(run("docker", "inspect", container).stdout)[0]
        port = int(inspect["NetworkSettings"]["Ports"]["9000/tcp"][0]["HostPort"])
        for attempt in range(30):
            try:
                first = response_json(port)
                break
            except (OSError, ConnectionError):
                if attempt == 29:
                    raise
                time.sleep(0.5)
        cookie = "PHPSESSID=" + first["session_id"]
        second = response_json(port, cookie=cookie)
        assert second["session_counter"] == 2, second
        form = response_json(port, body=b"smoke=form-ok", content_type="application/x-www-form-urlencoded")
        assert form["form_value"] == "form-ok", form
        multipart = (b"--smokeboundary\r\nContent-Disposition: form-data; name=\"smoke\"\r\n"
                     b"\r\nmultipart-ok\r\n--smokeboundary--\r\n")
        form = response_json(port, body=multipart, content_type="multipart/form-data; boundary=smokeboundary")
        assert form["form_value"] == "multipart-ok", form
        print("FPM requests, sessions, forms, and multipart parsing OK")
        try:
            stdout, stderr = request(port, query="oom=1")
            assert b"SHUTDOWN_CALLBACK_RAN" not in stdout, stdout
        except ConnectionError:
            pass  # The patched worker exits immediately, without FastCGI shutdown.
        for attempt in range(30):
            try:
                response_json(port)
                break
            except (OSError, ConnectionError):
                if attempt == 29:
                    raise
                time.sleep(0.5)
        logs = run("docker", "logs", container)
        assert "Allowed memory size" in logs.stdout + logs.stderr, (logs.stdout, logs.stderr)
        print("FPM remains available after bounded memory exhaustion")
    finally:
        logs = run("docker", "logs", container)
        print(logs.stdout + logs.stderr)
        run("docker", "stop", "--time", "5", container)


if __name__ == "__main__":
    main()
