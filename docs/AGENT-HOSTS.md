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
| Nightly and stable releases through `0.0.41` | 1 | drives it: HTTP dispatch |
| The Orchestrator V2 branch (upstream pull request "introduce new orchestrator") | 2 | reports it in `probe` and refuses every other route with `not_implemented` |

The two protocols share authentication, the model-selection shape, thread ids and the thread
route in the web UI. V2 removes the HTTP dispatch endpoint and gates its WebSocket on
`?orchestrationProtocol=2` with a one-call `launchThread`. When V2 reaches the release channel,
`agent probe` will show protocol 2 and the V2 client is one more module behind the same routes;
until then the routes refuse rather than guess.

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
| `pat agent hosts` | Projects (id, title, workspace root) and thread shells with each thread's turn state. `GET /api/orchestration/shell`. | `projects[].id` |
| `pat agent models [--home …]` | Provider instances, models and their option descriptors (the reasoning choices with labels and defaults) from this machine's T3 Code `settings.json` and `model-manifest.json`. | `instances[].instance_id`, `models[].slug`, `options[].choices[].id` |
| `pat agent dispatch --project <id> --title <t> --prompt <text or @file> --instance <id> --model <slug> [--option id=value]… [--runtime-mode …] [--interaction-mode …] [--worktree <abs>] [--branch <name>]` | Two commands on `POST /api/orchestration/dispatch`: `thread.create` with the chosen model selection, then `thread.turn.start` with the prompt. | `thread_id`, `thread_url`, `commands[].sequence` |
| `pat agent status <thread-id> [--messages N]` | The thread with `latestTurn.state` (`running`, `interrupted`, `completed`, `error`), session status, pending approvals or questions, and the last messages. | `turn_state`, `pending_approvals`, `recent_messages` |
| `pat agent send <thread-id> --prompt … [--queue]` | A follow-up `thread.turn.start`. Refuses with `busy` while the latest turn is running unless `--queue`. | `message_id`, `queued_behind_running_turn` |
| `pat agent interrupt <thread-id>` | `thread.turn.interrupt` once; the thread stays open. | `turn_state_before` |

Every model and reasoning choice is the caller's. `dispatch` has no default model; `--instance`
and `--model` are required and `--option` carries the reasoning level under the id the model's
descriptor names (`effort` for the Claude driver, `reasoningEffort` for Codex). Read them from
`pat agent models` for the machine at hand; do not carry a slug from one machine to another.

`--runtime-mode` defaults to `full-access` because a dispatched thread has nobody at the keyboard
to approve edits; pass `approval-required` when a person will watch the thread. `--worktree` must
be an absolute path the server can see; the thread records it and the provider starts there.

## Reading results

- `commands[].sequence` proves the server accepted each command. It does not prove the provider
  started: read `status` and look for `turn_state: running`, then `completed`.
- A `completed` turn means the provider returned. Whether the task is done is in the messages and
  in the receipts the agent wrote into its own `--output` directories; read those, not the turn.
- `pending_approvals` or `pending_user_input` true means the thread is waiting for a person in the
  T3 Code UI (`thread_url`). `pat` does not answer approvals or questions.
- `error_code: busy` from `send`: nothing was sent. `backend_timeout` from a write: the server may
  have applied it; read `status` before repeating anything.
- HTTP 401 becomes `config_invalid` (issue a new token); 403 becomes `config_invalid` with the
  missing scope; 400 becomes `input_invalid` with the server's reason, which usually means the
  command shape is bound to a server version this release did not see: compare `serverVersion`
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

- No WebSocket client, no live event stream: `status` is a snapshot, poll it or open the UI.
- No approvals, no question answers, no attachments, no thread deletion or archiving.
- No provider list over the network: `models` reads this machine's T3 Code files, so a remote
  host's models are not visible on protocol 1.
- Orchestrator V2 hosts, as above.
