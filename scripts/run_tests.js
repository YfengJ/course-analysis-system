const { spawnSync } = require("node:child_process");
const path = require("node:path");

const projectRoot = path.resolve(__dirname, "..");
const testScript = path.join(projectRoot, "scripts", "run_tests.py");
const configuredPython = process.env.PYTHON ? [[process.env.PYTHON]] : [];
const candidates = process.platform === "win32"
  ? [
      ...configuredPython,
      [path.join(projectRoot, ".venv", "Scripts", "python.exe")],
      ["py", "-3"],
      ["python"],
    ]
  : [
      ...configuredPython,
      [path.join(projectRoot, ".venv", "bin", "python")],
      ["python3"],
      ["python"],
    ];

for (const [command, ...prefixArgs] of candidates) {
  const result = spawnSync(command, [...prefixArgs, testScript], {
    cwd: projectRoot,
    stdio: "inherit",
  });

  if (!result.error) {
    process.exit(result.status ?? 1);
  }
  if (result.error.code !== "ENOENT") {
    throw result.error;
  }
}

console.error("No Python interpreter was found. Set PYTHON or install Python 3.12+.");
process.exit(127);
