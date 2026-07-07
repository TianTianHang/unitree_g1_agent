# Pi Extension Layout Design

## Context

The current Pi robot tools extension lives under `.agent-runtime/.unitree_agent/.pi/extensions/robot-tools.ts`.
That path mixes three separate concerns:

- `.agent-runtime/pi`: downloaded Pi source/cache
- `.agent-runtime/.unitree_agent`: Pi runtime workspace
- `robot-tools.ts`: project-owned Unitree voice bridge extension source

Project-owned extension source should not live under `.agent-runtime`, because that directory is runtime/cache oriented and can be regenerated or cleaned independently of source changes.

## Decision

Move the project-owned Pi extension source to:

```text
src/voice_bridge/pi_extensions/robot-tools.ts
```

Keep runtime/download paths separate:

```text
.agent-runtime/pi/                  # downloaded Pi source/cache
.agent-runtime/.unitree_agent/       # Pi runtime workspace
src/voice_bridge/pi_extensions/      # tracked project Pi extensions
```

## Configuration Model

The default `agent.pi.workspace` remains:

```yaml
workspace: ".agent-runtime/.unitree_agent"
```

The default `agent.pi.extensions` should include the tracked extension path:

```yaml
extensions:
  - "src/voice_bridge/pi_extensions/robot-tools.ts"
```

`build_pi_command()` should load configured extensions explicitly. The current automatic lookup of `workspace/.pi/extensions/robot-tools.ts` may be retained temporarily for compatibility, but the source-of-truth path for this project should be the configured tracked extension.

## Migration Scope

The migration should:

- Move `robot-tools.ts` from `.agent-runtime/.unitree_agent/.pi/extensions/` to `src/voice_bridge/pi_extensions/`.
- Update default config and YAML so the tracked extension is listed in `agent.pi.extensions`.
- Update command-building tests to expect the configured tracked extension.
- Update README documentation to describe `.agent-runtime` as runtime/cache only.
- Avoid touching `.agent-runtime/pi`, which is downloaded Pi source/cache.

## Success Criteria

- No project-owned source files remain under `.agent-runtime/.unitree_agent/.pi/extensions/`.
- Pi command construction still includes `-e src/voice_bridge/pi_extensions/robot-tools.ts`.
- Existing Pi RPC unit tests pass.
- Real Pi smoke test still passes when `PI_AGENT_INTEGRATION=1` and `pi` is configured.
