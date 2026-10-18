# Archived portal UIs (read-only fallback)

These trees are **not** the default site. The current portal is the React app at `/` (built from `portal-v2/`).

| Path | Was | Status |
|------|-----|--------|
| `/archive/v1/` | Legacy single-page portal (`/`) | Frozen; remove after a few release cycles |
| `/archive/v3/` | Previous React build (`/v2/`) | Frozen; `/v2/*` redirects to `/` |

Do not link these from the main nav. They exist so bookmarks and runbooks keep working briefly during the cutover.
