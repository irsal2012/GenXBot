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

## 4) Version bump before each publish

From CLI package directory:

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/cli
npm version patch
```

Use `minor` or `major` when needed:

```bash
npm version minor
npm version major
```

---

## 5) Sanity-check package contents

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/cli
npm pack --dry-run
```

Confirm the tarball includes at least:

- `bin/genxbot.js`
- `package.json`

---

## 6) Publish

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/cli
npm publish
```

For scoped public packages:

```bash
npm publish --access public
```

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

## 9) Recommended release workflow (manual)

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS
git checkout main
git pull

cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/cli
npm version patch
npm publish

cd /Users/irsalimran/Desktop/GenXAI-OSS
git push && git push --tags
```
