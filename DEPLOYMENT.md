# Deployment Standard

Shared deployment governance for the Launchpad + StarGate + DeepField platform. All three products follow these rules.

## Branch Protection

- PRs required to merge to `main` — no direct pushes
- CI status checks must pass before merging
- No force pushes to `main`

## CI Pipeline

Every push to `main` and every PR triggers CI. No exceptions.

| Step | What | Blocks merge? |
|------|------|---------------|
| Lint | `ruff check` on all Python source | Yes |
| Tests | `pytest` full suite (skip integration-tagged tests) | Yes |
| Frontend | `tsc --noEmit` on all TypeScript apps | Yes (if applicable) |
| Image build | `docker build` all Containerfiles (no push) | Yes |
| Test receipt | JSON artifact with commit, test count, timestamp | No (always runs) |

## Deploy Workflow

Deployments are manual, gated, and audited.

1. Developer triggers `Deploy to Cluster` workflow via GitHub Actions
2. Must type `deploy` to confirm (prevents accidental triggers)
3. **Gate check** runs full test suite again (not cached from CI)
4. **Environment approval** — GitHub environment requires reviewer approval
5. Build + push images (tagged with version and git SHA)
6. Apply Kustomize manifests to target cluster
7. Deployment receipt generated with commit, actor, timestamp

## Versioning

**CalVer: `YYYY.MM.patch`** (e.g., `2026.05.1`)

- Bump version on each deploy
- Tag the commit: `git tag v2026.05.1`
- Images tagged with both version and git SHA: `:2026.05.1` and `:a4ff4da`
- Never deploy `:latest` to production

## Image Tagging

| Tag | When | Example |
|-----|------|---------|
| `:ci` | CI build verification (not pushed) | `stargate:ci` |
| `:<git-sha>` | Every pushed image | `stargate:a4ff4da` |
| `:<calver>` | Release deploys | `stargate:2026.05.1` |
| `:latest` | Local dev only — never in production manifests | `stargate:latest` |

## Environments

| Environment | Purpose | Approval Required |
|-------------|---------|-------------------|
| `infra01` | Development/staging cluster | Yes (GitHub environment) |
| `prod` | Production (future) | Yes + additional reviewer |

## Secrets Management

- All secrets via Kubernetes Secrets — never `.env` files in deployment
- Database passwords generated at deploy time (random 24-char)
- Integration API keys stored in dedicated secrets (optional, marked as such)
- No secrets in container images, environment variables, or git history

## Rollback

If a deployment causes issues:

```bash
# Immediate rollback to previous revision
oc rollout undo deployment/<name> -n <namespace>

# Verify rollback
oc rollout status deployment/<name> -n <namespace>
```

For database schema rollbacks, create a reverse migration SQL file and apply manually.

## Test Receipts

Every CI run produces a JSON receipt:

```json
{
  "test_run_id": "uuid",
  "timestamp": "ISO 8601",
  "environment": "ci",
  "commit": "short-sha",
  "summary": {"total": 45, "passed": 45, "failed": 0},
  "trigger": "push|pull_request",
  "branch": "main",
  "product": "stargate|launchpad|deepfield"
}
```

Receipts are uploaded as GitHub Actions artifacts and stored in `test-receipts/`.

## Shared Tech Stack

All three products use the same versions to avoid drift:

| Component | Version |
|-----------|---------|
| Python | >=3.11 |
| FastAPI | >=0.115 |
| Pydantic | >=2.10 |
| asyncpg | >=0.30 |
| httpx | >=0.28 |
| Base image | UBI9/python-311 |
| Container tool | Podman |
| Deployment | Kustomize + AgnosticV/AgnosticD |
