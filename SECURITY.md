# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's [private vulnerability reporting](https://github.com/mittal0802/a2a-workbench/security/advisories/new). Do not open a public issue.

Include what is affected, how to reproduce it, and the impact you see.

## Supported versions

Security fixes go into the latest release.

## Scope notes

The Workbench is a local developer tool with no sign-in of its own: anyone who can reach its port can use it, including the credentials it stores. Keep it on `127.0.0.1` (with Docker, `-p 127.0.0.1:8484:8484`) or behind your own access control. Its host and `Origin` checks protect against DNS rebinding from web pages you visit; they are not a network boundary. Stored credentials are encrypted with `A2AW_SECRET_KEY` (or a generated key in the home directory), never logged and redacted in recorded traffic.
