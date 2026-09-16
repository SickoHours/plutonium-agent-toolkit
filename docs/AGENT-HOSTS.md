# Agent hosts: hand work to T3 Code

`pat agent …` turns a running [T3 Code](https://github.com/pingdotgg/t3code) server into a place
the toolkit can send work: create a thread in one of its projects, start the first turn with a
prompt, and read the thread's state back. The prompt is usually a playbook plus a target ("run
`docs/playbooks/compose-a-pack.md` on `examples/hello-pack`"); the agent inside the thread does
the work with `pat` itself. This is how a button in a GUI, a scheduled job or another agent hands a
modding task to a T3 Code thread without owning the conversation.

Nothing here touches the game. `agent dispatch`, `send` and `interrupt` write to the T3 Code
server; the rest read from it or from its settings on disk.

## Which T3 Code

| T3 Code build | Orchestration protocol | `pat agent` |
| --- | --- | --- |
| Hosts advertising protocol 1 (including previously qualified nightly builds) | 1 | HTTP reads and writes; existing native receipts apply |
| Hosts advertising protocol 2 (observed on `0.0.40` to `0.0.42`) | 2 | HTTP reads and WebSocket writes; every orchestration read carries `x-t3-orchestration-protocol: 2`, which 0.0.42 requires; authenticated `hosts` verified live on 0.0.42, dispatch qualification pending |

V2 project and thread ids are opaque strings, including long percent-encoded graph ids.
The client accepts up to 4096 UTF-8 bytes and URL-encodes ids when reading or linking threads.
Provider-instance ids are different: V2 requires a 1–64-character slug beginning with a
letter and containing only letters, digits, underscores or hyphens. Protocol 1 retains its
existing id validation.

The public descriptor selects the client; the release version alone does not identify the
protocol. Both versions retain the same CLI and user-configured bearer. V2 gates its WebSocket
at `/ws?orchestrationProtocol=2` and uses one `orchestration.launchThread` call to create the
thread and submit the initial prompt. Unknown protocol versions are refused before any write.
`drivable: true` means this client implements that protocol; it does not prove the bearer is
configured or that a provider has run successfully.

## Before the first command

1. T3 Code is running on this machine. It writes `T3CODE_HOME/userdata/server-runtime.json`
   (`~/.t3` by default) with its origin; `pat agent probe` reads that file, or takes
   `--origin http://127.0.0.1:3773` explicitly. The probe is public: no token.
2. A bearer token, issued by **your own** T3 Code CLI from the same data directory the server
   runs from:
   ```sh
   t3 auth session issue --token-only --ttl 30d --label pat
   pat configure --t3-bearer-token <the token>
   ```
   The AppImage and the desktop installs bundle the CLI as `t3`; if it is not on the path, run the
   bundled server with the same arguments (`… apps/server/dist/bin.mjs auth session issue …`).
   `pat` never mints, reads or stores a login; it holds only the token you pasted, and `doctor`
   prints it as `<set>`. Revoke it with `t3 auth session revoke <session-id>` when done.
3. A project in T3 Code whose workspace is the repository the agent should work in. `pat agent
   hosts` lists projects with their ids and workspace roots.

## Routes

| Command | What it does | Result to keep |
| --- | --- | --- |
| `pat agent probe [--origin …]` | Public descriptor: server version, environment id, orchestration protocol, `drivable`. | `server_version`, `orchestration_protocol` |
| `pat agent hosts` | Projects (id, title, workspace root) and thread shells with each thread's turn state. `GET /api/orchestration/shell` on either protocol. | `projects[].id` |
| `pat agent models [--home …]` | Provider instances, models and their option descriptors (the reasoning choices with labels and defaults) from this machine's T3 Code `settings.json` and `model-manifest.json`. | `instances[].instance_id`, `models[].slug`, `options[].choices[].id` |
| `pat agent dispatch --project <id> --title <t> --prompt <text or @file> --instance <id> --model <slug> [--option id=value]… [--runtime-mode …] [--interaction-mode …] [--worktree <abs>] [--branch <name>]` | V1: `thread.create` then `thread.turn.start` on HTTP dispatch. V2: one WebSocket `orchestration.launchThread` with the chosen model, workspace and initial message. | `thread_id`, `thread_url`, `commands[]` (V1 sequences; V2 launch confirmation) |
| `pat agent status <thread-id> [--messages N]` | The thread with `latestTurn.state` (`running`, `interrupted`, `completed`, `error`), session status, pending approvals or questions, and the last messages. | `turn_state`, `pending_approvals`, `recent_messages` |
| `pat agent send <thread-id> --prompt … [--queue]` | A follow-up `thread.turn.start` (V1) or `message.dispatch` (V2). Refuses with `busy` while the latest turn is running unless `--queue`. | `message_id`, `queued_behind_running_turn` |
| `pat agent interrupt <thread-id>` | `thread.turn.interrupt` (V1) or `run.interrupt` (V2) once; the thread stays open. V2 requires an active run. | `turn_state_before` |

Every model and reasoning choice is the caller's. `dispatch` has no default model; `--instance`
and `--model` are required and `--option` carries the reasoning level under the id the model's
descriptor names (`effort` for the Claude driver, `reasoningEffort` for Codex). Read them from
`pat agent models` for the machine at hand; do not carry a slug from one machine to another.

`--runtime-mode` defaults to `full-access` because a dispatched thread has nobody at the keyboard
to approve edits; pass `approval-required` when a person will watch the thread. `--worktree` must
be an absolute path the server can see; the thread records it and the provider starts there.

## Reading results

- V1 `commands[].sequence` proves command acceptance. V2 launch returns a matching thread
  projection and `resumed: false`, recorded in `commands[]` without inventing a sequence.
  V2 send and interrupt return a command sequence. None proves provider completion: read `status`.
- V2 reports `run_state`, `run_id`, `active_run_id` and `latest_run_id`. Compatibility field
  `turn_id` is an app run id. `turn_state: running` includes preparing, starting, waiting and queued;
  failed maps to error, and cancelled or rolled-back maps to interrupted. An active run takes
  precedence over a newer queued run. Interrupt targets the active run, never the queued one.
- V2 status reads canonical app messages and the current provider's session, preserving continuity
  after a provider switch. Send does not override the thread's current model or runtime settings.
  `--messages 0` returns no message bodies on either protocol.
- A `completed` turn means the provider returned. Whether the task is done is in the messages and
  in the receipts the agent wrote into its own `--output` directories; read those, not the turn.
- `pending_approvals` or `pending_user_input` true means the thread is waiting for a person in the
  T3 Code UI (`thread_url`). `pat` does not answer approvals or questions.
- `error_code: busy` from `send`: nothing was sent. The busy check is a snapshot; another client
  can start a run before the write reaches the server. V2 serializes delivery and may queue that race.
  `--queue` explicitly requests `queue_after_active`; otherwise the command asks to start immediately.
- V2 writes use bounded Effect JSON RPC Request/Exit frames with a matching request id.
  The bearer is only an upgrade header; proxies, redirects and WebSocket credential logging are
  disabled. A lost, timed-out or malformed reply after sending is `delivery_uncertain`, with
  thread/command/message or run ids for inspection. No write is retried automatically.
  Read `status` before repeating a write, including a V1 `backend_timeout`.
- V2 typed command rejection becomes `input_invalid`, missing RPC scope becomes `config_invalid`,
  and unclassified server defects remain uncertain. Server error bodies and transport exception
  text are omitted to protect the bearer.
- HTTP 401 becomes `config_invalid` (issue a new token); 403 becomes `config_invalid` with the
  missing scope; 400 becomes `input_invalid` with the server's error code (the reason text is not printed).
  A rejection may mean the command shape differs from the server's contract: compare `serverVersion`
  from `probe` with the version in the receipt linked from `docs/SUPPORT.md`.

## Qualifying on a host

```sh
PAT_HOME=<the toolkit home holding your token> python tools/qualify.py --tier agent --output docs/receipts \
    --project <id from pat agent hosts> --instance <id from pat agent models> --model <slug> --option effort=low
```

The tier probes, lists hosts and models, dispatches one proof thread whose prompt asks for a
one-word reply, waits for the turn to complete, sends a second turn, shows the busy refusal,
interrupts, and writes `docs/receipts/<version>/<platform>-tier4-agent.json` with every UUID and
path redacted. The thread stays on your server, titled so you can archive it. The token is never
written to the receipt.

## What is not here

- No live event stream: the V2 WebSocket opens for one write and closes; `status` is a snapshot.
- No approvals, no question answers, no attachments, no thread deletion or archiving.
- No provider list over the network: `models` reads this machine's T3 Code files, so a remote
  host's models are not visible on protocol 1.
- No automatic token issuance, provider selection, or authenticated V2 native qualification yet.

## Opt-in smoke test

The normal suite skips the live test. To probe and launch one trivial thread on a configured host:

```sh
PAT_AGENT_LIVE=1 PAT_AGENT_ORIGIN=http://127.0.0.1:3773 \
PAT_AGENT_PROJECT=<project-id> PAT_AGENT_INSTANCE=<instance-id> PAT_AGENT_MODEL=<model-slug> \
uv run python -m unittest discover -s tests -p test_agent_live.py -v
```

The bearer comes only from the existing toolkit configuration. Without it the test skips, even
when opted in; it never reads another credential source. `PAT_AGENT_OPTIONS` may contain a JSON
list such as `["reasoningEffort=low"]`. The thread remains titled `pat opt-in protocol smoke check`.
The test confirms launch and readback only, not turn completion or task acceptance. The full
agent qualification tier above is still required for native lifecycle evidence.

The wire adapter follows T3's `packages/contracts/src/orchestrationV2.ts` and
`environmentHttp.ts`. Its Effect envelope is the
[Request/Exit contract](https://unpkg.com/effect@4.0.0-rc.112/src/unstable/rpc/RpcMessage.ts),
using [JSON serialization](https://unpkg.com/effect@4.0.0-rc.112/src/unstable/rpc/RpcSerialization.ts).
