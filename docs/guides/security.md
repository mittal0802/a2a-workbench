# Security and sign-in

The Security tab (and `a2a-workbench auth …`, and the MCP `auth_*` tools) reads the agent card's `securitySchemes` and `securityRequirements`, including skill-level requirements, and applies them exactly as declared:

| Scheme | How you sign in | How it is sent |
|---|---|---|
| API key | paste the key | header, query parameter or cookie, as the card says |
| HTTP Basic / Bearer | username and password, or a token | `Authorization` header |
| OAuth 2.0 client credentials, password | client ID and secret (and username/password) | `Authorization: Bearer`, renewed before expiry |
| OAuth 2.0 authorization code | browser sign-in with PKCE (S256) | same |
| OAuth 2.0 device code | a code you enter on another device | same |
| OAuth 2.0 implicit (deprecated) | browser sign-in | same |
| OpenID Connect | browser sign-in via the discovery document | same |
| Mutual TLS | client certificate and key (PEM) | presented on the TLS connection (HTTP and gRPC) |

Requirements are evaluated as the spec defines them: the alternatives are OR, the schemes inside one alternative are AND and are all sent together. OAuth endpoints missing from the card are discovered from `oauth2MetadataUrl` (RFC 8414) or the OpenID configuration. When a sign-in fails, the provider's error is shown along with what its published metadata says it supports.

For browser sign-in, register `http://127.0.0.1:8484/oauth/callback` (web UI) or `http://127.0.0.1:8765/oauth/callback` (CLI, `--redirect-port`) as a redirect URI with the provider.

```bash
a2a-workbench auth status "My agent"
A2AW_API_KEY=… a2a-workbench auth set "My agent" apiKey
A2AW_CLIENT_SECRET=… a2a-workbench auth login "My agent" oauth --client-id "$ID" --scope a2a:invoke
a2a-workbench auth login "My agent" oauthCode --client-id "$ID"       # opens your browser
a2a-workbench auth probe "My agent" --json                             # is it enforced?
a2a-workbench auth logout "My agent" oauth
```

Secrets never need to be command-line arguments (which end up in shell history and `ps`): use `A2AW_API_KEY`, `A2AW_TOKEN`, `A2AW_ACCESS_TOKEN`, `A2AW_PASSWORD` or `A2AW_CLIENT_SECRET`, or pass `-` to read the value from standard input.

**Is it enforced?** The probe calls `GetTask` with a random task ID three times: with no credentials, with wrong ones and with yours. An agent that answers the first two with anything but an authentication error does not enforce what its card declares.

Credentials are encrypted at rest (AES-GCM) with `A2AW_SECRET_KEY`, or a key generated in `~/.a2a-workbench/secret.key` (mode 0600). They are never logged, never returned by the API (only masked previews such as `••••a91`), and redacted in every recorded exchange.
