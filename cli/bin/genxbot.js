#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const APP_NAME = "genxbot";
const HOME_DIR = os.homedir();
const APP_HOME = path.join(HOME_DIR, ".genxbot");
const LOG_DIR = path.join(APP_HOME, "logs");
const ENV_PATH = path.join(APP_HOME, ".env");

const repoRoot = path.resolve(__dirname, "../../../..");
const backendDir = path.join(repoRoot, "applications", "genxbot", "backend");

function printHelp() {
  console.log(`
GenXBot CLI

Usage:
  genxbot onboard [--install-daemon]
  genxbot help

Options:
  --install-daemon     Install background daemon (macOS LaunchAgent / Linux systemd --user)
`);
}

function checkCommand(name) {
  const probe = process.platform === "win32" ? "where" : "which";
  const res = spawnSync(probe, [name], { stdio: "ignore" });
  return res.status === 0;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function writeEnvTemplate() {
  if (fs.existsSync(ENV_PATH)) return;

  const template = `# GenXBot global environment\nOPENAI_API_KEY=\nADMIN_API_TOKEN=\nCHANNEL_WEBHOOK_SECURITY_ENABLED=false\n`;
  fs.writeFileSync(ENV_PATH, template, "utf8");
}

function runBackendProbe() {
  const py = checkCommand("python3") ? "python3" : checkCommand("python") ? "python" : null;
  if (!py) {
    console.warn("[warn] Python not found. Install Python 3.9+ to run backend.");
    return;
  }

  const res = spawnSync(py, ["-c", "import sys; print(sys.version.split()[0])"], {
    encoding: "utf8",
  });
  if (res.status === 0) {
    console.log(`[ok] Python detected: ${res.stdout.trim()}`);
  }
}

function daemonCommand() {
  return `cd ${backendDir} && python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000`;
}

function installMacDaemon() {
  const launchAgents = path.join(HOME_DIR, "Library", "LaunchAgents");
  ensureDir(launchAgents);

  const plistPath = path.join(launchAgents, "com.genxai.genxbot.plist");
  const stdoutLog = path.join(LOG_DIR, "daemon.out.log");
  const stderrLog = path.join(LOG_DIR, "daemon.err.log");

  const plist = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.genxai.genxbot</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>${daemonCommand()}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${backendDir}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${stdoutLog}</string>
  <key>StandardErrorPath</key>
  <string>${stderrLog}</string>
</dict>
</plist>
`;

  fs.writeFileSync(plistPath, plist, "utf8");
  spawnSync("launchctl", ["unload", plistPath], { stdio: "ignore" });
  const load = spawnSync("launchctl", ["load", plistPath], { stdio: "inherit" });
  if (load.status === 0) {
    console.log(`[ok] Installed LaunchAgent: ${plistPath}`);
  } else {
    console.warn("[warn] launchctl load failed; you may need to run manually.");
  }
}

function installLinuxDaemon() {
  const userSystemd = path.join(HOME_DIR, ".config", "systemd", "user");
  ensureDir(userSystemd);

  const svcPath = path.join(userSystemd, "genxbot.service");
  const stdoutLog = path.join(LOG_DIR, "daemon.out.log");
  const stderrLog = path.join(LOG_DIR, "daemon.err.log");

  const svc = `[Unit]
Description=GenXBot daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=${backendDir}
ExecStart=/bin/bash -lc '${daemonCommand()}'
Restart=always
RestartSec=3
StandardOutput=append:${stdoutLog}
StandardError=append:${stderrLog}

[Install]
WantedBy=default.target
`;

  fs.writeFileSync(svcPath, svc, "utf8");
  spawnSync("systemctl", ["--user", "daemon-reload"], { stdio: "inherit" });
  spawnSync("systemctl", ["--user", "enable", "--now", "genxbot.service"], {
    stdio: "inherit",
  });
  console.log(`[ok] Installed systemd user service: ${svcPath}`);
}

function installDaemon() {
  if (process.platform === "darwin") {
    installMacDaemon();
    return;
  }
  if (process.platform === "linux") {
    installLinuxDaemon();
    return;
  }
  console.warn("[warn] --install-daemon currently supports macOS and Linux.");
}

function onboard({ installDaemonFlag }) {
  console.log("[info] Starting GenXBot onboarding...");
  ensureDir(APP_HOME);
  ensureDir(LOG_DIR);
  writeEnvTemplate();

  console.log(`[ok] App home: ${APP_HOME}`);
  console.log(`[ok] Env file: ${ENV_PATH}`);

  const hasNode = checkCommand("node");
  const hasNpm = checkCommand("npm");
  const hasPy3 = checkCommand("python3") || checkCommand("python");

  console.log(`[check] node: ${hasNode ? "ok" : "missing"}`);
  console.log(`[check] npm: ${hasNpm ? "ok" : "missing"}`);
  console.log(`[check] python: ${hasPy3 ? "ok" : "missing"}`);

  runBackendProbe();

  if (installDaemonFlag) {
    installDaemon();
  }

  console.log("[done] Onboarding complete.");
  console.log("Next:");
  console.log(`  1) Edit ${ENV_PATH}`);
  console.log(`  2) Start backend manually: cd ${backendDir} && uvicorn app.main:app --reload --port 8000`);
}

function main() {
  const args = process.argv.slice(2);
  const command = args[0];

  if (!command || command === "help" || command === "--help" || command === "-h") {
    printHelp();
    process.exit(0);
  }

  if (command === "onboard") {
    const installDaemonFlag = args.includes("--install-daemon");
    onboard({ installDaemonFlag });
    process.exit(0);
  }

  console.error(`[error] Unknown command: ${command}`);
  printHelp();
  process.exit(1);
}

main();
