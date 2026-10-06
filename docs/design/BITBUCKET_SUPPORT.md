# Bitbucket repositories — design and plan

> Status: **built, 2026-10-05 (T1–T6)**; T0, the office check, is still to run. The office's code is on
> **Bitbucket**; Data Center (self-hosted) is assumed, from the on-prem rule — T0 confirms it.
> Built as planned, plus: for a Bitbucket URL, with or without a token, git asks neither the machine's
> credential helper nor an askpass program (Git Credential Manager made a refused sign-in wait about
> two minutes, and could answer with a login stored on the server); the `/scm/` rule never applies to
> github.com or gitlab.com; the wizard's clone cache is keyed by the token too. Detail: the project
> history, 2026-10-05r.
> Mockup: [projects-empty.html](../ui-mockups/projects-empty.html), New Project wizard, step 1.
> Skills to load: `engine-flowchart` (`engine/incremental/` — the clone primitive), `engine-dev`, `ui-dev`
> (`web-app/`), `docs-maintainer`.

## The problem, as it is today

| # | What happens | Why it fails on Bitbucket |
|---|---|---|
| 1 | Every git call sends the access token **as the username, with an empty password**: `https://<token>:@host/…` (`repo_git._creds`, `pipeline_runner._checkout`, `clone._do_checkout`, `clone._fetch_commit`). GitHub accepts that. | Bitbucket Data Center takes an HTTP access token as `Authorization: Bearer <token>` (project and repository tokens: [the only way](https://confluence.atlassian.com/bitbucketserver/http-access-tokens-939515499.html)) or as the password with its owner's username. Bitbucket Cloud takes it with the fixed username `x-token-auth` ([docs](https://support.atlassian.com/bitbucket-cloud/docs/using-api-tokens/)). So a private Bitbucket repository fails Test Connection, Browse, the config check, the commit list and the job's clone. |
| 2 | The URL people copy is the repository **page** (`https://host/projects/VCU/repos/vcu-firmware/browse`). | Not a clone URL: git answers "not found". The clone URL is `https://host/scm/vcu/vcu-firmware.git`. |
| 3 | git's 401 comes out as "Could not reach the remote — …" (`_friendly` matches "unable to access" first) or as git's raw last line. | The user is not told the token is missing or wrong. |
| 4 | Step 1 says "Git URL" (read as GitHub), shows a GitHub placeholder, hides the token behind a link, and carries several lines of explanation. | Confusing for a Bitbucket user; too much text. |

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **How the token is sent is read from the URL, never asked.** See the table below. | The URL says the host; one rule, no provider picker, no Username box. |
| D2 | **A Bitbucket token goes in an HTTP header, through the environment**: `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=http.<scheme>://<host>[:port]/.extraHeader`, `GIT_CONFIG_VALUE_0=Authorization: …`. Scoped to the repository's host, so a redirect elsewhere never carries it. Never in argv, the URL, `.git/config`, a log line or an error message. Needs git ≥ 2.31 (T0 checks the office's). | argv is visible in the process list; a URL leaks into git's messages. |
| D3 | **No Username box.** Data Center always gets Bearer. | Bearer is the only way a project or repository token works. A personal token with Bearer is not confirmed by Atlassian's page — T0 checks it. If it fails, the office uses a project or repository token (Repository read), or a username field comes back as a separate change. |
| D4 | **A Bitbucket page address becomes its clone URL on the server**, and Test Connection returns the URL it used (`repo_url`); the wizard puts it in the box. | The server is the one place every path (wizard, API, config preview, create) goes through. |
| D5 | **Storage unchanged**: the token stays in `build_config.repo_access_token`; no migration. `projects.repo_provider` is set from the URL on create (`bitbucket` for Bitbucket URLs, `local` as today, otherwise as today). Display only: D1 never reads it. | The rule needs only the URL and the token, which every caller already has. |
| D6 | **GitHub, GitLab, SSH and local folders behave exactly as today**: same URL, same git arguments. | Nothing that works may move. |
| D7 | **Step 1 is minimal** — the mockup: no explanatory text. | The user asked for a simple screen. |

**D1 — the rule** (one function, used by every git call that talks to a remote):

| The repository URL | The token is sent as |
|---|---|
| `ssh://…`, `git@host:…`, a local folder | not at all (the server's SSH key; file access) — as today |
| `https://bitbucket.org/…` (Cloud) | header `Authorization: Basic base64("x-token-auth:<token>")` |
| `https://…/scm/…` (Data Center; a context path before `/scm/` is fine) | header `Authorization: Bearer <token>` |
| any other `http(s)://` (GitHub, GitLab, other servers) | unchanged: `https://<token>:@host/…` |

**D4 — page address → clone URL:**

| Pasted | Becomes |
|---|---|
| `https://host[/ctx]/projects/VCU/repos/vcu-firmware[/browse…]` | `https://host[/ctx]/scm/vcu/vcu-firmware.git` (project key lower-cased) |
| `https://host[/ctx]/users/<name>/repos/<repo>[/…]` | `https://host[/ctx]/scm/~<name>/<repo>.git` |
| `https://bitbucket.org/<workspace>/<repo>[/src/…]` | `https://bitbucket.org/<workspace>/<repo>.git` |

## The screen (mockup, step 1)

| Element | Today (web app) | New |
|---|---|---|
| Source toggle | `Git URL` \| `Local path` | `Remote` \| `Local` |
| URL placeholder | `https://github.com/org/repo.git` | `https://bitbucket.company.com/scm/vcu/vcu-firmware.git` |
| Local hint ("A git repository on the server … holds .git …") | shown under Local | removed |
| Folder path typed under Remote | "… not a URL. Use Local path" | "… not a URL. Switch to Local" |
| Access token | a link "Private repository? Add an access token", then the field, with "Optional — for private repos" | the **Access Token** field, always shown for Remote; hidden for Local and for an `ssh://` / `git@host:` URL; placeholder "Paste the access token"; no side note |
| After Test Connection | — | a page address is replaced in the box by the clone URL the server returned |
| Sign-in failure | "Could not reach the remote …" | "Authentication failed — this repository needs an access token." (none sent) · "Authentication failed — check the access token." (one sent); the cursor moves to the token box |
| Config card | "Fills the project, repository, cores and architecture from the config `analyzer.py onboard --config` reads. …" | "Have a config file?" · "Fills the project, repository, cores and architecture." |
| Review step | Access Token `••••••••` / Not set | unchanged |

The token is still never kept in the draft (`draft.ts`): a restored draft that used one opens on step 1
and asks for it again; the `tokenOpen` state goes, since the field is always there.

## Plan

| # | Task | Where | Notes |
|---|---|---|---|
| **T0** | **Office check** (no code; the office runs it, before T1 merges). Commands below. | the office machine | Decides D2's git version, D3, and whether T8 is needed. |
| **T1** | **One credential function** per D1/D2 — e.g. `git_auth(url, token) -> (git_url, extra_env)` in `engine/incremental/clone.py` (the platform's one clone primitive; the API already imports it). `git_ops._run` and `api/services/git_cli._run` take extra env. Every remote git call uses it: `clone.shallow_clone`, `clone._do_checkout`, `clone._fetch_commit`, `git_cli.ls_remote`, `git_cli.fetch`, `pipeline_runner._checkout`. Pass the token once (`token=`); drop the `username=token, password=""` convention (`repo_git._creds`, `pipeline_runner._checkout`, `_do_checkout`). `git_cli`'s copies of `_auth_url` / `_clean_url` go. | `engine/incremental/clone.py`, `git_ops.py`; `api/services/git_cli.py`, `repo_git.py`, `pipeline_runner.py` | `resolve_project_repo` and its callers (`generate.py`, `engine.py`, `source_checkout.py`) stay as they are: they already pass URL + token. |
| **T2** | **Page address → clone URL** per D4: one function in `repo_git`, applied in test-connection, both browse routes, `POST /projects/config/preview` and `POST /projects`. `TestConnectionResponse` gains `repo_url` (the URL used). | `api/services/repo_git.py`, `api/routes/repositories.py`, `api/routes/projects.py`, `api/schemas.py`, `api/swagger.json` | |
| **T3** | **Messages.** `_friendly` checks sign-in failures first: "authentication failed", "could not read username", "could not read password", "returned error: 401", "returned error: 403". Two answers, by whether a token was sent (see the screen table). | `api/services/repo_git.py` | |
| **T4** | **`repo_provider` from the URL** on create (D5). | `api/routes/projects.py` | The client's `repo_provider` is ignored except `local`, as today. |
| **T5** | **Wizard step 1** as the screen table: toggle labels, placeholders, the local hint, the "Switch to Local" link, the always-there token field (`tokenOpen` goes), hide the token for an SSH URL (`^ssh://` or `^[\w.-]+@[\w.-]+:`), put `res.repo_url` in the box after Test Connection, focus the token on a sign-in failure, stop sending `repo_provider: 'github'` on create, the config card's line. | `web-app/src/pages/NewProjectPage/index.tsx` (~940–995, 261, 361, 448–470, 843), `components/ConfigImport.tsx:81`, `draft.ts`, `services/api/repositories.ts` (`repoUrl` in the result), tests in `NewProjectPage/__tests__/` | |
| **T6** | **Tests and docs** — below. | | |

**T0 — the office check** (PowerShell; a token with Repository read; `<url>` = the `/scm/…` clone URL):

```powershell
git --version                                     # 2.31 or later for D2
$h = "Authorization: Bearer <token>"
git -c "http.extraHeader=$h" ls-remote --symref <url> HEAD          # once with a project/repository token, once with a personal one
git -c "http.extraHeader=$h" clone --depth 1 --filter=blob:none --no-checkout <url> probe
git -C probe -c "http.extraHeader=$h" fetch --depth 1 <url> <an older commit sha>
```

| Answer | Means |
|---|---|
| `ls-remote` lists branches with a personal token | D3 holds for every token type |
| `ls-remote` 401 with a personal token, OK with a project token | use project/repository tokens (or reopen D3) |
| `warning: filtering not recognized by server` | Browse still works (depth 1), only slower |
| the fetch by SHA is refused | fine: `_fetch_commit` falls back to `--unshallow` |
| a certificate error | T8 (CA bundle) is needed |
| the repository uses Git LFS | check the checkout: Bearer + LFS has a known Bitbucket issue (BSERV-13613) |

**T6 — tests and docs**

- **Unit** (`tests/unit`): `git_auth` for every row of D1. GitHub and GitLab are byte-for-byte as today. The
  Bitbucket token is never in a `_run` argument list, never in `.git/config` after a clone or fetch, never in a
  `GitError` message. The header is scoped to the repository's host. D4's table.
- **End to end without the office** (recommended): a small HTTP server in the test that answers 401 without
  `Authorization: Bearer <t>` and hands the rest to `git http-backend` (CGI) over a bare repository at a
  `/scm/…` path. Run test-connection, browse, the commit list and `ensure_commit_checkout` through it.
- **API** (`tests/api`): a page address returns its clone URL in `repo_url`; create stores `repo_provider`
  `bitbucket`; the two sign-in messages. Mind `tests/api` uses the real config.local.json database unless
  overridden.
- **Web**: `npm test` in `web-app/` (a bare `npx vitest run` also runs the live API suite, which writes).
- **Docs**: `api/README.md` (test-connection's `repo_url`), `api/swagger.json`,
  [API_AND_FRONTEND.md](../../project-context/API_AND_FRONTEND.md), a dated history entry and its TIMELINE line;
  this doc's status → built.

**Later — not in this task**

| # | Task | When |
|---|---|---|
| T7 | Replace a project's access token after it is created (Data Center tokens expire; there is no route for it today). | Needs a mockup first. |
| T8 | A CA bundle machine setting (`repositories.caBundle` → `GIT_SSL_CAINFO`). | Only if T0 shows a certificate error; git on Windows trusts the Windows store. |
| T9 | `analyzer.py onboard --source <url>` with a token, read from an environment variable (never an argument). | Only if the office clones from the CLI. |
| — | The token is stored in plain text in `build_config`, for every host; [study 03](../production-redesign/03-incremental-changes-design.md) says it should be stored encrypted. | Separate item. |

## Open questions

- Data Center or Cloud? (Assumed Data Center.)
- Does a personal token work with Bearer? (T0)
- HTTPS token, or the server's SSH key? An SSH URL needs none of this: it works today if the server's key is
  registered in Bitbucket.
