#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

function fail(message) {
  console.error(`[runtime-check] ${message}`);
  process.exit(1);
}

const workspaceRoot = process.cwd();
const standaloneRoot = path.join(workspaceRoot, ".next", "standalone");
const standaloneServerPath = path.join(standaloneRoot, "server.js");
const standaloneSharpPackagePath = path.join(standaloneRoot, "node_modules", "sharp", "package.json");

if (!fs.existsSync(standaloneServerPath)) {
  fail("Missing .next/standalone/server.js. Run `npm run build` first.");
}

try {
  const resolvedSharp = require.resolve("sharp");
  console.log(`[runtime-check] sharp resolved at ${resolvedSharp}`);
} catch (error) {
  fail(`Unable to resolve sharp from package dependencies: ${error instanceof Error ? error.message : "unknown error"}`);
}

if (!fs.existsSync(standaloneSharpPackagePath)) {
  fail("Missing sharp in .next/standalone/node_modules. Standalone runtime would fail image optimization.");
}

console.log("[runtime-check] standalone runtime packaging includes sharp.");
