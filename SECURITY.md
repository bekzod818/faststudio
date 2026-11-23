# Security Policy

FastStudio guards administrative access to application data, so we take
security reports seriously.

## Supported versions

| Version | Supported |
|---|---|
| latest `0.x` minor | yes |
| older `0.x` | no (please upgrade) |

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private vulnerability reporting:
<https://github.com/bekzod818/faststudio/security/advisories/new>

Please include affected version, a description, reproduction steps or a
proof of concept, and the impact you believe it has.

What to expect:

- Acknowledgement within **3 business days**.
- An initial assessment within **7 days**.
- A fix and coordinated disclosure, normally within **90 days**; we credit
  reporters in the advisory unless you prefer otherwise.

## Scope

In scope: authentication, session and CSRF handling, authorization of admin
API routes, SQL/query injection, mass assignment, XSS in the admin UI,
security headers, and the integrity of published packages.

Out of scope: vulnerabilities in applications that misconfigure FastStudio
against documented guidance (for example `secure_cookies=False` in production),
and issues in third-party dependencies already tracked upstream.

See [docs/threat-model.md](docs/threat-model.md) for the protections FastStudio
provides and their limits.
