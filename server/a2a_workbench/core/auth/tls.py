"""TLS client configuration from PEM material."""

import os
import ssl
import tempfile

import grpc

from a2a_workbench.core.auth.apply import TlsMaterial


def ssl_context(tls: TlsMaterial) -> ssl.SSLContext:
    """Return an SSL context presenting the client certificate and trusting ``ca_pem``.

    The PEMs pass through a private temporary directory that is removed once loaded.
    """
    context = (
        ssl.create_default_context(cadata=tls.ca_pem)
        if tls.ca_pem
        else ssl.create_default_context()
    )
    with tempfile.TemporaryDirectory() as tmp:
        os.chmod(tmp, 0o700)
        cert, key = os.path.join(tmp, "cert.pem"), os.path.join(tmp, "key.pem")
        for path, data in ((cert, tls.cert_pem), (key, tls.key_pem)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(data)
        context.load_cert_chain(cert, key)
    return context


def grpc_credentials(tls: TlsMaterial) -> grpc.ChannelCredentials:
    """Return gRPC channel credentials presenting the client certificate."""
    return grpc.ssl_channel_credentials(
        root_certificates=tls.ca_pem.encode() if tls.ca_pem else None,
        private_key=tls.key_pem.encode(),
        certificate_chain=tls.cert_pem.encode(),
    )
