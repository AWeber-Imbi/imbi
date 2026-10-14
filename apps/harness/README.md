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

This is the P5a isolation slice of the harness plan: the pod layout, the
executor socket, `run_with_secret`, and the SDK start through the `setpriv`
wrapper. It has no task logic.

A runner process runs one chain. At the end of the chain it kills every
`agent` process in both containers, removes the chain workspace as `agent`,
finishes, and exits. P5 then deletes the pod.

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
