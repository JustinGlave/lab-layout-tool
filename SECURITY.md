# Security Policy

## Supported Versions

Only the latest release is actively supported with security fixes.

| Version | Supported |
|---------|-----------|
| Latest  | Yes       |
| Older   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, **do not open a public issue**.

Report it privately to the repository owner:

- **Email:** justinglave@gmail.com
- **Subject:** `[LLT Security] Brief description`

Please include:
- A description of the vulnerability
- Steps to reproduce it
- Potential impact

You can expect a response within 3 business days. If the issue is confirmed, a fix will be prioritized for the next release.

## Scope

Key security considerations for this application:

- **BricsCAD COM driver** runs at the user's privilege level — generated DWGs
  inherit the same permissions as the running user. The app does not elevate.
- **Project data** is saved as JSON under `%APPDATA%\ATS Inc\Lab Layout Tool`
  by default and as freely-named `.json` files anywhere the user picks via
  File → Save Project. Ensure data folders have appropriate OS-level access
  controls in shared environments.
- **Generated drawings** land in `jobs/drawings/` (local install dir) by
  default — these are output files containing as-built valve information for
  the active project; treat per company data-handling policy.
- **Bundled template** (`templates/Background.dwg`) ships with the install
  and is overwritten on auto-update. User-modified templates should be kept
  outside the install dir to avoid being replaced.
- **Auto-updater** downloads only from the official GitHub releases page of
  this repository, validates the zip contains the expected exe + `_internal/`
  layout before applying, and refuses to run from source builds.
