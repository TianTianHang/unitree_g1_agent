# Sport API Ack Stuck on Pending

## Symptoms

- First `walk` command via voice succeeds.
- Second `walk` command is rejected by `safety_control_node`:
  ```
  rejecting loco intent: robot health not ok: degraded;
  checks={'lowstate_fresh': True, 'health_ok': False}
  ```
- `g1_interface_node` repeatedly logs:
  ```
  ignoring invalid sport API response: Expecting value: line 1 column 1 (char 0)
  published zero velocity: reason=command_deadline
  ```

## Root Cause

The health state degrades because the command acknowledgment (`last_command_ack`) is stuck in the `"pending"` state.

### Chain of Events

1. `on_safe_loco()` → `_publish_velocity_command()` sends a `set_velocity` (API 7105) request via the Unitree sport API, then immediately sets:

   ```python
   # g1_interface/node.py:472-479
   self.last_command_ack = {
       "sequence_id": sequence_id,
       "state": "pending",           # <-- immediately "pending"
       "code": None,
       "command_kind": command_kind,
       "stop_reason": stop_reason,
       "updated_monotonic_sec": now_sec,
   }
   ```

2. `publish_health()` fires every 200ms. `build_health_status()` checks `last_command_ack.state` at `node.py:62`:

   ```python
   command_ack_unhealthy = public_command_ack.get("state") in {"pending", "rejected", "timed_out"}
   ```

   Since state is `"pending"`, the health state is set to `"degraded"` (`node.py:75`).

3. The Unitree robot responds on `/api/sport/response`. The response `data`/`parameter` payload is **empty or not valid JSON** (probably because `set_velocity` is a fire-and-forget API that returns a minimal or empty payload).

4. `SportApiClient.record_response()` (`sport_api.py:53`) calls `decode_response_payload()` which attempts `json.loads()` on the payload. This raises `json.JSONDecodeError`.

5. `on_sport_response()` catches the exception and **exits early without updating `last_command_ack`**:

   ```python
   # g1_interface/node.py:382-384
   except (json.JSONDecodeError, TypeError, ValueError) as exc:
       self.node.get_logger().warning(f"ignoring invalid sport API response: {exc}")
       return
   ```

6. The ack never transitions to `"acknowledged"`. Health stays `"degraded"`.

7. `safety_control_node` receives `health_state="degraded"` → rejects all subsequent loco intents because `health_state != "ok"` (`safety_control/validator.py:127-129`).

8. Meanwhile, `watchdog_tick` → `_expire_api_requests` times out the pending request (500ms timeout) and sets state to `"timed_out"`, then issues a stop command which creates a *new* `"pending"` ack, perpetuating the cycle.

### Why the First Walk Succeeds

At startup, `health_state` is `"ok"` (no pending ack). The first loco intent passes validation. By the time the health degrades, the command is already executing. The second intent arrives after health is already degraded.

## Solution: Separate Payload Parsing from Ack Update

The `record_response()` method should **not fail the entire response** when the payload is unparseable. The status code in `header.status.code` is sufficient to acknowledge the command.

### Proposed Changes

**`src/g1_interface/g1_interface/sport_api.py`** — `record_response()`:

- Wrap `decode_response_payload(msg)` in a try/except.
- If payload parsing fails, return `{"matched": True, "code": status_code, "payload": {}}` (or `None`) instead of raising.
- Log a warning but do not prevent the caller from updating the ack.

```python
def record_response(self, msg: object, now_sec: float) -> dict[str, object]:
    identity = getattr(getattr(msg, "header", None), "identity", None)
    status = getattr(getattr(msg, "header", None), "status", None)
    sequence_id = int(getattr(identity, "id", 0))
    api_id = int(getattr(identity, "api_id", 0))
    pending = self._pending.get(sequence_id)
    
    payload = None
    try:
        payload = decode_response_payload(msg)
    except (json.JSONDecodeError, ValueError) as exc:
        # Payload is optional — the status code alone is enough to ack
        pass
    
    if pending is None:
        return {"matched": False, "sequence_id": sequence_id, ...}
    if api_id != pending.api_id:
        return {"matched": False, "sequence_id": sequence_id, ...}
    
    self._pending.pop(sequence_id, None)
    return {
        "matched": True,
        "sequence_id": pending.sequence_id,
        "api_id": pending.api_id,
        "action": pending.action,
        "code": int(getattr(status, "code", -1)),
        "latency_ms": ...,
        "payload": payload or {},
    }
```

**`src/g1_interface/g1_interface/node.py`** — `on_sport_response()`:

- Remove the try/except wrapper since `record_response()` no longer raises on payload errors.
- Or keep it but only for unexpected errors, not payload parsing failures.

```python
def on_sport_response(self, msg):
    now_sec = self._monotonic_sec()
    result = self._sport_api.record_response(msg, now_sec=now_sec)
    self.last_api_result = result
    self.last_sport_response_monotonic_sec = now_sec
    if result.get("matched") is True:
        self.consecutive_api_timeouts = 0
    self._update_command_ack_from_response(result, now_sec)
    self._update_sport_state_from_response(result, now_sec)
```

### Flow After Fix

1. Walk command sent → ack = `"pending"`.
2. Robot responds with status code (e.g. code=0 for success, code!=0 for failure).
3. `record_response()` parses the response, payload decode fails but is **silently handled**. Returns `{"matched": True, "code": 0}`.
4. `_update_command_ack_from_response()` sees `code == 0` → changes ack to `"acknowledged"`.
5. Next `publish_health()` sees `state="acknowledged"` → health is `"ok"`.
6. Subsequent loco intents pass safety validation.

## Affected Files

| File | Lines | Role |
|------|-------|------|
| `src/g1_interface/g1_interface/sport_api.py` | 53-88 | `record_response()` — payload parse fail kills the response |
| `src/g1_interface/g1_interface/sport_api.py` | 101-116 | `decode_response_payload()` — raises on empty/invalid payload |
| `src/g1_interface/g1_interface/node.py` | 378-384 | `on_sport_response()` — catches and discards the response |
