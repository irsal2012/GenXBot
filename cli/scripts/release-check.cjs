#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const packageJsonPath = path.join(__dirname, "..", "package.json");
const changelogPath = path.join(__dirname, "..", "CHANGELOG.md");
const refName = process.argv[2] || "";

function fail(message) {
  console.error(`❌ ${message}`);
  process.exit(1);
}

if (!fs.existsSync(packageJsonPath)) {
  fail("cli/package.json was not found.");
}

if (!fs.existsSync(changelogPath)) {
  fail("cli/CHANGELOG.md was not found.");
}

const pkg = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
const changelog = fs.readFileSync(changelogPath, "utf8");
const expectedVersionHeader = new RegExp(`##\\s+\\[?${pkg.version.replace(/\\./g, "\\.")}\\]?\\b`);

if (!pkg.name || !pkg.version) {
  fail("package.json must include both name and version fields.");
}

if (!/^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/.test(pkg.version)) {
  fail(`package.json version '${pkg.version}' is not valid semver.`);
}

if (!expectedVersionHeader.test(changelog)) {
  fail(
    `CHANGELOG.md must include a release section for ${pkg.version} (expected heading like '## [${pkg.version}]').`
  );
}

if (refName && refName.startsWith("cli-v")) {
  const tagVersion = refName.replace(/^cli-v/, "");
  if (tagVersion !== pkg.version) {
    fail(`Tag '${refName}' does not match cli/package.json version '${pkg.version}'.`);
  }
}

console.log(`✅ Release checks passed for ${pkg.name}@${pkg.version}${refName ? ` (ref: ${refName})` : ""}.`);
