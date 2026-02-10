# Security Policy

## Supported Versions

Only the latest release is supported with security fixes.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security reports.**

Please report vulnerabilities privately through
[GitHub Security Advisories](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository (*Security > Advisories > New draft advisory*). This keeps the
report private until a fix is available.

If advisories are not enabled, contact the maintainer directly via the email
address listed on their GitHub profile.

### What to include

- Receipt Designer version (see `receipt_designer/__init__.py`).
- Operating system and Python version.
- Steps to reproduce the issue.
- Any relevant logs or error output.
- A proof-of-concept, if it can be shared safely.

## What to expect

This is a volunteer-maintained project. We will make a best-effort attempt to
acknowledge reports promptly and address confirmed issues in a timely manner,
but we cannot guarantee specific response times.

We prefer coordinated disclosure — please give us reasonable time to release a
fix before publishing details. Reporters will be credited in the release notes
unless they prefer to remain anonymous.

## Scope

Receipt Designer is a desktop application. Typical areas of concern include:

- Malicious template files (`.receipt` / `.json`) causing unexpected behavior.
- Path traversal via image or asset references in templates.
- Unsafe deserialization of template data.
- Printer backend communication issues (network, serial, USB).

Issues in third-party dependencies should be reported to those projects directly,
but feel free to let us know so we can update our pinned versions.
