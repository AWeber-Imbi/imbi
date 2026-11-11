# GitHub App Runbook

This runbook gives one agent access to GitHub, from the start to the end:
GitHub, AWS, and Imbi. After the setup, the agent's runner can clone the
project repository, and the agent can push and open pull requests and
issues. The commits and pull requests show as `<agent>[bot]`.

Imbi stores no GitHub token. For each request, imbi-api reads the App
private key from AWS Secrets Manager and gets a new installation token
from GitHub. The token covers one repository and one purpose, and lasts
one hour at most.

This page gives the order and the values for each side. The Imbi screens
have their own pages, linked from each step.

The examples use the agent `reviewer`, the App ID `1234`, and the GitHub
host `example.ghe.com`. Use your own values.

<style>
.ghr { --g-ink: var(--md-default-fg-color); --g-muted: var(--md-default-fg-color--light); --g-line: var(--md-default-fg-color--lighter); --g-bg: var(--md-default-bg-color); --g-gh: #3f5f8f; --g-aws: #9a5a0c; --g-imbi: #17766a; --g-accent: #c2410c; --g-gh-tint: #edf1f8; --g-aws-tint: #f9f1e6; --g-imbi-tint: #e8f4f1; --g-mono: var(--md-code-font-family, monospace); --g-sans: var(--md-text-font-family, sans-serif); }
[data-md-color-scheme="slate"] .ghr { --g-gh: #8eaee0; --g-aws: #f0a94e; --g-imbi: #5cc7b6; --g-accent: #ff8a4c; --g-gh-tint: #222b3b; --g-aws-tint: #2d251b; --g-imbi-tint: #1b2e2b; }
.md-typeset figure.ghr { display: block; width: 100%; max-width: 100%; }
.ghr svg { display: block; width: 100%; height: auto; }
.ghr .band { stroke: none; } .ghr .band.gh { fill: var(--g-gh-tint); } .ghr .band.aws { fill: var(--g-aws-tint); } .ghr .band.imbi { fill: var(--g-imbi-tint); }
.ghr .lane { font: 700 12px var(--g-sans); letter-spacing: .08em; text-transform: uppercase; }
.ghr .lane.gh { fill: var(--g-gh); } .ghr .lane.aws { fill: var(--g-aws); } .ghr .lane.imbi { fill: var(--g-imbi); }
.ghr .node rect.box { fill: var(--g-bg); stroke-width: 1.5; }
.ghr .node.gh rect.box { stroke: var(--g-gh); } .ghr .node.aws rect.box { stroke: var(--g-aws); } .ghr .node.imbi rect.box { stroke: var(--g-imbi); }
.ghr .node.once rect.box { stroke-dasharray: 5 4; }
.ghr .node .t { font: 700 13px var(--g-sans); fill: var(--g-ink); }
.ghr .node .s { font: 400 11px var(--g-mono); fill: var(--g-muted); }
.ghr .node .k { font: 500 11px var(--g-mono); fill: var(--g-accent); }
.ghr .node .n { font: 700 11px var(--g-sans); fill: var(--g-bg); }
.ghr .node.gh .badge { fill: var(--g-gh); } .ghr .node.aws .badge { fill: var(--g-aws); } .ghr .node.imbi .badge { fill: var(--g-imbi); }
.ghr .mk { fill: var(--g-muted); } .ghr .mk-ink { fill: var(--g-ink); }
.ghr .edge path { fill: none; stroke: var(--g-muted); stroke-width: 1.4; marker-end: url(#ghr-arr); }
.ghr .edge.ref path { stroke-dasharray: 4 4; }
.ghr .edge text { font: 400 11px var(--g-mono); fill: var(--g-muted); }
.ghr .podbox { fill: none; stroke: var(--g-muted); stroke-dasharray: 4 4; }
.ghr .podlbl { font: 400 10.5px var(--g-mono); fill: var(--g-muted); }
.ghr .life { stroke: var(--g-line); stroke-width: 1.2; stroke-dasharray: 3 4; }
.ghr .hdr { font: 700 12.5px var(--g-sans); fill: var(--g-ink); }
.ghr .hdr.imbi { fill: var(--g-imbi); } .ghr .hdr.aws { fill: var(--g-aws); } .ghr .hdr.gh { fill: var(--g-gh); }
.ghr .needs-h { font: 700 11px var(--g-sans); fill: var(--g-muted); letter-spacing: .08em; text-transform: uppercase; }
.ghr .phase { fill: var(--g-imbi-tint); } .ghr .phase-t { font: 700 12px var(--g-sans); fill: var(--g-ink); }
.ghr .msg path { fill: none; stroke: var(--g-ink); stroke-width: 1.3; marker-end: url(#ghr-sarr); }
.ghr .ret path { fill: none; stroke: var(--g-muted); stroke-width: 1.2; stroke-dasharray: 5 4; marker-end: url(#ghr-sret); }
.ghr .msg text { font: 400 11px var(--g-mono); fill: var(--g-ink); } .ghr .ret text { font: 400 11px var(--g-mono); fill: var(--g-muted); }
.ghr .self rect { fill: var(--g-bg); stroke: var(--g-imbi); stroke-width: 1.2; }
.ghr .self text { font: 400 11px var(--g-mono); fill: var(--g-ink); }
.ghr .note rect { stroke: var(--g-muted); stroke-dasharray: 4 3; }
.ghr .need rect { fill: var(--g-bg); stroke: var(--g-accent); stroke-width: 1.2; }
.ghr .need text { font: 700 10.5px var(--g-sans); fill: var(--g-accent); }
</style>

## How the parts connect

<figure class="ghr"><svg class="ghr-map" viewBox="0 0 760 746" role="img" aria-label="Setup map. In GitHub: the App, its private key, and one installation per organization. In AWS: the key stored as a secret that the IAM role can read. In Imbi: the key binding names the AWS secret, the App binding names the key binding, two grants name the App binding and the agent, and the agent selects the App binding."><defs><marker id="ghr-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="mk" d="M0,0 L10,5 L0,10 z"></path></marker></defs><rect class="band gh" x="6" y="8" width="748" height="150" rx="8"></rect><text class="lane gh" x="24" y="30">GitHub</text><rect class="band aws" x="6" y="168" width="748" height="110" rx="8"></rect><text class="lane aws" x="24" y="190">AWS</text><rect class="band imbi" x="6" y="288" width="748" height="450" rx="8"></rect><text class="lane imbi" x="24" y="310">Imbi</text><g class="node gh"><rect class="box" x="30" y="48" width="180" height="92" rx="7"></rect><circle class="badge" cx="30" cy="48" r="10"></circle><text class="n" x="30" y="52" text-anchor="middle">3</text><text class="t" x="46" y="72">Installations</text><text class="s" x="46" y="90">org-a, org-b, org-c</text><text class="s" x="46" y="106">one per organization</text></g><g class="node gh"><rect class="box" x="280" y="48" width="180" height="64" rx="7"></rect><circle class="badge" cx="280" cy="48" r="10"></circle><text class="n" x="280" y="52" text-anchor="middle">1</text><text class="t" x="296" y="72">GitHub App</text><text class="k" x="296" y="90">App ID 1234</text></g><g class="node gh"><rect class="box" x="550" y="48" width="180" height="56" rx="7"></rect><circle class="badge" cx="550" cy="48" r="10"></circle><text class="n" x="550" y="52" text-anchor="middle">2</text><text class="t" x="566" y="72">Private key</text><text class="s" x="566" y="90">.pem file</text></g><g class="node aws once"><rect class="box" x="280" y="200" width="180" height="56" rx="7"></rect><text class="t" x="296" y="224">IAM role</text><text class="s" x="296" y="242">reads imbi/*</text></g><g class="node aws"><rect class="box" x="550" y="200" width="180" height="56" rx="7"></rect><circle class="badge" cx="550" cy="200" r="10"></circle><text class="n" x="550" y="204" text-anchor="middle">4</text><text class="t" x="566" y="224">Secret</text><text class="s" x="566" y="242">imbi/github/reviewer</text></g><g class="node imbi once"><rect class="box" x="30" y="330" width="180" height="56" rx="7"></rect><text class="t" x="46" y="354">GitHub provider</text><text class="s" x="46" y="372">github_app</text></g><g class="node imbi once"><rect class="box" x="280" y="330" width="180" height="56" rx="7"></rect><text class="t" x="296" y="354">AWS provider</text><text class="s" x="296" y="372">aws_secrets_manager</text></g><g class="node imbi"><rect class="box" x="280" y="440" width="180" height="72" rx="7"></rect><circle class="badge" cx="280" cy="440" r="10"></circle><text class="n" x="280" y="444" text-anchor="middle">6</text><text class="t" x="296" y="464">App binding</text><text class="s" x="296" y="482">ghe/reviewer</text><text class="k" x="296" y="498">app_id 1234</text></g><g class="node imbi"><rect class="box" x="550" y="440" width="196" height="72" rx="7"></rect><circle class="badge" cx="550" cy="440" r="10"></circle><text class="n" x="550" y="444" text-anchor="middle">5</text><text class="t" x="566" y="464">Key binding</text><text class="s" x="566" y="482">ghe/reviewer_private_key</text><text class="k" x="566" y="498">provider key, 1234</text></g><g class="node imbi"><rect class="box" x="30" y="560" width="180" height="72" rx="7"></rect><circle class="badge" cx="30" cy="560" r="10"></circle><text class="n" x="30" y="564" text-anchor="middle">7</text><text class="t" x="46" y="584">Grant: runner</text><text class="s" x="46" y="602">workspace_checkout,</text><text class="s" x="46" y="618">marketplace_fetch</text></g><g class="node imbi"><rect class="box" x="280" y="560" width="180" height="72" rx="7"></rect><circle class="badge" cx="280" cy="560" r="10"></circle><text class="n" x="280" y="564" text-anchor="middle">8</text><text class="t" x="296" y="584">Grant: write</text><text class="s" x="296" y="602">github_write</text></g><g class="node imbi"><rect class="box" x="280" y="664" width="180" height="56" rx="7"></rect><circle class="badge" cx="280" cy="664" r="10"></circle><text class="n" x="280" y="668" text-anchor="middle">9</text><text class="t" x="296" y="688">Agent reviewer</text><text class="s" x="296" y="706">GitHub App setting</text></g><g class="edge"><path d="M280,80 H212"></path><text x="246" y="72" text-anchor="middle">install</text></g><g class="edge"><path d="M460,76 H548"></path><text x="504" y="68" text-anchor="middle">generate</text></g><g class="edge"><path d="M640,104 V198"></path><text x="648" y="156" text-anchor="start">store</text></g><g class="edge"><path d="M460,228 H548"></path><text x="504" y="220" text-anchor="middle">can read</text></g><g class="edge"><path d="M370,330 V258"></path><text x="378" y="300" text-anchor="start">assumes</text></g><g class="edge"><path d="M640,440 V258"></path><text x="648" y="356" text-anchor="start">Secret ID</text></g><g class="edge"><path d="M460,372 L575,438"></path><text x="522" y="394" text-anchor="start">provider</text></g><g class="edge"><path d="M210,386 L300,438"></path><text x="232" y="426" text-anchor="start">provider</text></g><g class="edge"><path d="M550,466 H462"></path><text x="506" y="458" text-anchor="middle">private_key</text></g><g class="edge"><path d="M460,494 H548"></path><text x="506" y="510" text-anchor="middle">consumers</text></g><g class="edge"><path d="M370,560 V514"></path><text x="378" y="542" text-anchor="start">binding</text></g><g class="edge"><path d="M180,560 L290,514"></path><text x="214" y="530" text-anchor="end">binding</text></g><g class="edge"><path d="M125,632 L285,676"></path><text x="178" y="668" text-anchor="end">agent</text></g><g class="edge"><path d="M370,632 V662"></path><text x="378" y="652" text-anchor="start">agent</text></g><g class="edge ref"><path d="M460,692 H530 V530 H445 V515"></path><text x="538" y="610" text-anchor="middle" transform="rotate(-90 538 610)">GitHub App</text></g></svg><figcaption>An arrow points from the part that holds a reference to the part that it names. A number is the step that makes the part. A dashed box is made one time for each Imbi organization.</figcaption></figure>

| Part | Where | What it holds |
|---|---|---|
| GitHub App | GitHub | The App ID and the permissions. The permissions are the upper limit of each token |
| Private key | GitHub, then AWS | The `.pem` file. imbi-api signs a JWT with it |
| Installation | GitHub | One for each GitHub organization. A token can only cover repositories of one installation |
| Secret | AWS Secrets Manager | The `.pem` text |
| Key binding | Imbi | A reference for the AWS secret, marked as a provider key. Only imbi-api reads it. No grant can give it to an agent |
| App binding | Imbi | The App ID and the reference of the key binding. It gets the tokens |
| Grants | Imbi | Which agents may use the App binding, for which purposes |
| Agent setting | Imbi | Which App binding the runner asks for |

The agent setting and the grants do different things. The setting tells
the runner which binding to ask for. The grant decides if imbi-api allows
the request. The agent needs both.

## How a token is made

The runner asks for a token when a task starts, to clone the repository.
The agent asks for a second token when it pushes or opens a pull request.
The **Step** column gives the setup step that each message needs.

<figure class="ghr"><svg class="ghr-seq" viewBox="0 0 760 836" role="img" aria-label="A task run. The runner claims the task and gets the App binding. It asks imbi-api to resolve the binding for workspace_checkout. imbi-api requires exactly one matching grant and returns a handle. The executor materializes the handle. imbi-api reads the key from AWS, finds the installation, and gets a token for the one repository. The executor clones and releases, and imbi-api revokes the token. Later the agent calls run_with_secret for github_write, and the same steps make a write token for one command."><defs><marker id="ghr-sarr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="mk-ink" d="M0,0 L10,5 L0,10 z"></path></marker><marker id="ghr-sret" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="mk" d="M0,0 L10,5 L0,10 z"></path></marker></defs><rect class="podbox" x="8" y="8" width="296" height="52" rx="8"></rect><text class="podlbl" x="18" y="22">runner pod</text><line class="life" x1="50" y1="58" x2="50" y2="828"></line><text class="hdr " x="50" y="48" text-anchor="middle">Agent</text><line class="life" x1="150" y1="58" x2="150" y2="828"></line><text class="hdr " x="150" y="48" text-anchor="middle">Runner</text><line class="life" x1="255" y1="58" x2="255" y2="828"></line><text class="hdr " x="255" y="48" text-anchor="middle">Executor</text><line class="life" x1="395" y1="58" x2="395" y2="828"></line><text class="hdr imbi" x="395" y="48" text-anchor="middle">imbi-api</text><line class="life" x1="530" y1="58" x2="530" y2="828"></line><text class="hdr aws" x="530" y="48" text-anchor="middle">AWS</text><line class="life" x1="640" y1="58" x2="640" y2="828"></line><text class="hdr gh" x="640" y="48" text-anchor="middle">GitHub</text><text class="needs-h" x="718" y="48" text-anchor="middle">Step</text><rect class="phase" x="8" y="75" width="744" height="23" rx="4"></rect><text class="phase-t" x="18" y="91">Task starts: clone the repository</text><g class="msg"><path d="M153,120 H392"></path><text x="272.5" y="115" text-anchor="middle">claim the task</text></g><g class="ret"><path d="M392,148 H153"></path><text x="272.5" y="143" text-anchor="middle">repository + App binding</text></g><g class="need"><rect x="684" y="133" width="68" height="19" rx="9.5"></rect><text x="718" y="147" text-anchor="middle">9</text></g><g class="msg"><path d="M153,176 H392"></path><text x="272.5" y="171" text-anchor="middle">resolve: workspace_checkout</text></g><g class="self"><rect x="274.0" y="189" width="242.0" height="21" rx="4"></rect><text x="395.0" y="204" text-anchor="middle">requires exactly one matching grant</text></g><g class="need"><rect x="684" y="189" width="68" height="19" rx="9.5"></rect><text x="718" y="203" text-anchor="middle">7</text></g><g class="ret"><path d="M392,232 H153"></path><text x="272.5" y="227" text-anchor="middle">handle</text></g><g class="msg"><path d="M153,260 H252"></path><text x="202.5" y="255" text-anchor="middle">handle</text></g><g class="msg"><path d="M258,288 H392"></path><text x="325.0" y="283" text-anchor="middle">materialize</text></g><g class="msg"><path d="M398,316 H527"></path><text x="462.5" y="311" text-anchor="middle">read the key</text></g><g class="need"><rect x="684" y="301" width="68" height="19" rx="9.5"></rect><text x="718" y="315" text-anchor="middle">4, 5</text></g><g class="ret"><path d="M527,344 H398"></path><text x="462.5" y="339" text-anchor="middle">.pem</text></g><g class="self"><rect x="283.6" y="357" width="222.8" height="21" rx="4"></rect><text x="395.0" y="372" text-anchor="middle">looks up the verified repository</text></g><g class="need"><rect x="684" y="357" width="68" height="19" rx="9.5"></rect><text x="718" y="371" text-anchor="middle">Doctor</text></g><g class="msg"><path d="M398,400 H637"></path><text x="517.5" y="395" text-anchor="middle">JWT: find the installation</text></g><g class="need"><rect x="684" y="385" width="68" height="19" rx="9.5"></rect><text x="718" y="399" text-anchor="middle">1, 2, 3</text></g><g class="msg"><path d="M398,428 H637"></path><text x="517.5" y="423" text-anchor="middle">token: one repo, contents read</text></g><g class="need"><rect x="684" y="413" width="68" height="19" rx="9.5"></rect><text x="718" y="427" text-anchor="middle">6</text></g><g class="ret"><path d="M637,456 H398"></path><text x="517.5" y="451" text-anchor="middle">token, one hour at most</text></g><g class="ret"><path d="M392,484 H258"></path><text x="325.0" y="479" text-anchor="middle">token</text></g><g class="msg"><path d="M258,512 H637"></path><text x="447.5" y="507" text-anchor="middle">git clone, token on a file descriptor</text></g><g class="msg"><path d="M258,540 H392"></path><text x="325.0" y="535" text-anchor="middle">release</text></g><g class="msg"><path d="M398,568 H637"></path><text x="517.5" y="563" text-anchor="middle">revoke the token</text></g><rect class="phase" x="8" y="579" width="744" height="23" rx="4"></rect><text class="phase-t" x="18" y="595">The agent opens a pull request</text><g class="msg"><path d="M53,624 H147"></path><text x="100.0" y="619" text-anchor="middle">run_with_secret</text></g><g class="self"><rect x="10" y="637" width="184.4" height="21" rx="4"></rect><text x="102.2" y="652" text-anchor="middle">gh pr create, github_write</text></g><g class="msg"><path d="M153,680 H392"></path><text x="272.5" y="675" text-anchor="middle">resolve: github_write</text></g><g class="need"><rect x="684" y="665" width="68" height="19" rx="9.5"></rect><text x="718" y="679" text-anchor="middle">8</text></g><g class="self note"><rect x="130" y="692" width="530" height="23" rx="4"></rect><text x="395.0" y="708" text-anchor="middle">The same steps. The token gets contents, pull_requests, issues: write.</text></g><g class="msg"><path d="M258,736 H637"></path><text x="447.5" y="731" text-anchor="middle">gh pr create, GH_TOKEN in one command</text></g><g class="ret"><path d="M252,764 H53"></path><text x="152.5" y="759" text-anchor="middle">output, token removed</text></g><g class="msg"><path d="M258,792 H392"></path><text x="325.0" y="787" text-anchor="middle">release and revoke</text></g></svg><figcaption>Solid arrows are requests. Dashed arrows are replies.</figcaption></figure>

- imbi-api does all of the GitHub authentication. The private key goes
  from AWS to imbi-api and no further. The runner pod gets only
  short-lived tokens.
- The token for `github_write` is in the environment of one command only,
  and Imbi removes it from the command output.
- The token covers only the repository that the GitHub integration
  verified for the project. If the project's `EXISTS_IN` edge was made or
  edited by hand, the Doctor check
  [`identifier-verified`](../plugins/github.md#identifier-verified) fails
  and Imbi refuses the token.

## Before you start

These parts are made one time for each Imbi organization, not for each
agent. Check that they exist:

| Part | Where | See |
|---|---|---|
| IAM role that imbi-api assumes, with the ExternalId `imbi:<organization id>` and read access to the secret prefix | AWS | [Secrets, Prepare AWS](secrets.md#prepare-aws) |
| An AWS Secrets Manager provider | **Admin, Secrets, Providers** | [Secrets, Add a provider](secrets.md#add-a-provider) |
| A `github_app` provider with the GitHub host | **Admin, Secrets, Providers** | [Agent Runners, Configure GitHub access](../deployment/agent-runners.md#6-configure-github-access) |

Click **Test** on each provider row to check it.

The `github_app` provider accepts `github.com`, a `<tenant>.ghe.com`
host, or a GHES host that the operator lists in
`IMBI_SECRETS_GITHUB_GHES_HOSTS`.

## Step 1: Create the GitHub App

In the GitHub organization that owns the App, open **Settings, Developer
settings, GitHub Apps, New GitHub App**.

| Field | Value |
|---|---|
| GitHub App name | The agent name, for example `reviewer`. Commits show as `reviewer[bot]` |
| Homepage URL | Any URL, for example the Imbi page of the agent |
| Webhook | Clear **Active**. Imbi needs no events from this App |
| Repository permissions: Contents | Read and write |
| Repository permissions: Pull requests | Read and write |
| Repository permissions: Issues | Read and write |
| Repository permissions: Metadata | Read-only (GitHub adds it) |
| Where can this GitHub App be installed? | **Any account**. A private App can only be installed in the organization that owns it |

Click **Create GitHub App**. Copy the **App ID** from the App settings
page.

Each token asks only for the permissions of its purpose. GitHub refuses a
token with more permissions than the App has.

| Purpose | Token permissions |
|---|---|
| `workspace_checkout` | `contents: read` |
| `marketplace_fetch` | `contents: read` |
| `github_write` | `contents: write`, `pull_requests: write`, `issues: write` |

## Step 2: Generate the private key

On the App settings page, under **Private keys**, click **Generate a
private key**. The browser downloads a `.pem` file. Keep it only until
step 4.

## Step 3: Install the App

On the App settings page, click **Install App**. Select a GitHub
organization, then **All repositories** or the repositories that the agent
works in. Click **Install**. If the organization requires approval, an
organization owner approves the install.

Do this for each GitHub organization that the agent works in.

You do not need the installation ID. Imbi finds the installation of each
repository. The repositories of one token must all be in one
installation.

To check, open the organization's **Settings, GitHub Apps**. The App is
in the list.

## Step 4: Store the key in AWS

In AWS Secrets Manager, click **Store a new secret**:

| Field | Value |
|---|---|
| Secret type | **Other type of secret**, **Plaintext** |
| Value | The full `.pem` text, with the `BEGIN` and `END` lines |
| Secret name | For example `imbi/github/reviewer`. Use a name that the IAM role can read |
| Encryption key | The default key, or a KMS key that the role can decrypt |

Then delete the local `.pem` file.

## Step 5: Add the key binding

Open **Admin, Secrets, Bindings** and click **New binding** (see
[Secrets, Add a binding](secrets.md#add-a-binding)).

| Field | Value |
|---|---|
| Reference | `ghe/reviewer_private_key`. Use lower case letters, digits, and `_` |
| Provider | The AWS Secrets Manager provider |
| Credential class | `static` |
| Secret ID | `imbi/github/reviewer` |
| Allowed fields | Empty |
| Provider key host | `example.ghe.com` |
| Provider key App id | `1234` |

Leave **Consumers** empty. The App binding does not exist yet. Do not add
a grant for this binding.

Click **Validate** on the row to check that Imbi can read the AWS secret.

## Step 6: Add the App binding

Click **New binding** again.

| Field | Value |
|---|---|
| Reference | `ghe/reviewer` |
| Provider | The `github_app` provider |
| Credential class | `dynamic` |
| App ID | `1234` |
| Installation ID | Empty, so that one binding works in each GitHub organization |
| Private key | `secret://ghe/reviewer_private_key` |
| Repositories | Empty. Only `marketplace_fetch` uses this list. See [Agents, Plugin marketplaces](agents.md#plugin-marketplaces) |
| Allowed delivery modes | `file_descriptor` and `environment` |
| Description | What the token is for. The agent sees this text |

Then edit the key binding `ghe/reviewer_private_key`. Under
**Consumers**, select `ghe/reviewer` and save.

The order matters. The App binding must name an existing key binding, and
the **Consumers** list shows only existing App bindings.

Click **Validate** on the App binding row.

## Step 7: Grant the runner purposes

The runner uses these tokens to clone the project repository and to fetch
plugins. The agent never sees them. The agent must exist before a grant
can name it, so save the agent first.

Open **Admin, Secrets, Grants** and click **New grant**.

| Field | Value |
|---|---|
| Agents | `reviewer` |
| Bindings | `ghe/reviewer` |
| Purposes | `workspace_checkout`, `marketplace_fetch` |
| Delivery modes | `file_descriptor` only |
| Projects | All, or the selected projects |

## Step 8: Grant the write purpose

The agent uses this token to push and to open pull requests and issues
with `run_with_secret`.

| Field | Value |
|---|---|
| Agents | `reviewer` |
| Bindings | `ghe/reviewer` |
| Purposes | `github_write` |
| Delivery modes | `environment` only |
| Projects | All, or the selected projects |

Keep the grants of steps 7 and 8 separate. A grant allows each of its
purposes with each of its delivery modes, and exactly one grant must
allow each request. With no match, Imbi refuses the request with
`no_grant`. With two matches, it refuses with `ambiguous_grants`.

## Step 9: Select the App binding on the agent

Open **Agents**, the agent, **Edit**, then the **Access** tab. Select
`ghe/reviewer` as the **GitHub App** and save. See
[Agents, Access](agents.md#access).

The tab shows a row for `workspace_checkout`, `github_write`, and
`marketplace_fetch`. Each row shows a check when a grant allows it.

You can also do this step right after step 6. Then click **Grant** on
each row that has no check. Imbi adds the purpose to the agent's grant
that has the same binding and delivery mode, or makes a new grant. The
result is the grants of steps 7 and 8.

## Check

Run a task on a project whose GitHub repository the agent can reach.
Open **Admin, Secrets, Resolutions** to see the token reads, and
**Audit** to see a refused request and its reason.

| Reason | Fix |
|---|---|
| `installation_not_found` | Install the App in the GitHub organization of the repository (step 3) |
| `permission_or_repository_not_granted` | Give the App the permission (step 1), or add the repository to the installation (step 3) |
| `no_grant` | Check the grant's agents, binding, purposes, delivery modes, and projects (steps 7 and 8) |
| `ambiguous_grants` | Remove the overlap, so that one grant matches (steps 7 and 8) |
| `repositories_span_installations` | Use repositories of one GitHub organization for each task, or separate bindings |

If Imbi refuses the token for the project repository, run the project's
Doctor and apply the `identifier-verified` fix.

## Use one App for more than one agent

Nothing in Imbi requires one App for each agent. A grant can name more
than one agent, so other agents can use `ghe/reviewer`. Their commits and
pull requests then show as `reviewer[bot]`.
