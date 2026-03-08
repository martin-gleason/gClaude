# Environments

Two Cloud Run services in the same GCP project, deployed from separate branches.

## Branching Strategy

| Branch | Deploys to | Trigger |
|--------|-----------|---------|
| `main` | `gclaude` (production) | Push to `main` |
| `develop` | `gclaude-dev` (development) | Push to `develop` |
| PR to either | No deploy — tests only | Pull request |

## Environment Differences

| Setting | Production (`main`) | Development (`develop`) |
|---------|-------------------|----------------------|
| Cloud Run service | `gclaude` | `gclaude-dev` |
| Max instances | 3 | 1 |
| `DAILY_BUDGET_USD` | 5.00 | 1.00 |
| `LOG_LEVEL` | INFO | DEBUG |
| `GCS_BUCKET_NAME` | gclaude-prod-files | gclaude-dev-files |
| `GOOGLE_CHAT_PROJECT_NUMBER` | prod bot | dev bot |
| `AUTHORIZED_USERS` | prod allowlist | dev allowlist |

**Shared across both:** `ANTHROPIC_API_KEY` (same Secret Manager secret), Artifact Registry, Workload Identity Federation.

## GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `GCP_PROJECT_ID` | GCP project ID (shared) |
| `WIF_PROVIDER` | Workload Identity Federation provider (shared) |
| `WIF_SERVICE_ACCOUNT` | WIF service account (shared) |
| `AUTHORIZED_USERS_PROD` | Comma-separated prod user allowlist |
| `AUTHORIZED_USERS_DEV` | Comma-separated dev tester allowlist |

## GitHub Repository Variables

| Variable | Purpose |
|----------|---------|
| `GOOGLE_CHAT_PROJECT_NUMBER_PROD` | Project number from prod Chat bot registration |
| `GOOGLE_CHAT_PROJECT_NUMBER_DEV` | Project number from dev Chat bot registration |

## GCP Resources Required

### Shared (already exist)
- Artifact Registry repository `gclaude`
- Secret Manager secret `ANTHROPIC_API_KEY`
- Workload Identity Federation pool & provider

### Production (already exist)
- Cloud Run service `gclaude`
- GCS bucket `gclaude-prod-files`
- Google Chat bot registration (prod)

### Development (to create)
- Cloud Run service `gclaude-dev` — auto-created on first deploy
- GCS bucket `gclaude-dev-files` — create manually before first deploy
- Google Chat bot registration (dev) — register a separate bot pointing to the `gclaude-dev` Cloud Run URL

## Setup Checklist

1. Create GCS bucket `gclaude-dev-files`
2. Register a dev Google Chat bot pointing to the `gclaude-dev` service URL
3. Add GitHub secret `AUTHORIZED_USERS_PROD` (copy from current `AUTHORIZED_USERS`)
4. Add GitHub secret `AUTHORIZED_USERS_DEV` (dev tester emails)
5. Add GitHub variable `GOOGLE_CHAT_PROJECT_NUMBER_PROD` (from prod bot)
6. Add GitHub variable `GOOGLE_CHAT_PROJECT_NUMBER_DEV` (from dev bot)
7. Create and push the `develop` branch
8. Remove the old `AUTHORIZED_USERS` secret after migration
