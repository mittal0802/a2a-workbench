# Upstream gaps

Things A2A Workbench needs that the official SDK (`a2aproject/a2a-python`) or the
A2A specification (`a2aproject/A2A`) does not provide. We never work around these
locally; each entry becomes an upstream issue, PR or proposal once approved.

Entry format:

```
## <short title>
- Where: SDK | spec
- Missing: what is not there today
- Why we need it: the Workbench feature it blocks
- Proposal: the API or spec change we would propose
- Status: open | proposed (<link>) | merged (<link>)
```

## Importing `a2a.compat.v0_3.grpc_handler` first disables the v0.3 gRPC client
- Where: SDK (`a2a-python` 1.2.2)
- Missing: `a2a/client/client_factory.py` wraps `from a2a.compat.v0_3.grpc_transport import CompatGrpcTransport` in `try/except ImportError`. When `a2a.compat.v0_3.grpc_handler` is imported before `a2a.client`, the circular import makes that import fail, the factory silently sets `CompatGrpcTransport = None`, and v0.3 gRPC agents are then called on the v1.0 service (`lf.a2a.v1.A2AService/*`) and answer UNIMPLEMENTED.
- Why we need it: one process that serves a v0.3 gRPC agent (the zoo) and acts as a client.
- Proposal: break the cycle (import the compat transport lazily inside the gRPC producer) and stop treating a circular-import `ImportError` as "grpc extras not installed".
- Status: open. Workaround: `a2a_workbench/fixtures/zoo.py` imports `a2a.client` first.
