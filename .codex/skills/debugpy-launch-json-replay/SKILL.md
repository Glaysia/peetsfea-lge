---
title: Debugpy Launch Replay
created: 2026-04-17 @ 09:09
updated: 2026-04-17 @ 09:09
tags:
  - governance
name: debugpy-launch-json-replay
description: Recreate this repository's VS Code `debugpy` launch configuration from the terminal by inspecting `.vscode/launch.json` and related task files. Use when the user asks to reproduce `launch.json`, replay the exact debug run, or compare terminal execution with the repo's VS Code debug path.
---

# Debugpy Launch Replay

Reconstruct the exact shell-visible execution path that this repository's `.vscode/launch.json` would use.

## Workflow

1. Read `.vscode/launch.json`.
2. Identify the requested configuration by `name`.
3. Resolve these fields exactly if present:
   - `python`
   - `program`
   - `cwd`
   - `args`
   - `env`
   - `preLaunchTask`
4. If `preLaunchTask` is set, read `.vscode/tasks.json` and expand dependency order exactly.
5. Resolve `${workspaceFolder}` to the repository root.
6. Replay the prelaunch shell steps first.
7. Run the launch command from the resolved `cwd` with the resolved `env`.

## Rules

- Treat `.vscode/launch.json` as the source of truth for the debug launch.
- Treat `.vscode/tasks.json` as the source of truth for preparation steps.
- Preserve `cwd` exactly. Do not substitute a different working directory.
- Preserve declared environment variables exactly.
- Prefer reproducing the terminal effect of the launch, not inventing a custom debug command.
- If the launch config is `request: "attach"`, report the attach parameters instead of pretending it is a launch.
- If the repo has explicit task sequencing, do not skip it.

## Output

When replaying a launch config, report:

- The configuration name.
- The resolved prelaunch task chain.
- The resolved launch command.
- The resolved `cwd`.
- The resolved environment overrides.

If you actually run it, state which steps were executed and whether the result matched the launch configuration.

## Repo Note

This repository uses `preLaunchTask` to enforce setup and cleanup before debug runs. Respect that sequence when reproducing `Run entry/sample_build.py from run/`.
