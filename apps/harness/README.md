# Imbi Harness

The agent runner pod of ADR 0022. One image, two containers, three users:

| Process | Container | User | Holds |
|---|---|---|---|
| `imbi-harness runner` | `runner` | `runner` | Runner credential, agent tokens, handles, model key |
| `imbi-harness executor` | `executor` | `executor` | Executor credential |
| Claude Code CLI and its tools | `runner` | `agent` | Nothing |
| `run_with_secret` commands | `executor` | `agent` | Only the secrets of that command |

Both processes start as uid 0 with only `CAP_SETUID` and `CAP_SETGID`, and
with `allowPrivilegeEscalation: false`. They drop with `setresuid(u, u, 0)`.
The saved uid 0 is used only to start `agent` processes, to signal them, and
to make `agent` files.

A runner process runs one chain. For its root task it:

1. opens an ADR 0020 session,
2. builds `/work/<chain>`: it clones each project repository and each pinned
   plugin marketplace in the executor, as `agent`, with the token on a file
   descriptor of git's credential helper (`git-credential-fd`),
3. gets the model key through a `model_inference` resolution, which the
   executor materializes and releases,
4. starts a loopback model proxy for the task (Anthropic or LiteLLM), which
   reports usage after each call and refuses calls when the budget is spent,
5. writes the task's `CLAUDE_CONFIG_DIR` (`settings.json`, `CLAUDE.md`),
6. runs the SDK and sends redacted task events (1 MiB parts for large turns
   and tool results), and stops at a cancel or a closed task,
7. sets the outcome.

At the end of the chain it kills every `agent` process in both containers,
removes the chain workspace as `agent`, finishes, and exits. Child tasks, the
tool policy, and pod deletion come in later slices.

## Isolation suite

`isolation/` holds the adversarial tests. They run in a kind cluster against
a test double of imbi-api (`isolation/fake_api.py`) that serves the runner
and executor routes, an Anthropic-compatible model, and a GitHub write route.
Only the `isolation` image target contains this directory; the `runtime`
target and the wheel do not.

```sh
apps/harness/isolation/run-kind.sh
```

The script builds the `isolation` image target, loads it into the cluster,
deploys the fake API and the test pod, runs the in-pod suite, and then runs the
lifecycle suite (`SIGTERM`, partition) from the host.
