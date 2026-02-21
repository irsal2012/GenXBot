#!/usr/bin/env node
/* eslint-disable no-console */

const fs = require("fs");
const http = require("http");
const net = require("net");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const readline = require("readline/promises");
const { spawn, spawnSync } = require("child_process");

const APP_NAME = "genxbot";
const HOME_DIR = os.homedir();
const APP_HOME = path.join(HOME_DIR, ".genxbot");
const LOG_DIR = path.join(APP_HOME, "logs");
const ENV_PATH = path.join(APP_HOME, ".env");
const DAEMON_META_PATH = path.join(APP_HOME, "daemon.meta.json");
const HEALTH_SNAPSHOT_PATH = path.join(APP_HOME, "health.snapshot.json");
const DAEMON_LABEL = "com.genxai.genxbot";
const DEFAULT_BACKEND_PORT = 8000;
const DEFAULT_FRONTEND_PORT = 5173;

const repoRoot = path.resolve(__dirname, "../..");

function printHelp() {
  console.log(`
GenXBot CLI

Usage:
  genxbot onboard [--interactive] [--install-daemon] [--yes]
  genxbot start
  genxbot stop
  genxbot status [--json]
  genxbot logs [--out|--err] [--lines N] [--follow]
  genxbot uninstall [--yes]
  genxbot doctor [--json]
  genxbot help

Options:
  --interactive        Guided onboarding prompts + validation checks
  --install-daemon     Install background daemon (macOS LaunchAgent / Linux systemd --user)
  --follow, -f         Stream logs continuously (for logs command)
  --lines, -n N        Number of log lines to show (default: 100)
  --yes                Accept defaults in interactive onboarding (where applicable)
  --json               Machine-readable output for doctor command

Tips:
  - For first-time setup, run: genxbot onboard --interactive
  - Manage backend daemon with: genxbot start|stop|status|logs|uninstall
  - If OPENAI_API_KEY is not set, GenXBot runs in deterministic fallback mode
`);
}

function readJsonFile(filePath, fallback = null) {
  try {
    if (!pathExists(filePath)) return fallback;
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJsonFile(filePath, value) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function daemonPlistPath() {
  return path.join(HOME_DIR, "Library", "LaunchAgents", `${DAEMON_LABEL}.plist`);
}

function daemonSystemdPath() {
  return path.join(HOME_DIR, ".config", "systemd", "user", "genxbot.service");
}

function isProcessAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function resolveDaemonPythonCommand() {
  if (checkCommand("python3")) return "python3";
  if (checkCommand("python")) return "python";
  return null;
}

function daemonArgs() {
  return [
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    `${DEFAULT_BACKEND_PORT}`,
  ];
}

function daemonEnv() {
  const envFromFile = loadEnvValues();
  return {
    ...process.env,
    ...envFromFile,
  };
}

function readDaemonMeta() {
  return (
    readJsonFile(DAEMON_META_PATH, {
      manager: "cli",
      pid: null,
      startedAt: null,
      stoppedAt: null,
      backendDir: null,
      pythonCommand: null,
      args: [],
      outLog: path.join(LOG_DIR, "daemon.out.log"),
      errLog: path.join(LOG_DIR, "daemon.err.log"),
      uninstallAt: null,
    }) || {}
  );
}

function writeDaemonMeta(meta) {
  writeJsonFile(DAEMON_META_PATH, {
    manager: meta.manager || "cli",
    pid: meta.pid ?? null,
    startedAt: meta.startedAt ?? null,
    stoppedAt: meta.stoppedAt ?? null,
    backendDir: meta.backendDir || detectBackendDir(),
    pythonCommand: meta.pythonCommand || null,
    args: meta.args || daemonArgs(),
    outLog: meta.outLog || path.join(LOG_DIR, "daemon.out.log"),
    errLog: meta.errLog || path.join(LOG_DIR, "daemon.err.log"),
    uninstallAt: meta.uninstallAt ?? null,
    updatedAt: new Date().toISOString(),
  });
}

async function writeHealthSnapshot(extra = {}) {
  const meta = readDaemonMeta();
  const pidAlive = isProcessAlive(meta.pid);
  const probe = await probeHttp(`http://127.0.0.1:${DEFAULT_BACKEND_PORT}/api/v1/runs`);
  const snapshot = {
    timestamp: new Date().toISOString(),
    daemon: {
      manager: meta.manager || "cli",
      pid: meta.pid ?? null,
      pidAlive,
      startedAt: meta.startedAt ?? null,
      stoppedAt: meta.stoppedAt ?? null,
      backendDir: meta.backendDir || detectBackendDir(),
    },
    backendApi: {
      reachable: Boolean(probe.ok),
      statusCode: probe.statusCode ?? null,
      error: probe.error ?? null,
    },
    ...extra,
  };

  writeJsonFile(HEALTH_SNAPSHOT_PATH, snapshot);
  return snapshot;
}

function checkCommand(name) {
  const probe = process.platform === "win32" ? "where" : "which";
  const res = spawnSync(probe, [name], { stdio: "ignore" });
  return res.status === 0;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function pathExists(targetPath) {
  try {
    fs.accessSync(targetPath, fs.constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

function detectBackendDir() {
  const candidates = [
    path.join(repoRoot, "backend"),
    path.join(repoRoot, "applications", "genxbot", "backend"),
    path.join(process.cwd(), "backend"),
    process.cwd(),
  ];

  for (const candidate of candidates) {
    if (pathExists(path.join(candidate, "requirements.txt")) && pathExists(path.join(candidate, "app"))) {
      return candidate;
    }
  }

  return candidates[0];
}

function detectFrontendDir() {
  const candidates = [
    path.join(repoRoot, "frontend"),
    path.join(repoRoot, "applications", "genxbot", "frontend"),
    path.join(process.cwd(), "frontend"),
  ];

  for (const candidate of candidates) {
    if (pathExists(path.join(candidate, "package.json"))) {
      return candidate;
    }
  }
  return candidates[0];
}

function parseEnv(content) {
  const values = {};
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const idx = line.indexOf("=");
    if (idx <= 0) continue;
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    values[key] = value;
  }
  return values;
}

function renderEnv(values) {
  return [
    "# GenXBot global environment",
    `OPENAI_API_KEY=${values.OPENAI_API_KEY ?? ""}`,
    `ADMIN_API_TOKEN=${values.ADMIN_API_TOKEN ?? ""}`,
    `AGENT_RUNTIME_MODE=${values.AGENT_RUNTIME_MODE ?? "single"}`,
    `CHANNEL_WEBHOOK_SECURITY_ENABLED=${values.CHANNEL_WEBHOOK_SECURITY_ENABLED ?? "false"}`,
    "",
  ].join("\n");
}

function writeEnvTemplate() {
  if (fs.existsSync(ENV_PATH)) return;

  const template = renderEnv({});
  fs.writeFileSync(ENV_PATH, template, "utf8");
}

function loadEnvValues() {
  if (!pathExists(ENV_PATH)) return {};
  return parseEnv(fs.readFileSync(ENV_PATH, "utf8"));
}

function validateEnv(values) {
  const warnings = [];
  const errors = [];

  const mode = (values.AGENT_RUNTIME_MODE || "single").trim().toLowerCase();
  if (mode && !["single", "multi", "hybrid"].includes(mode)) {
    errors.push("AGENT_RUNTIME_MODE must be one of: single, multi, hybrid");
  }

  const apiKey = (values.OPENAI_API_KEY || "").trim();
  if (!apiKey) {
    warnings.push("OPENAI_API_KEY is missing. GenXBot will run deterministic fallback mode.");
  }

  const adminToken = (values.ADMIN_API_TOKEN || "").trim();
  if (!adminToken) {
    warnings.push("ADMIN_API_TOKEN is empty. Admin endpoint protection may be limited.");
  }

  return { warnings, errors };
}

function maskToken(value) {
  const trimmed = (value || "").trim();
  if (!trimmed) return "(empty)";
  if (trimmed.length <= 8) return "****";
  return `${trimmed.slice(0, 4)}...${trimmed.slice(-4)}`;
}

function generateAdminToken() {
  return `genxbot_${crypto.randomBytes(16).toString("hex")}`;
}

function detectPythonCommand() {
  if (checkCommand("python3")) return "python3";
  if (checkCommand("python")) return "python";
  return null;
}

function checkPythonImport(pyCommand, moduleName) {
  if (!pyCommand) return false;
  const res = spawnSync(pyCommand, ["-c", `import ${moduleName}`], { stdio: "ignore" });
  return res.status === 0;
}

function printCheck(level, message) {
  const icon = level === "PASS" ? "[ok]" : level === "WARN" ? "[warn]" : "[fail]";
  console.log(`${icon} ${message}`);
}

function versionFor(command, args = ["--version"]) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.status !== 0) return null;
  return (result.stdout || result.stderr || "").trim().split("\n")[0];
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
  const backendDir = detectBackendDir();
  const py = resolveDaemonPythonCommand() || "python3";
  return `cd ${backendDir} && ${py} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`;
}

function installMacDaemon() {
  const backendDir = detectBackendDir();
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
    writeDaemonMeta({
      ...readDaemonMeta(),
      manager: "launchd",
      backendDir,
      outLog: stdoutLog,
      errLog: stderrLog,
    });
  } else {
    console.warn("[warn] launchctl load failed; you may need to run manually.");
  }
}

function installLinuxDaemon() {
  const backendDir = detectBackendDir();
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
  writeDaemonMeta({
    ...readDaemonMeta(),
    manager: "systemd",
    backendDir,
    outLog: stdoutLog,
    errLog: stderrLog,
  });
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

async function promptInput(rl, prompt, defaultValue = "") {
  const suffix = defaultValue ? ` (${defaultValue})` : "";
  const input = await rl.question(`${prompt}${suffix}: `);
  return input.trim() || defaultValue;
}

async function interactiveOnboard({ yes = false }) {
  const firstRun = !pathExists(ENV_PATH);
  ensureDir(APP_HOME);
  ensureDir(LOG_DIR);
  writeEnvTemplate();

  const backendDir = detectBackendDir();
  const values = loadEnvValues();
  let selectedMode = (values.AGENT_RUNTIME_MODE || "single").trim().toLowerCase();
  if (!["single", "multi", "hybrid"].includes(selectedMode)) {
    selectedMode = "single";
  }

  if (yes) {
    values.AGENT_RUNTIME_MODE = selectedMode;
    values.CHANNEL_WEBHOOK_SECURITY_ENABLED = values.CHANNEL_WEBHOOK_SECURITY_ENABLED || "false";
    if (!values.ADMIN_API_TOKEN) {
      values.ADMIN_API_TOKEN = generateAdminToken();
    }
  } else {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    try {
      console.log("\n[info] Interactive onboarding\n");
      if (firstRun) {
        console.log("[info] First run detected. We'll apply guided defaults and validate your environment.");
      }
      console.log(`[info] Detected backend path: ${backendDir}`);
      console.log("[info] Guided defaults: AGENT_RUNTIME_MODE=single, CHANNEL_WEBHOOK_SECURITY_ENABLED=false");

      values.OPENAI_API_KEY = await promptInput(
        rl,
        "OPENAI_API_KEY (recommended for live LLM planning/execution)",
        values.OPENAI_API_KEY || "",
      );
      values.ADMIN_API_TOKEN = await promptInput(
        rl,
        "ADMIN_API_TOKEN (recommended for protected admin endpoints)",
        values.ADMIN_API_TOKEN || "",
      );
      if (!values.ADMIN_API_TOKEN) {
        const createToken = await promptInput(rl, "Generate a secure ADMIN_API_TOKEN now? [Y/n]", "Y");
        if (!createToken || createToken.toLowerCase() === "y" || createToken.toLowerCase() === "yes") {
          values.ADMIN_API_TOKEN = generateAdminToken();
          console.log(`[ok] Generated ADMIN_API_TOKEN: ${maskToken(values.ADMIN_API_TOKEN)}`);
        }
      }

      selectedMode = await promptInput(
        rl,
        "AGENT_RUNTIME_MODE [single|multi|hybrid]",
        selectedMode,
      );
      while (!["single", "multi", "hybrid"].includes(selectedMode.toLowerCase())) {
        console.log("[warn] Invalid runtime mode. Choose single, multi, or hybrid.");
        selectedMode = await promptInput(rl, "AGENT_RUNTIME_MODE", "single");
      }
      values.AGENT_RUNTIME_MODE = selectedMode.toLowerCase();

      const webhookSecurity = await promptInput(
        rl,
        "CHANNEL_WEBHOOK_SECURITY_ENABLED [true|false]",
        values.CHANNEL_WEBHOOK_SECURITY_ENABLED || "false",
      );
      values.CHANNEL_WEBHOOK_SECURITY_ENABLED = webhookSecurity.toLowerCase() === "true" ? "true" : "false";
    } finally {
      rl.close();
    }
  }

  const validation = validateEnv(values);
  fs.writeFileSync(ENV_PATH, renderEnv(values), "utf8");

  for (const warning of validation.warnings) {
    printCheck("WARN", warning);
  }
  for (const error of validation.errors) {
    printCheck("FAIL", error);
  }

  console.log("\n[done] Interactive onboarding completed.");
  console.log(`- Env file: ${ENV_PATH}`);
  console.log(`- Backend path: ${backendDir}`);
  console.log(`- OPENAI_API_KEY: ${maskToken(values.OPENAI_API_KEY)}`);
  console.log(`- ADMIN_API_TOKEN: ${maskToken(values.ADMIN_API_TOKEN)}`);
  if (!values.OPENAI_API_KEY) {
    console.log("\n[info] Fallback behavior: planning/execution will use deterministic fallback until OPENAI_API_KEY is set.");
  }
  console.log("\nNext steps:");
  console.log("1) Run `genxbot doctor` to verify dependencies, ports, and config.");
  console.log(`2) Start backend: cd ${backendDir} && uvicorn app.main:app --reload --port 8000`);
}

async function startDaemon() {
  ensureDir(APP_HOME);
  ensureDir(LOG_DIR);
  writeEnvTemplate();

  const existing = readDaemonMeta();
  if (isProcessAlive(existing.pid)) {
    console.log(`[info] GenXBot daemon already running (pid ${existing.pid}).`);
    await writeHealthSnapshot({ event: "start_skipped_already_running" });
    return;
  }

  const py = resolveDaemonPythonCommand();
  if (!py) {
    console.error("[error] Python not found. Install python3/python before starting daemon.");
    process.exit(1);
  }

  const backendDir = detectBackendDir();
  const outLog = path.join(LOG_DIR, "daemon.out.log");
  const errLog = path.join(LOG_DIR, "daemon.err.log");
  const outFd = fs.openSync(outLog, "a");
  const errFd = fs.openSync(errLog, "a");
  const args = daemonArgs();

  const child = spawn(py, args, {
    cwd: backendDir,
    detached: true,
    stdio: ["ignore", outFd, errFd],
    env: daemonEnv(),
  });
  fs.closeSync(outFd);
  fs.closeSync(errFd);
  child.unref();

  const nextMeta = {
    ...existing,
    manager: "cli",
    pid: child.pid,
    startedAt: new Date().toISOString(),
    stoppedAt: null,
    backendDir,
    pythonCommand: py,
    args,
    outLog,
    errLog,
  };
  writeDaemonMeta(nextMeta);

  await sleep(1200);
  const snapshot = await writeHealthSnapshot({ event: "start" });
  const apiState = snapshot.backendApi.reachable
    ? `reachable (status ${snapshot.backendApi.statusCode})`
    : `not yet reachable (${snapshot.backendApi.error || "starting"})`;
  console.log(`[ok] Started GenXBot daemon (pid ${child.pid}).`);
  console.log(`[info] Backend API probe: ${apiState}`);
}

async function stopDaemon({ silent = false } = {}) {
  const meta = readDaemonMeta();
  if (!meta.pid) {
    if (!silent) console.log("[info] No daemon PID metadata found. Nothing to stop.");
    await writeHealthSnapshot({ event: "stop_no_metadata" });
    return true;
  }

  if (!isProcessAlive(meta.pid)) {
    const updatedMeta = {
      ...meta,
      pid: null,
      stoppedAt: new Date().toISOString(),
    };
    writeDaemonMeta(updatedMeta);
    if (!silent) console.log("[info] Daemon process not running; metadata cleaned.");
    await writeHealthSnapshot({ event: "stop_clean_stale_pid" });
    return true;
  }

  try {
    process.kill(meta.pid, "SIGTERM");
  } catch {
    if (!silent) console.warn("[warn] Failed to send SIGTERM to daemon process.");
  }

  let stopped = false;
  let usedSigkill = false;
  for (let i = 0; i < 15; i += 1) {
    if (!isProcessAlive(meta.pid)) {
      stopped = true;
      break;
    }
    await sleep(200);
  }

  if (!stopped && isProcessAlive(meta.pid)) {
    try {
      process.kill(meta.pid, "SIGKILL");
      stopped = true;
      usedSigkill = true;
    } catch {
      stopped = false;
    }
  }

  if (stopped) {
    writeDaemonMeta({
      ...meta,
      pid: null,
      stoppedAt: new Date().toISOString(),
    });
    await writeHealthSnapshot({ event: "stop", forced: usedSigkill });
    if (!silent) console.log("[ok] Stopped GenXBot daemon.");
    return true;
  }

  await writeHealthSnapshot({ event: "stop_failed" });
  if (!silent) console.error("[error] Failed to stop daemon process.");
  return false;
}

async function daemonStatus({ json = false } = {}) {
  const meta = readDaemonMeta();
  const running = isProcessAlive(meta.pid);
  const snapshot = await writeHealthSnapshot({ event: "status" });

  const status = {
    daemon: {
      manager: meta.manager || "cli",
      running,
      pid: running ? meta.pid : null,
      startedAt: meta.startedAt || null,
      stoppedAt: meta.stoppedAt || null,
      backendDir: meta.backendDir || detectBackendDir(),
    },
    logs: {
      out: meta.outLog || path.join(LOG_DIR, "daemon.out.log"),
      err: meta.errLog || path.join(LOG_DIR, "daemon.err.log"),
    },
    healthSnapshotPath: HEALTH_SNAPSHOT_PATH,
    backendApi: snapshot.backendApi,
  };

  if (json) {
    console.log(JSON.stringify(status, null, 2));
    return;
  }

  console.log(`[info] manager: ${status.daemon.manager}`);
  console.log(`[info] running: ${status.daemon.running ? "yes" : "no"}`);
  console.log(`[info] pid: ${status.daemon.pid ?? "(none)"}`);
  console.log(`[info] startedAt: ${status.daemon.startedAt ?? "(n/a)"}`);
  console.log(`[info] stoppedAt: ${status.daemon.stoppedAt ?? "(n/a)"}`);
  if (status.backendApi.reachable) {
    console.log(`[ok] backend API reachable (status ${status.backendApi.statusCode})`);
  } else {
    console.log(`[warn] backend API unreachable (${status.backendApi.error || "not running"})`);
  }
  console.log(`[info] out log: ${status.logs.out}`);
  console.log(`[info] err log: ${status.logs.err}`);
  console.log(`[info] health snapshot: ${status.healthSnapshotPath}`);
}

function readLastLines(filePath, lines = 100) {
  if (!pathExists(filePath)) return "";
  const content = fs.readFileSync(filePath, "utf8");
  const chunks = content.split(/\r?\n/);
  return chunks.slice(-lines).join("\n");
}

function parseLinesArg(args) {
  const nIdx = args.findIndex((arg) => arg === "--lines" || arg === "-n");
  if (nIdx === -1) return 100;
  const maybeValue = Number.parseInt(args[nIdx + 1], 10);
  return Number.isInteger(maybeValue) && maybeValue > 0 ? maybeValue : 100;
}

function streamLogs(files, lines) {
  const tailArgs = ["-n", `${lines}`, "-f", ...files];
  const tailProc = spawn("tail", tailArgs, { stdio: "inherit" });
  tailProc.on("exit", (code) => {
    process.exit(code || 0);
  });
}

function showLogs(args) {
  const meta = readDaemonMeta();
  const outLog = meta.outLog || path.join(LOG_DIR, "daemon.out.log");
  const errLog = meta.errLog || path.join(LOG_DIR, "daemon.err.log");
  const lines = parseLinesArg(args);
  const onlyOut = args.includes("--out");
  const onlyErr = args.includes("--err");
  const follow = args.includes("--follow") || args.includes("-f");

  const selected = [];
  if (onlyOut && !onlyErr) selected.push(outLog);
  else if (onlyErr && !onlyOut) selected.push(errLog);
  else selected.push(outLog, errLog);

  const existing = selected.filter((filePath) => pathExists(filePath));
  if (existing.length === 0) {
    console.log("[warn] No daemon log files found yet.");
    return;
  }

  if (follow) {
    console.log(`[info] Following logs (${existing.join(", ")})... Press Ctrl+C to stop.`);
    streamLogs(existing, lines);
    return;
  }

  for (const logPath of existing) {
    console.log(`\n===== ${logPath} (last ${lines} lines) =====`);
    const text = readLastLines(logPath, lines);
    if (text.trim()) console.log(text);
    else console.log("(empty)");
  }
}

async function uninstallCli({ yes = false } = {}) {
  if (!yes) {
    console.log("[warn] This will stop daemon processes and remove ~/.genxbot data.");
    console.log("[info] Re-run with: genxbot uninstall --yes");
    process.exit(1);
  }

  await stopDaemon({ silent: true });

  if (process.platform === "darwin") {
    const plistPath = daemonPlistPath();
    if (pathExists(plistPath)) {
      spawnSync("launchctl", ["unload", plistPath], { stdio: "ignore" });
      fs.rmSync(plistPath, { force: true });
      console.log(`[ok] Removed LaunchAgent: ${plistPath}`);
    }
  } else if (process.platform === "linux") {
    const svcPath = daemonSystemdPath();
    if (pathExists(svcPath)) {
      spawnSync("systemctl", ["--user", "disable", "--now", "genxbot.service"], { stdio: "ignore" });
      fs.rmSync(svcPath, { force: true });
      spawnSync("systemctl", ["--user", "daemon-reload"], { stdio: "ignore" });
      console.log(`[ok] Removed systemd user service: ${svcPath}`);
    }
  }

  writeDaemonMeta({
    ...readDaemonMeta(),
    pid: null,
    uninstallAt: new Date().toISOString(),
  });

  if (pathExists(APP_HOME)) {
    fs.rmSync(APP_HOME, { recursive: true, force: true });
    console.log(`[ok] Removed ${APP_HOME}`);
  }

  console.log("[done] GenXBot CLI uninstall cleanup complete.");
}

function checkPort(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve({ available: false }));
    server.once("listening", () => {
      server.close(() => resolve({ available: true }));
    });
    server.listen(port, "127.0.0.1");
  });
}

function probeHttp(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 1500 }, (res) => {
      resolve({ ok: res.statusCode >= 200 && res.statusCode < 500, statusCode: res.statusCode });
      res.resume();
    });
    req.on("error", (err) => resolve({ ok: false, error: err.message }));
    req.on("timeout", () => {
      req.destroy();
      resolve({ ok: false, error: "timeout" });
    });
  });
}

async function doctor({ json = false }) {
  const backendDir = detectBackendDir();
  const frontendDir = detectFrontendDir();
  const envValues = loadEnvValues();
  const envValidation = validateEnv(envValues);

  const checks = [];
  const add = (name, level, detail) => checks.push({ name, level, detail });

  const nodeVersion = versionFor("node", ["--version"]);
  add("node", nodeVersion ? "PASS" : "FAIL", nodeVersion || "node not found");
  const npmVersion = versionFor("npm", ["--version"]);
  add("npm", npmVersion ? "PASS" : "FAIL", npmVersion || "npm not found");
  const pyCommand = detectPythonCommand();
  const pyVersion = versionFor(pyCommand || "python3", ["--version"]);
  add("python", pyVersion ? "PASS" : "FAIL", pyVersion || "python3/python not found");
  const pipCommand = checkCommand("pip3") ? "pip3" : checkCommand("pip") ? "pip" : null;
  const pipVersion = versionFor(pipCommand || "pip3", ["--version"]);
  add("pip", pipVersion ? "PASS" : "WARN", pipVersion || "pip3/pip not found");
  const uvicornVersion = versionFor("uvicorn", ["--version"]);
  add("uvicorn", uvicornVersion ? "PASS" : "WARN", uvicornVersion || "uvicorn not found in PATH");
  const fastapiImportOk = checkPythonImport(pyCommand, "fastapi");
  add(
    "python_fastapi",
    fastapiImportOk ? "PASS" : "WARN",
    fastapiImportOk ? "fastapi import ok" : "fastapi import failed (activate venv and install backend requirements)",
  );

  add(
    "backend_dir",
    pathExists(path.join(backendDir, "requirements.txt")) ? "PASS" : "FAIL",
    backendDir,
  );
  add(
    "frontend_dir",
    pathExists(path.join(frontendDir, "package.json")) ? "PASS" : "WARN",
    frontendDir,
  );
  add(
    "backend_requirements",
    pathExists(path.join(backendDir, "requirements.txt")) ? "PASS" : "FAIL",
    path.join(backendDir, "requirements.txt"),
  );
  add(
    "frontend_node_modules",
    pathExists(path.join(frontendDir, "node_modules")) ? "PASS" : "WARN",
    pathExists(path.join(frontendDir, "node_modules"))
      ? "frontend dependencies installed"
      : "frontend dependencies missing (run npm install in frontend)",
  );

  add("app_home", pathExists(APP_HOME) ? "PASS" : "WARN", APP_HOME);
  add("log_dir", pathExists(LOG_DIR) ? "PASS" : "WARN", LOG_DIR);

  add("env_file", pathExists(ENV_PATH) ? "PASS" : "WARN", ENV_PATH);
  add(
    "openai_token",
    (envValues.OPENAI_API_KEY || "").trim() ? "PASS" : "WARN",
    (envValues.OPENAI_API_KEY || "").trim()
      ? `configured (${maskToken(envValues.OPENAI_API_KEY)})`
      : "missing (deterministic fallback mode will be used)",
  );
  add(
    "admin_token",
    (envValues.ADMIN_API_TOKEN || "").trim() ? "PASS" : "WARN",
    (envValues.ADMIN_API_TOKEN || "").trim()
      ? `configured (${maskToken(envValues.ADMIN_API_TOKEN)})`
      : "missing (admin endpoint protection may be limited)",
  );
  for (const warning of envValidation.warnings) {
    add("env_validation", "WARN", warning);
  }
  for (const error of envValidation.errors) {
    add("env_validation", "FAIL", error);
  }

  const backendPort = await checkPort(DEFAULT_BACKEND_PORT);
  add(
    "port_8000",
    backendPort.available ? "PASS" : "WARN",
    backendPort.available ? "port available" : "port in use (backend may already be running)",
  );
  const frontendPort = await checkPort(DEFAULT_FRONTEND_PORT);
  add(
    "port_5173",
    frontendPort.available ? "PASS" : "WARN",
    frontendPort.available ? "port available" : "port in use (frontend may already be running)",
  );

  const apiProbe = await probeHttp("http://127.0.0.1:8000/api/v1/runs");
  if (apiProbe.ok) {
    add("backend_api", "PASS", `reachable (status ${apiProbe.statusCode})`);
  } else {
    add("backend_api", "WARN", `unreachable (${apiProbe.error || "not running"})`);
  }

  const summary = {
    PASS: checks.filter((c) => c.level === "PASS").length,
    WARN: checks.filter((c) => c.level === "WARN").length,
    FAIL: checks.filter((c) => c.level === "FAIL").length,
  };

  if (json) {
    console.log(JSON.stringify({ checks, summary }, null, 2));
  } else {
    console.log("[info] GenXBot doctor report\n");
    for (const item of checks) {
      printCheck(item.level, `${item.name}: ${item.detail}`);
    }
    console.log(`\n[summary] pass=${summary.PASS} warn=${summary.WARN} fail=${summary.FAIL}`);
  }

  if (summary.FAIL > 0) {
    process.exit(1);
  }
}

function onboard({ installDaemonFlag }) {
  const backendDir = detectBackendDir();
  const firstRun = !pathExists(ENV_PATH);
  console.log("[info] Starting GenXBot onboarding...");
  ensureDir(APP_HOME);
  ensureDir(LOG_DIR);
  writeEnvTemplate();

  const values = loadEnvValues();
  values.AGENT_RUNTIME_MODE = (values.AGENT_RUNTIME_MODE || "single").trim().toLowerCase();
  if (!["single", "multi", "hybrid"].includes(values.AGENT_RUNTIME_MODE)) {
    values.AGENT_RUNTIME_MODE = "single";
  }
  values.CHANNEL_WEBHOOK_SECURITY_ENABLED =
    (values.CHANNEL_WEBHOOK_SECURITY_ENABLED || "false").trim().toLowerCase() === "true"
      ? "true"
      : "false";
  fs.writeFileSync(ENV_PATH, renderEnv(values), "utf8");

  console.log(`[ok] App home: ${APP_HOME}`);
  console.log(`[ok] Env file: ${ENV_PATH}`);
  if (firstRun) {
    console.log("[info] First run detected. Applied safe defaults:");
    console.log("       - AGENT_RUNTIME_MODE=single");
    console.log("       - CHANNEL_WEBHOOK_SECURITY_ENABLED=false");
  }

  const hasNode = checkCommand("node");
  const hasNpm = checkCommand("npm");
  const hasPy3 = checkCommand("python3") || checkCommand("python");

  console.log(`[check] node: ${hasNode ? "ok" : "missing"}`);
  console.log(`[check] npm: ${hasNpm ? "ok" : "missing"}`);
  console.log(`[check] python: ${hasPy3 ? "ok" : "missing"}`);

  runBackendProbe();

  const validation = validateEnv(values);
  for (const warning of validation.warnings) {
    printCheck("WARN", warning);
  }
  for (const error of validation.errors) {
    printCheck("FAIL", error);
  }

  if (!values.OPENAI_API_KEY) {
    console.log("[info] Fallback behavior: without OPENAI_API_KEY, GenXBot uses deterministic fallback mode.");
  }

  if (installDaemonFlag) {
    installDaemon();
  }

  console.log("[done] Onboarding complete.");
  console.log("Next:");
  console.log("  1) Run `genxbot onboard --interactive` for guided token setup and validation");
  console.log("  2) Run `genxbot doctor` for full preflight diagnostics");
  console.log(`  3) Start backend manually: cd ${backendDir} && uvicorn app.main:app --reload --port 8000`);
}

async function main() {
  const args = process.argv.slice(2);
  const command = args[0];

  if (!command || command === "help" || command === "--help" || command === "-h") {
    printHelp();
    process.exit(0);
  }

  if (command === "onboard") {
    const installDaemonFlag = args.includes("--install-daemon");
    const interactive = args.includes("--interactive");
    const yes = args.includes("--yes");
    if (interactive) {
      await interactiveOnboard({ yes });
      if (installDaemonFlag) installDaemon();
      process.exit(0);
    }
    onboard({ installDaemonFlag });
    process.exit(0);
  }

  if (command === "doctor") {
    const asJson = args.includes("--json");
    await doctor({ json: asJson });
    process.exit(0);
  }

  if (command === "start") {
    await startDaemon();
    process.exit(0);
  }

  if (command === "stop") {
    const stopped = await stopDaemon();
    process.exit(stopped ? 0 : 1);
  }

  if (command === "status") {
    const asJson = args.includes("--json");
    await daemonStatus({ json: asJson });
    process.exit(0);
  }

  if (command === "logs") {
    showLogs(args.slice(1));
    return;
  }

  if (command === "uninstall") {
    const yes = args.includes("--yes");
    await uninstallCli({ yes });
    process.exit(0);
  }

  console.error(`[error] Unknown command: ${command}`);
  printHelp();
  process.exit(1);
}

main();
