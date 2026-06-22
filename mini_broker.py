#!/usr/bin/env python3
"""
mini_broker.py  -  Broker MQTT minimo (v3.1.1) en Python puro.
==================================================================
NO es para produccion. Solo implementa lo justo para que Federer y el
panel web se conecten y enruten mensajes en localhost:1883 sin instalar
Mosquitto (util para lanzar la UI / tomar screenshots sin nodos reales).

Soporta: CONNECT/CONNACK, PUBLISH (QoS0/1 + PUBACK), SUBSCRIBE/SUBACK,
UNSUBSCRIBE/UNSUBACK, PINGREQ/PINGRESP, DISCONNECT. Comodines + y #.
Uso:  python mini_broker.py [--port 1883]
"""
import socket, struct, threading, sys

HOST, PORT = "0.0.0.0", 1883

clients = {}            # conn -> set(subscripciones)
clients_lock = threading.Lock()


def _read_remaining_length(sock):
    mult, val = 1, 0
    while True:
        b = sock.recv(1)
        if not b:
            return None
        byte = b[0]
        val += (byte & 0x7F) * mult
        if (byte & 0x80) == 0:
            break
        mult *= 128
    return val


def _read_n(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _encode_len(n):
    out = b""
    while True:
        d = n % 128
        n //= 128
        if n > 0:
            d |= 0x80
        out += bytes([d])
        if n == 0:
            break
    return out


def _topic_matches(filt, topic):
    f, t = filt.split("/"), topic.split("/")
    i = 0
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t):
            return False
        if part != "+" and part != t[i]:
            return False
    return len(f) == len(t)


def _route(topic, payload):
    with clients_lock:
        targets = [(c, subs) for c, subs in clients.items()]
    for conn, subs in targets:
        if any(_topic_matches(f, topic) for f in subs):
            pkt = bytearray([0x30])
            body = struct.pack("!H", len(topic)) + topic.encode() + payload
            pkt += _encode_len(len(body)) + body
            try:
                conn.sendall(pkt)
            except OSError:
                pass


def handle(conn, addr):
    with clients_lock:
        clients[conn] = set()
    try:
        while True:
            h = conn.recv(1)
            if not h:
                break
            ptype = h[0] >> 4
            flags = h[0] & 0x0F
            rl = _read_remaining_length(conn)
            if rl is None:
                break
            body = _read_n(conn, rl) if rl else b""
            if body is None:
                break

            if ptype == 1:          # CONNECT
                conn.sendall(bytes([0x20, 0x02, 0x00, 0x00]))   # CONNACK ok
            elif ptype == 3:        # PUBLISH
                tlen = struct.unpack("!H", body[:2])[0]
                topic = body[2:2 + tlen].decode("utf-8", "replace")
                rest = body[2 + tlen:]
                qos = (flags >> 1) & 0x03
                if qos > 0:
                    pid = rest[:2]
                    payload = rest[2:]
                    conn.sendall(bytes([0x40, 0x02]) + pid)     # PUBACK
                else:
                    payload = rest
                _route(topic, payload)
            elif ptype == 8:        # SUBSCRIBE
                pid = body[:2]
                i, codes = 2, b""
                while i < len(body):
                    flen = struct.unpack("!H", body[i:i + 2])[0]
                    i += 2
                    filt = body[i:i + flen].decode("utf-8", "replace")
                    i += flen
                    i += 1          # requested qos byte
                    with clients_lock:
                        clients[conn].add(filt)
                    codes += bytes([0x00])  # granted QoS 0
                conn.sendall(bytes([0x90]) + _encode_len(2 + len(codes)) + pid + codes)
            elif ptype == 10:       # UNSUBSCRIBE
                pid = body[:2]
                conn.sendall(bytes([0xB0, 0x02]) + pid)         # UNSUBACK
            elif ptype == 12:       # PINGREQ
                conn.sendall(bytes([0xD0, 0x00]))               # PINGRESP
            elif ptype == 14:       # DISCONNECT
                break
    except OSError:
        pass
    finally:
        with clients_lock:
            clients.pop(conn, None)
        try:
            conn.close()
        except OSError:
            pass


def main():
    port = PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(50)
    print(f"[mini-broker] MQTT escuchando en {HOST}:{port} (Ctrl+C para salir)")
    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=handle, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[mini-broker] adios.")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
