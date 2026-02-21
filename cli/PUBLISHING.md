# Publishing GenXBot CLI to npm

This guide explains how to publish the global GenXBot CLI package so users can install with:

```bash
npm install -g genxbot@latest
# or
pnpm add -g genxbot@latest
```

---

## 1) Prerequisites

- npm account with publish rights
- `npm` CLI installed
- package name available (or scoped name like `@your-org/genxbot`)

Check current package name:

```bash
cat /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/cli/package.json
```

---

## 2) Login to npm

```bash
npm login
```

Verify:

```bash
npm whoami
```

---

## 3) Choose package naming strategy

### Option A: Unscoped package (current)

Keep:

```json
"name": "genxbot"
```

Users install:

```bash
npm install -g genxbot@latest
```

### Option B: Scoped package (recommended for org ownership)

Set in `package.json`:

```json
"name": "@genexsus-ai/genxbot"
```

and add:

```json
"publishConfig": { "access": "public" }
```

Users install:

```bash
npm install -g @genexsus-ai/genxbot@latest
```

---

## 4) Versioning and changelog policy (CI-driven)

Versioning and changelog generation are now automated with **Release Please**:

- Workflow: `.github/workflows/release-please.yml`
- Config: `.release-please-config.json`
- Manifest: `.release-please-manifest.json`
- Changelog output: `cli/CHANGELOG.md`

How it works:

1. Merge release-worthy commits into `main`.
2. Release Please opens/updates a release PR with:
   - bumped `cli/package.json` version
   - updated `cli/CHANGELOG.md`
   - release title/version metadata
3. Merging that release PR creates a `cli-v*` tag and GitHub release.

If you need to force-run manually, use **workflow_dispatch** for `release-please`.

---

## 5) Local sanity checks before pushing release changes

```bash
cd /Users/iimran/Desktop/GenXBot/cli
npm run release:validate
```

This runs:

- `npm run release:check` (version/changelog/tag consistency gates)
- `npm pack --dry-run`
- `npm publish --dry-run --access public`

Confirm the tarball includes at least:

- `bin/genxbot.js`
- `scripts/release-check.cjs`
- `CHANGELOG.md`
- `package.json`

---

## 6) Publish (automated in CI)

Publishing is now handled by GitHub Actions workflow:

- Workflow: `.github/workflows/cli-release.yml`
- Validation job runs on PRs touching CLI/release files.
- Publish job only runs on tags matching `cli-v*` and only after validation passes.
- Publish job requires `NPM_TOKEN` secret (recommended via protected `npm-release` environment).

CI publish command:

```bash
npm publish --access public --provenance
```

Manual `npm publish` should only be used for emergencies.

---

## 7) Verify install flow

After publish:

```bash
npm install -g genxbot@latest
genxbot help
genxbot onboard
```

Daemon install (macOS/Linux):

```bash
genxbot onboard --install-daemon
```

---

## 8) Troubleshooting

### `403 Forbidden` on publish

- You are not owner/maintainer of package name.
- Use scoped package name or request ownership transfer.

### `You cannot publish over the previously published versions`

- Bump version first:

```bash
npm version patch
```

### Binary not found after global install

- Ensure `bin` field exists in `package.json`:

```json
"bin": { "genxbot": "bin/genxbot.js" }
```

- Ensure shebang exists in `bin/genxbot.js`:

```js
#!/usr/bin/env node
```

---

## 9) Recommended release workflow (automated)

```bash
cd /Users/iimran/Desktop/GenXBot
git checkout main
git pull

# Implement CLI changes and merge to main
# Wait for/merge Release Please PR
# Ensure tag cli-vX.Y.Z is created by release flow

# CI then validates and publishes package from tag
```

---

## 10) Release validation gates summary

CI blocks publish unless all checks pass:

1. `cli/scripts/release-check.cjs`
   - `cli/package.json` has valid semver
   - `cli/CHANGELOG.md` contains matching version heading
   - for tag builds, `cli-vX.Y.Z` must match package version
2. `npm pack --dry-run`
3. `npm publish --dry-run --access public`
4. On tag builds only: real publish with `NPM_TOKEN`
