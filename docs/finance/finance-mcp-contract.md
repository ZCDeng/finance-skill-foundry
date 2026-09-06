# Finance MCP Contract

This adapter exposes the stage-7 finance service through a local stdio Model Context Protocol server. It is intentionally a thin boundary around `FinanceStore`: it does not launch Claude Desktop, mutate global desktop configuration, accept arbitrary file paths as tool input, or receive source-system credentials.

## Protocol Basis

The server implements the MCP `2025-06-18` lifecycle over stdio:

- `initialize` negotiates `protocolVersion` and declares the `tools` capability.
- `notifications/initialized` marks the connection ready for normal tool traffic.
- `ping` returns an empty JSON-RPC result.
- `tools/list` returns the finance tool schemas.
- `tools/call` dispatches the allowed finance methods.

The protocol choice follows the official MCP specification:

- MCP uses JSON-RPC 2.0 messages between hosts, clients, and servers, and the specification is authoritative over protocol requirements: <https://modelcontextprotocol.io/specification/2026-07-28>.
- The `2025-06-18` transport spec defines stdio as a standard transport where the client launches the server as a subprocess, the server reads JSON-RPC messages from stdin and writes JSON-RPC messages to stdout, and messages are newline-delimited UTF-8 JSON-RPC with no non-MCP stdout: <https://modelcontextprotocol.io/specification/2025-06-18/basic/transports>.
- The lifecycle spec requires `initialize` as the first interaction, an `initialized` notification after success, and protocol-version negotiation where the server returns the requested version if supported or another supported version otherwise: <https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle>.
- The ping utility is a standard JSON-RPC request that must return an empty result promptly: <https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/ping>.
- The tools spec defines `tools/list`, `tools/call`, tool `inputSchema`, structured tool results, and JSON-RPC protocol errors for unknown tools or invalid arguments: <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>.
- The MCP authorization spec is for HTTP-based transports. It says stdio implementations should not follow that HTTP authorization flow and should retrieve credentials from the environment instead: <https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization>.

## Invocation

The module is directly runnable:

```bash
FOUNDRY_MCP_VAR_ROOT=/path/to/var \
FOUNDRY_MCP_GRANT_ID=<grant-id> \
FOUNDRY_MCP_TOKEN=<token-shown-once> \
python -m foundry.finance_mcp
```

The token is intentionally not accepted as a command-line argument, so it does not appear in normal process listings.

The stable Python grant API is:

```python
from pathlib import Path

from foundry.finance_mcp import create_stdio_grant, revoke_stdio_grant

grant = create_stdio_grant(
    Path("/path/to/var"),
    task_id="<32-hex task id>",
    session_id="<registered analysis session>",
    snapshot_ids=["<32-hex dataset snapshot id>"],
    context_ids=["<32-hex finance context id>"],
)

env = grant["env"]
command = grant["command"]
revoke_stdio_grant(Path("/path/to/var"), grant["grant_id"])
```

The packaged CLI integration surface lives in `foundry.finance_mcp`:

- `add_parsers(subparsers)` registers `finance-mcp-serve`, `finance-mcp-grant --spec`, and `finance-mcp-revoke --grant-id`.
- `dispatch(args)` handles those commands and returns `True` when it owns the command.

`finance-mcp-grant --spec` is a local-operator command. The spec must provide `task_id`, `session_id`, and the intended `snapshot_ids`; it may also provide `context_ids`, `config_path`, `server_name`, and `frozen`. The command writes a protected MCP client config file and prints only `{"config_path", "grant_id"}`. It refuses session-bound invocation such as `--session`, because grant issuance and revocation are local-operator actions rather than session-driven assistant actions. It does not print the grant token or accept the token in argv. `finance-mcp-revoke --grant-id` flips the stored grant revocation flag and is also refused when invoked with `--session`. `finance-mcp-serve` reads its grant id, token, and var root from the grant environment.

Development client configs use `[sys.executable, "-m", "foundry.finance_mcp"]`. Frozen/package configs use `[sys.executable, "finance-mcp-serve"]`, so root packaging can register the subcommand without depending on a source checkout.

The grant record is stored under the task store's `mcp-grants` directory, outside the runner workspace. The plaintext token is returned once for subprocess environment injection. The persisted record stores only a SHA-256 token hash plus the task id, session id, session context revision, snapshot ceiling, optional finance context ids, and revocation flag. Client config files are created with exclusive creation and mode `0600`; an existing file or symlink target is refused instead of replaced.

## Security Boundary

Every request re-reads the grant file and refuses the request when the grant is revoked, the token hash does not match, the session is no longer registered on the task, the session context revision changed, the snapshot ceiling exceeds the session context, or the requested finance context/run/draft is outside the bound grant.

Context-bound grants may still call `list_finance_context`. The returned datasets remain limited by the snapshot ceiling, and returned contexts, scenarios, and metric definitions are limited to `context_ids` in the grant. Account maps are returned only when referenced by one of those granted contexts, so another finance context that happens to use the same dataset snapshot does not leak metadata through the list response.

The adapter exposes only these tools:

- `list_finance_context`
- `run_metric`
- `explain_variance`
- `save_scenario`
- `run_scenario`
- `drilldown_fact`
- `save_explanation_draft`

`save_scenario` accepts `{context_id, kind, inputs, label, parent_id?, changes?}` where `kind` is `receivables_aging`, `cash_13_weeks`, or `driver_model`. Child scenarios are authorized through the parent scenario's `context_id` and the service keeps the parent context and kind. `run_scenario` accepts `{scenario_id, question?}` and authorizes through the saved scenario's context.

All tools call the existing `FinanceStore` methods. Dataset snapshots are immutable analysis records already owned by the task. Source-system credentials stay outside the runner; the adapter reads only task-local snapshots and finance records. Grant/session/scope refusals return sanitized JSON-RPC `access denied` errors. Domain validation failures inside an authorized tool return MCP tool results with `isError: true`, so an external assistant can correct inputs without receiving local paths, source credentials, or stack traces.

## Validation Contract

The subprocess smoke test starts `python -m foundry.finance_mcp`, performs `initialize`, sends `notifications/initialized`, verifies `ping`, lists tools, and calls `run_metric` against two separate task/snapshot fixtures. The asserted MCP result matches the direct `FinanceStore.run_metric` result for the same profit number, unit, and evidence references.

Additional tests verify that context-bound `list_finance_context` does not expose other same-snapshot finance contexts, scenario save/run matches direct `FinanceStore` results, `notifications/initialized` does not take effect before `initialize`, unsupported protocol versions return the server-supported version, malformed `params` and non-object `arguments` are rejected, oversized JSON lines are bounded at roughly 1 MiB, and authorization denials remain sanitized.

The installed-client verifier is `tools/verify_finance_mcp_client.py`. It creates a synthetic G1 finance task, writes a protected grant/config through the same grant API, and invokes an installed external client with that config for this run only. For Codex CLI verification it accepts `--codex-path` so the installed ChatGPT/Codex app bundle binary can be used without upgrading the global CLI. It creates a temporary `CODEX_HOME`, copies only the protected auth file and minimal configured model/provider settings, writes a temporary MCP server config, runs Codex in ephemeral per-run approval mode, checks list/run/drilldown equivalence against direct `FinanceStore`, revokes the grant, and checks that the external client surfaces rejection. The evidence JSON redacts paths and never records the token.
