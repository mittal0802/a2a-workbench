import subprocess
import sys


def test_importing_the_zoo_first_keeps_legacy_grpc_client_available():
    code = (
        "import a2a_workbench.fixtures.zoo\n"
        "import a2a.client.client_factory as f\n"
        "assert f.CompatGrpcTransport is not None, 'compat gRPC transport disabled'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
