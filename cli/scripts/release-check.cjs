#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const packageJsonPath = path.join(__dirname, "..", "package.json");
const changelogPath = path.join(__dirname, "..", "CHANGELOG.md");
const repoRoot = path.join(__dirname, "..", "..");
const releaseManifestPath = path.join(repoRoot, ".release-please-manifest.json");
const releaseConfigPath = path.join(repoRoot, ".release-please-config.json");
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

if (!fs.existsSync(releaseManifestPath)) {
  fail(".release-please-manifest.json was not found.");
}

if (!fs.existsSync(releaseConfigPath)) {
  fail(".release-please-config.json was not found.");
}

const pkg = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
const changelog = fs.readFileSync(changelogPath, "utf8");
const releaseManifest = JSON.parse(fs.readFileSync(releaseManifestPath, "utf8"));
const releaseConfig = JSON.parse(fs.readFileSync(releaseConfigPath, "utf8"));
const expectedVersionHeader = new RegExp(`##\\s+\\[?${pkg.version.replace(/\\./g, "\\.")}\\]?\\b`);

if (!pkg.name || !pkg.version) {
  fail("package.json must include both name and version fields.");
}

if (!/^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/.test(pkg.version)) {
  fail(`package.json version '${pkg.version}' is not valid semver.`);
}

if (!releaseManifest.cli) {
  fail(".release-please-manifest.json must include a 'cli' version entry.");
}

if (releaseManifest.cli !== pkg.version) {
  fail(
    `Manifest version mismatch: .release-please-manifest.json has cli=${releaseManifest.cli} but cli/package.json has ${pkg.version}.`
  );
}

const cliConfig = releaseConfig?.packages?.cli;
if (!cliConfig) {
  fail(".release-please-config.json must include packages.cli config.");
}

if (cliConfig["package-name"] !== pkg.name) {
  fail(
    `Release-please package-name mismatch: expected '${pkg.name}', found '${cliConfig["package-name"]}'.`
  );
}

if (cliConfig["release-type"] !== "node") {
  fail(`Release-please packages.cli.release-type must be 'node'.`);
}

if (cliConfig["changelog-path"] !== "cli/CHANGELOG.md") {
  fail(`Release-please packages.cli.changelog-path must be 'cli/CHANGELOG.md'.`);
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

const expectedBinPath = path.join(__dirname, "..", "bin", "genxbot.js");
if (!fs.existsSync(expectedBinPath)) {
  fail("CLI binary was not found at cli/bin/genxbot.js.");
}

console.log(`✅ Release checks passed for ${pkg.name}@${pkg.version}${refName ? ` (ref: ${refName})` : ""}.`);
