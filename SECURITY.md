# Security Policy

## Supported versions

Security fixes are applied to the current **V19** release line on `master` and the matching packages on [PyPI](https://pypi.org/project/rsna-anonymizer/) (latest `19.x`).

Older major versions are **not** supported.

## How to report a vulnerability

Please **do not** open a public GitHub issue for an unfixed vulnerability.

1. Prefer GitHub **Private vulnerability reporting** / Security Advisories:  
   https://github.com/RSNA/anonymizer/security/advisories/new
2. If that is unavailable, email the maintainer: **michael@dx.life**

Include enough detail to reproduce the issue (affected version, environment, and steps). We will acknowledge reports within **5 business days** and coordinate disclosure after a fix or mitigation is available.

## Scope

**In scope (examples):**

- Bugs that could leak or mishandle PHI during anonymization, import, export, or send
- Credential / token handling issues in send and cloud export paths
- Supply-chain issues in the published `rsna-anonymizer` package and its declared dependencies

**Out of scope (examples):**

- Local misconfiguration (AE Titles, network allow-lists, project folders)
- Third-party TotalSegmentator academic-license side channels
- Issues that exist only in deleted or experimental prototyping trees and do not ship in the published package
