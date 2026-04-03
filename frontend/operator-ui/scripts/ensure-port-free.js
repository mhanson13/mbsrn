#!/usr/bin/env node

const { spawnSync } = require("node:child_process");

const DEFAULT_PORT = 3201;
const requestedPort = Number.parseInt(process.env.MBSRN_DEV_PORT || "", 10);
const port = Number.isFinite(requestedPort) && requestedPort > 0 ? requestedPort : DEFAULT_PORT;

function runCommand(command, args) {
  return spawnSync(command, args, { encoding: "utf8" });
}

function parsePort(address) {
  const value = String(address || "").trim();
  if (!value) {
    return null;
  }
  const suffix = value.slice(value.lastIndexOf(":") + 1);
  const parsed = Number.parseInt(suffix, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function listeningPidsWindows(targetPort) {
  const result = runCommand("netstat", ["-ano", "-p", "tcp"]);
  if (result.error || typeof result.stdout !== "string") {
    return [];
  }
  const pids = new Set();
  const lines = result.stdout.split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || !trimmed.includes("LISTENING")) {
      continue;
    }
    const parts = trimmed.split(/\s+/);
    if (parts.length < 5) {
      continue;
    }
    const localAddress = parts[1];
    const state = parts[3];
    const pid = Number.parseInt(parts[4], 10);
    if (state !== "LISTENING" || !Number.isFinite(pid)) {
      continue;
    }
    if (parsePort(localAddress) === targetPort) {
      pids.add(pid);
    }
  }
  return Array.from(pids);
}

function listeningPidsLsof(targetPort) {
  const result = runCommand("lsof", ["-t", "-i", `TCP:${targetPort}`, "-sTCP:LISTEN"]);
  if (result.error || result.status !== 0 || typeof result.stdout !== "string") {
    return [];
  }
  return result.stdout
    .split(/\r?\n/)
    .map((value) => Number.parseInt(value.trim(), 10))
    .filter((value) => Number.isFinite(value));
}

function listeningPidsSs(targetPort) {
  const result = runCommand("ss", ["-ltnp"]);
  if (result.error || result.status !== 0 || typeof result.stdout !== "string") {
    return [];
  }
  const pids = new Set();
  const lines = result.stdout.split(/\r?\n/);
  for (const line of lines) {
    if (!line.includes("LISTEN")) {
      continue;
    }
    const portMatch = line.match(/:(\d+)\s/);
    if (!portMatch || Number.parseInt(portMatch[1], 10) !== targetPort) {
      continue;
    }
    const pidMatches = line.match(/pid=(\d+)/g);
    if (!pidMatches) {
      continue;
    }
    for (const match of pidMatches) {
      const pid = Number.parseInt(match.replace("pid=", ""), 10);
      if (Number.isFinite(pid)) {
        pids.add(pid);
      }
    }
  }
  return Array.from(pids);
}

function listeningPidsNetstat(targetPort) {
  const result = runCommand("netstat", ["-ltnp"]);
  if (result.error || result.status !== 0 || typeof result.stdout !== "string") {
    return [];
  }
  const pids = new Set();
  const lines = result.stdout.split(/\r?\n/);
  for (const line of lines) {
    if (!line.includes("LISTEN")) {
      continue;
    }
    const parts = line.trim().split(/\s+/);
    if (parts.length < 7) {
      continue;
    }
    const localAddress = parts[3];
    const pidProgram = parts[6];
    if (parsePort(localAddress) !== targetPort) {
      continue;
    }
    const pidText = pidProgram.split("/")[0];
    const pid = Number.parseInt(pidText, 10);
    if (Number.isFinite(pid)) {
      pids.add(pid);
    }
  }
  return Array.from(pids);
}

function getListeningPids(targetPort) {
  if (process.platform === "win32") {
    return listeningPidsWindows(targetPort);
  }
  const lsofPids = listeningPidsLsof(targetPort);
  if (lsofPids.length > 0) {
    return lsofPids;
  }
  const ssPids = listeningPidsSs(targetPort);
  if (ssPids.length > 0) {
    return ssPids;
  }
  return listeningPidsNetstat(targetPort);
}

function killPid(pid, force = false) {
  if (!Number.isFinite(pid) || pid === process.pid) {
    return true;
  }
  if (process.platform === "win32") {
    const args = force ? ["/PID", String(pid), "/T", "/F"] : ["/PID", String(pid), "/T"];
    const result = runCommand("taskkill", args);
    return !result.error;
  }
  try {
    process.kill(pid, force ? "SIGKILL" : "SIGTERM");
    return true;
  } catch {
    return false;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function freePort(targetPort) {
  const initialPids = getListeningPids(targetPort).filter((pid) => pid !== process.pid);
  if (initialPids.length === 0) {
    console.log(`[dev-port] Port ${targetPort} is already free.`);
    return true;
  }

  console.log(`[dev-port] Port ${targetPort} is in use by PID(s): ${initialPids.join(", ")}.`);
  console.log(`[dev-port] Attempting graceful shutdown...`);
  for (const pid of initialPids) {
    killPid(pid, false);
  }

  await sleep(350);
  let remaining = getListeningPids(targetPort).filter((pid) => pid !== process.pid);
  if (remaining.length === 0) {
    console.log(`[dev-port] Port ${targetPort} has been released.`);
    return true;
  }

  console.log(`[dev-port] Port ${targetPort} still occupied by PID(s): ${remaining.join(", ")}. Forcing stop...`);
  for (const pid of remaining) {
    killPid(pid, true);
  }

  await sleep(350);
  remaining = getListeningPids(targetPort).filter((pid) => pid !== process.pid);
  if (remaining.length === 0) {
    console.log(`[dev-port] Port ${targetPort} has been released.`);
    return true;
  }

  console.error(`[dev-port] Unable to free port ${targetPort}; still in use by PID(s): ${remaining.join(", ")}.`);
  return false;
}

async function main() {
  const ok = await freePort(port);
  if (!ok) {
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(`[dev-port] Unexpected error while preparing port ${port}:`, error);
  process.exit(1);
});
