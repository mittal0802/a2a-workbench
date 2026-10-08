"""A throwaway certificate authority with server and client certificates for mTLS tests."""

import datetime
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass
class TestPki:
    """PEM strings of the CA and the two leaf certificates, plus their file paths."""

    ca_cert: str
    server_cert: str
    server_key: str
    client_cert: str
    client_key: str
    ca_path: Path
    server_cert_path: Path
    server_key_path: Path


def _key_pem(key: ec.EllipticCurvePrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def _cert(
    subject: str,
    key: ec.EllipticCurvePrivateKey,
    issuer: x509.Name,
    issuer_key: ec.EllipticCurvePrivateKey,
    *,
    ca: bool = False,
    usage: list[x509.ObjectIdentifier] | None = None,
    server: bool = False,
) -> x509.Certificate:
    now = datetime.datetime.now(datetime.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False,
        )
    )
    if ca:
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    if usage:
        builder = builder.add_extension(x509.ExtendedKeyUsage(usage), critical=False)
    if server:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(IPv4Address("127.0.0.1"))]
            ),
            critical=False,
        )
    return builder.sign(issuer_key, hashes.SHA256())


def make_test_pki(directory: Path) -> TestPki:
    """Create a CA, a server certificate for 127.0.0.1/localhost and a client certificate."""
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "A2A Workbench test CA")])
    ca = _cert("A2A Workbench test CA", ca_key, ca_name, ca_key, ca=True)
    server_key = ec.generate_private_key(ec.SECP256R1())
    server = _cert(
        "127.0.0.1",
        server_key,
        ca_name,
        ca_key,
        usage=[ExtendedKeyUsageOID.SERVER_AUTH],
        server=True,
    )
    client_key = ec.generate_private_key(ec.SECP256R1())
    client = _cert(
        "zoo-client", client_key, ca_name, ca_key, usage=[ExtendedKeyUsageOID.CLIENT_AUTH]
    )
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM).decode()  # noqa: E731
    directory.mkdir(parents=True, exist_ok=True)
    paths = {"ca.pem": pem(ca), "server.pem": pem(server), "server.key": _key_pem(server_key)}
    for name, text in paths.items():
        (directory / name).write_text(text)
    return TestPki(
        ca_cert=pem(ca),
        server_cert=pem(server),
        server_key=_key_pem(server_key),
        client_cert=pem(client),
        client_key=_key_pem(client_key),
        ca_path=directory / "ca.pem",
        server_cert_path=directory / "server.pem",
        server_key_path=directory / "server.key",
    )
