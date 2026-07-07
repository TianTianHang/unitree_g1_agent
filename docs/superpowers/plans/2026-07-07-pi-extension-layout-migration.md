# Pi Extension Layout Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the project-owned Pi robot tools extension out of `.agent-runtime` and into tracked source at `src/voice_bridge/pi_extensions/robot-tools.ts`.

**Architecture:** Keep `.agent-runtime` as runtime/download/cache space only. Make the tracked extension path explicit through `agent.pi.extensions`, while retaining the existing workspace auto-discovery behavior for compatibility. Treat configured relative extension paths as repo-relative and pass absolute paths to Pi.

**Tech Stack:** Python 3.10+, pytest, YAML config, TypeScript Pi extension API.

## Global Constraints

- Do not touch `.agent-runtime/pi`, which is downloaded Pi source/cache.
- Keep `agent.pi.workspace` defaulted to `.agent-runtime/.unitree_agent`.
- Make `src/voice_bridge/pi_extensions/robot-tools.ts` the project source-of-truth extension path.
- Resolve configured relative extension paths to absolute paths before passing them to Pi.
- Preserve compatibility with existing `workspace/.pi/extensions/robot-tools.ts` auto-discovery.
- Run unit tests with `PYTHONPATH=src/voice_bridge /usr/bin/python3 -m pytest ...`.

---

## File Structure

- Move: `.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts` to `src/voice_bridge/pi_extensions/robot-tools.ts`.
- Modify: `src/voice_bridge/voice_bridge/pi_config.py` to default `extensions` to the tracked extension path.
- Modify: `src/voice_bridge/config/voice_bridge.yaml` to list the tracked extension path.
- Modify: `src/voice_bridge/tests/test_pi_config.py` to assert configured extension loading and workspace fallback compatibility.
- Modify: `src/voice_bridge/README.md` to document `.agent-runtime` as runtime/cache only.

### Task 1: Extension Path Configuration

**Files:**
- Modify: `src/voice_bridge/tests/test_pi_config.py`
- Modify: `src/voice_bridge/voice_bridge/pi_config.py`
- Modify: `src/voice_bridge/config/voice_bridge.yaml`

**Interfaces:**
- Consumes: `DEFAULT_PI_CONFIG`, `build_pi_command(pi_config: dict[str, Any], workspace: Path, repo_root: Path | None = None) -> list[str]`
- Produces: default `agent.pi.extensions == ["src/voice_bridge/pi_extensions/robot-tools.ts"]`

- [ ] **Step 1: Write failing config tests**

Add this test to `src/voice_bridge/tests/test_pi_config.py`:

```python
def test_default_pi_config_lists_tracked_robot_tools_extension():
    assert DEFAULT_PI_CONFIG["extensions"] == ["src/voice_bridge/pi_extensions/robot-tools.ts"]
```

Update `test_build_pi_command_loads_robot_tools_when_present` so it passes `extensions: []` and verifies workspace auto-discovery still works.

Add this test:

```python
def test_build_pi_command_loads_configured_extensions_without_workspace_tools(tmp_path: Path):
    workspace = tmp_path / ".agent-runtime" / ".unitree_agent"
    repo_root = tmp_path / "repo"

    command = build_pi_command(
        {
            "command": "pi",
            "args": ["--mode", "rpc", "--no-session"],
            "extensions": ["src/voice_bridge/pi_extensions/robot-tools.ts"],
            "append_system_prompt": "",
        },
        workspace,
        repo_root=repo_root,
    )

    assert command == [
        "pi",
        "--mode",
        "rpc",
        "--no-session",
        "-e",
        str(repo_root / "src/voice_bridge/pi_extensions/robot-tools.ts"),
    ]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src/voice_bridge /usr/bin/python3 -m pytest src/voice_bridge/tests/test_pi_config.py -q
```

Expected: `test_default_pi_config_lists_tracked_robot_tools_extension` fails because defaults still use an empty extension list.

- [ ] **Step 3: Update default config**

In `src/voice_bridge/voice_bridge/pi_config.py`, add:

```python
DEFAULT_ROBOT_TOOLS_EXTENSION = "src/voice_bridge/pi_extensions/robot-tools.ts"
```

Add a helper that resolves configured relative extension paths against the repo root:

```python
def _resolve_extension_path(extension: str, repo_root: Path | None) -> str:
    path = Path(extension)
    if path.is_absolute():
        return str(path)
    root = repo_root or resolve_repo_root()
    return str(root / path)
```

Change `build_pi_command()` to accept an optional repo root and use the helper:

```python
def build_pi_command(pi_config: dict[str, Any], workspace: Path, repo_root: Path | None = None) -> list[str]:
    ...
    for extension in pi_config.get("extensions", []):
        cmd.extend(["-e", _resolve_extension_path(str(extension), repo_root)])
```

Change `DEFAULT_PI_CONFIG["extensions"]` to:

```python
"extensions": [DEFAULT_ROBOT_TOOLS_EXTENSION],
```

In `src/voice_bridge/config/voice_bridge.yaml`, change:

```yaml
    extensions: []
```

to:

```yaml
    extensions:
      - "src/voice_bridge/pi_extensions/robot-tools.ts"
```

In `src/voice_bridge/voice_bridge/pi_agent.py`, pass the resolved repo root into command construction:

```python
command = build_pi_command(self._pi_config, self._workspace, repo_root=self._repo_root)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
PYTHONPATH=src/voice_bridge /usr/bin/python3 -m pytest src/voice_bridge/tests/test_pi_config.py src/voice_bridge/tests/test_config.py -q
```

Expected: all selected tests pass.

### Task 2: Move Extension Source and Docs

**Files:**
- Create: `src/voice_bridge/pi_extensions/robot-tools.ts`
- Delete: `.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts`
- Modify: `src/voice_bridge/README.md`

**Interfaces:**
- Produces: tracked Pi extension source at `src/voice_bridge/pi_extensions/robot-tools.ts`
- Removes: project-owned source from `.agent-runtime/.unitree_agent/.pi/extensions/`

- [ ] **Step 1: Move the extension source**

Move the current content of `.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts` to:

```text
src/voice_bridge/pi_extensions/robot-tools.ts
```

Delete the old tracked file:

```text
.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts
```

- [ ] **Step 2: Update README**

In `src/voice_bridge/README.md`, replace the Pi RPC backend sentence:

```markdown
Set `agent.backend: pi_rpc` to run Pi Agent as a JSONL RPC subprocess. The default workspace is `.agent-runtime/.unitree_agent`, and `voice_bridge` loads `.pi/extensions/robot-tools.ts` with `-e` when the file exists.
```

with:

```markdown
Set `agent.backend: pi_rpc` to run Pi Agent as a JSONL RPC subprocess. The default workspace is `.agent-runtime/.unitree_agent`; `.agent-runtime` is runtime/cache space only. The project-owned robot tools extension lives at `src/voice_bridge/pi_extensions/robot-tools.ts` and is loaded through `agent.pi.extensions`.
```

- [ ] **Step 3: Run focused tests**

Run:

```bash
PYTHONPATH=src/voice_bridge /usr/bin/python3 -m pytest src/voice_bridge/tests/test_pi_config.py src/voice_bridge/tests/test_pi_integration.py -q
```

Expected: config tests pass; integration test is skipped unless `PI_AGENT_INTEGRATION=1`.

### Task 3: Final Verification and Commit

**Files:**
- All files changed in Tasks 1-2

**Interfaces:**
- Produces: committed migration with passing tests

- [ ] **Step 1: Run full tests**

Run:

```bash
source /opt/ros/humble/setup.bash && PYTHONPATH=src/voice_bridge /usr/bin/python3 -m pytest src/voice_bridge/tests -q
```

Expected: all unit tests pass, with Pi integration skipped unless `PI_AGENT_INTEGRATION=1`.

- [ ] **Step 2: Run real Pi smoke test**

Run:

```bash
PI_AGENT_INTEGRATION=1 PYTHONPATH=src/voice_bridge /usr/bin/python3 -m pytest src/voice_bridge/tests/test_pi_integration.py -q
```

Expected: `1 passed`.

- [ ] **Step 3: Commit**

Run:

```bash
git add src/voice_bridge/tests/test_pi_config.py src/voice_bridge/voice_bridge/pi_config.py src/voice_bridge/config/voice_bridge.yaml src/voice_bridge/pi_extensions/robot-tools.ts src/voice_bridge/README.md .agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts docs/superpowers/plans/2026-07-07-pi-extension-layout-migration.md
git commit -m "refactor: move pi robot tools extension into source"
```

Expected: one commit containing the migration and plan.

## Self-Review

- Spec coverage: default tracked extension path, runtime/cache separation, explicit `agent.pi.extensions`, compatibility with workspace auto-discovery, docs, and tests are covered.
- Placeholder scan: no TBD/TODO/deferred implementation markers remain.
- Type consistency: the plan uses existing `DEFAULT_PI_CONFIG` and `build_pi_command()` signatures unchanged.
