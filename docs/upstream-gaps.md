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

## `AuthInterceptor` covers only some security schemes and one scheme per requirement
- Where: SDK (`a2a-python` 1.2.2, `a2a/client/auth/interceptor.py`)
- Missing: the interceptor walks `security_requirements` and returns after applying the **first** scheme it has a credential for, so an AND requirement (`{"apiKey": [], "oauth2": ["read"]}`) sends only one of the two. It handles HTTP Bearer, OAuth 2.0 / OIDC (as Bearer) and API keys in a header; HTTP Basic is not handled, and API keys in a query parameter or cookie are skipped (the source says so). Skill-level `security_requirements` are not considered, and mutual TLS has no client-side hook.
- Why we need it: connecting to agents protected by any scheme the spec defines, with AND requirements, as A2A §4.5 and §7.3 describe. The Workbench applies credentials itself, through the SDK's own `ClientCallContext.service_parameters` for headers, and through the transports it already supplies (`ClientConfig.httpx_client` query parameters and TLS, `grpc_channel_factory` credentials).
- Proposal: (1) apply every scheme of the first satisfiable requirement (OR across requirements, AND inside one); (2) add HTTP Basic (`CredentialService` returning user/password), API key in query and cookie; (3) accept an optional skill id to evaluate skill-level requirements; (4) document mTLS as transport configuration (`httpx_client` / channel credentials).
- Status: open.
