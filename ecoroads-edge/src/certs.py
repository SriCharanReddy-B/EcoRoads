"""
Self-signed HTTPS certificate for the phone bridge.

Phone browsers only give a web page camera + GPS access over HTTPS.
We don't own a domain or a real certificate for a laptop on a hotspot,
so we make our own once and store it in ecoroads-edge/certs/. The phone
warns about it the first time; after "Proceed" it remembers.

The certificate lists the laptop's current IP addresses. If you join a
different network and the laptop's IP changes, a new one is generated
automatically (and the phone warns once more).
"""

import datetime
import ipaddress
import json
import socket
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent.parent / "certs"


def local_ipv4_addresses():
    ips = set()
    try:  # address of the interface that would be used for outbound traffic
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # no packet is actually sent
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.discard("0.0.0.0")
    real = sorted(ip for ip in ips if not ip.startswith("127."))
    return real or ["127.0.0.1"]


def ensure_certificate(cert_dir=CERT_DIR):
    cert_dir = Path(cert_dir)
    cert, key, meta = cert_dir / "phone_bridge.crt", cert_dir / "phone_bridge.key", cert_dir / "ips.json"
    ips = local_ipv4_addresses()
    if cert.exists() and key.exists() and meta.exists():
        if set(ips) <= set(json.loads(meta.read_text())):
            return str(cert), str(key)

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        raise SystemExit("The phone bridge needs the 'cryptography' package:  pip install cryptography")

    cert_dir.mkdir(parents=True, exist_ok=True)
    pkey = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EcoRoads edge node")])
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(ip))
                                         for ip in set(ips) | {"127.0.0.1"}]
    now = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder()
         .subject_name(name).issuer_name(name)
         .public_key(pkey.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(now - datetime.timedelta(days=1))
         .not_valid_after(now + datetime.timedelta(days=825))
         .add_extension(x509.SubjectAlternativeName(san), critical=False)
         .sign(pkey, hashes.SHA256()))
    key.write_bytes(pkey.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    meta.write_text(json.dumps(ips))
    print(f"[bridge] created HTTPS certificate for {', '.join(ips)}")
    return str(cert), str(key)
