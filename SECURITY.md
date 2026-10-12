# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's [private vulnerability reporting](https://github.com/mittal0802/a2a-workbench/security/advisories/new). Do not open a public issue.

Include what is affected, how to reproduce it, and the impact you see.

## Supported versions

Security fixes go into the latest release.

## Scope notes

The Workbench is a local developer tool: it answers only to local host names, has no sign-in of its own, and should not be exposed to an untrusted network. Stored credentials are encrypted with `A2AW_SECRET_KEY` (or a generated key in the home directory), never logged and redacted in recorded traffic.
