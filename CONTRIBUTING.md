# Contributing

This is an internal tool maintained by the ATS Inc. team. Contributions are limited to authorized team members.

## Getting Started

1. Clone the repo and create a virtual environment:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Run the app directly for development:
   ```
   python app.py
   ```
3. For drawing-generation changes, you'll need BricsCAD installed locally
   (the app drives it via COM). UI-only changes can be tested without it —
   the form opens fine, only the **Generate Drawing** action requires CAD.

## Making Changes

- Create a branch for your work: `git checkout -b your-feature-name`
- Keep changes focused — one feature or fix per PR
- Test your changes manually before submitting, including edge cases
- For UI changes, verify at both normal and reduced window sizes
- Do not commit test data, credentials, or personal data files
- Generated artifacts (`jobs/drawings/`, `jobs/last_generation.log`,
  block thumbnails under `blocks/**/*.png`, `.dwg.bak` backups) are
  gitignored — leave them out of commits

## Submitting a Pull Request

1. Push your branch and open a PR against `main`
2. Describe what changed and why
3. Tag the repo owner for review

## Releases

Only the repo owner runs builds and publishes releases. See the **Build a release** section in the README for the release process.

## Questions

Reach out to Justin Glave directly for anything not covered here.
