# Contributing to Teamarr

Thanks for your interest in contributing. Bug reports, league requests, matching corrections, docs fixes, and code are all welcome.

## Reporting Issues

Open an issue before writing code, so the change can be discussed first:

- **[Bug Report](https://github.com/Pharaoh-Labs/teamarr/issues/new?template=bug_report.yml)** — wrong channels, missed matches, generation errors
- **[League / Sport Request](https://github.com/Pharaoh-Labs/teamarr/issues/new?template=league_request.yml)** — a league we don't cover yet
- **[Enhancement](https://github.com/Pharaoh-Labs/teamarr/issues/new?template=enhancement.yml)** — improve something that already exists
- **[Feature Request](https://github.com/Pharaoh-Labs/teamarr/issues/new?template=feature_request.yml)** — something new

For matching bugs, attach a **support bundle** (footer of the app, "Support bundle"). It is redacted and carries the stream names and failure reasons we need.

## Quick Contributions

### Team aliases and city translations

If a stream names a team in a way Teamarr does not recognize, the fix is usually data, not code. Aliases live in the app under **Matching**; if the alias would help everyone, open a Bug Report with the stream name and the team it should match, and we will add it to the built-in alias table.

### Adding a league

Leagues are rows in `teamarr/database/schema.sql` (`INSERT OR REPLACE INTO leagues`). Adding one also updates the sport section of `docs/reference/supported-leagues.md` and the league-count claims listed in the "Documentation Updates" table of `CLAUDE.md`. Open a League Request first: many leagues need a data source we don't have yet.

## Development Setup

```bash
# Fork and clone
git clone https://github.com/YOUR-USERNAME/teamarr.git
cd teamarr

# Backend (Python 3.11+)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Frontend
cd frontend && npm install && cd ..

# Run
python3 app.py                 # API on :9195
cd frontend && npm run dev     # Vite on :5173, proxies /api to :9195
```

Point the running app at a **throwaway Dispatcharr** while developing. Teamarr's scheduler writes channels into Dispatcharr and triggers media-server refreshes; never develop against an instance you care about.

## Pull Request Process

1. Branch from `dev`: `git checkout dev && git pull && git checkout -b <type>/<issue#>-<slug>` (type is `feat`, `fix`, `refactor`, `chore`, or `docs`)
2. Make the change, and update the docs it touches (`docs/`, `README.md`) in the same branch
3. Run the quality gates:
   ```bash
   ruff check teamarr/ tests/
   pytest tests/ -v
   cd frontend && npm run build
   ```
4. Open the PR **against `dev`, not `main`**, referencing the issue. CI runs on pull requests only.

### PR Guidelines

- Keep changes focused; one issue per PR
- Add or update tests for matching and parsing changes; the matcher is regression-tested against real stream names
- Run tests against an empty database (`DATABASE_PATH=/nonexistent/teamarr.db pytest tests/`) — a populated local DB hides failures that CI will catch
- No commit watermarks or generated-with trailers
- Do not commit `.beads/` changes; the maintainers sync issue tracking separately

## Code Style

- Python is formatted and linted with `ruff`; TypeScript follows the existing patterns
- Comments explain *why*, not *what*
- Match the surrounding code; avoid drive-by refactors in a fix PR

## Questions?

- [Documentation](https://pharaoh-labs.github.io/teamarr/)
- [Search Issues](https://github.com/Pharaoh-Labs/teamarr/issues)

## License

By submitting a pull request, you confirm that you have the right to submit the contribution and license it under the GNU Affero General Public License v3.0 only.

If your employer or another party owns the contribution, obtain its authorization before submitting it.

Contributions must not include code, assets, or data whose license is incompatible with AGPL-3.0-only. Preserve all required third-party notices and identify their source and license in the pull request.

Submitting a pull request grants Teamarr and its maintainers a perpetual, worldwide, non-exclusive, royalty-free, irrevocable license to use, modify, distribute, sublicense, and relicense the contribution as part of Teamarr under any [OSI-approved open-source license](https://opensource.org/licenses). This permission does not transfer copyright ownership.

## Attribution

Teamarr reads publicly available sports data and artwork from ESPN and other providers. All team names, logos, and trademarks are property of their respective owners.
