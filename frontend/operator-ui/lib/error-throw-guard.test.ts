import fs from "node:fs";
import path from "node:path";

type Violation = {
  file: string;
  line: number;
  pattern: string;
  source: string;
};

const REPO_ROOT = path.resolve(__dirname, "..");
const SOURCE_DIRS = ["app", "components", "lib"].map((segment) => path.join(REPO_ROOT, segment));

const DISALLOWED_PATTERNS: Array<{ pattern: string; regex: RegExp }> = [
  { pattern: "throw null", regex: /\bthrow\s+null\b/ },
  { pattern: "throw undefined", regex: /\bthrow\s+undefined\b/ },
  { pattern: "Promise.reject(null)", regex: /\bPromise\.reject\(\s*null\s*\)/ },
  { pattern: "Promise.reject(undefined)", regex: /\bPromise\.reject\(\s*undefined\s*\)/ },
  {
    pattern: "throw unknown variable (err/error/etc)",
    regex: /\bthrow\s+(error|err|innerError|result|response|data|reason)\b/,
  },
];

function listSourceFiles(baseDir: string): string[] {
  const entries = fs.readdirSync(baseDir, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    const fullPath = path.join(baseDir, entry.name);
    if (entry.isDirectory()) {
      files.push(...listSourceFiles(fullPath));
      continue;
    }
    if (!entry.isFile()) {
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry.name)) {
      continue;
    }
    if (/\.test\.(ts|tsx)$/.test(entry.name)) {
      continue;
    }
    files.push(fullPath);
  }
  return files;
}

function findViolations(filePath: string): Violation[] {
  const relativePath = path.relative(REPO_ROOT, filePath).replace(/\\/g, "/");
  const lines = fs.readFileSync(filePath, "utf-8").split(/\r?\n/);
  const violations: Violation[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const source = lines[index];
    if (!source || source.trimStart().startsWith("//")) {
      continue;
    }
    for (const candidate of DISALLOWED_PATTERNS) {
      if (!candidate.regex.test(source)) {
        continue;
      }
      violations.push({
        file: relativePath,
        line: index + 1,
        pattern: candidate.pattern,
        source: source.trim(),
      });
    }
  }

  return violations;
}

describe("operator-ui throw guard", () => {
  it("does not contain null/unknown throw patterns in app runtime source", () => {
    const files = SOURCE_DIRS.flatMap((sourceDir) => listSourceFiles(sourceDir));
    const violations = files.flatMap((filePath) => findViolations(filePath));

    const summary = violations
      .map((violation) => `${violation.file}:${violation.line} [${violation.pattern}] ${violation.source}`)
      .join("\n");

    expect(summary).toBe("");
  });
});
