# CodeFactoryAgent: Autonomous Jira-Driven Software Engineering Agent

`CodeFactoryAgent` is an autonomous AI software engineering bot designed to bridge the gap between a **Jira ticket** and a **GitHub Pull Request**. 

It functions like an automated software engineer on your team: given a ticket key (e.g., `DEMO-1` or `KAN-4`), it reads the story requirements, analyzes the target application's **Code Graph** and architectural context, creates an isolated feature branch, writes idiomatic code, updates living documentation, verifies changes with tests, and opens a Pull Request for human review.

---

## 💡 Conceptual Overview (From a Layman's Point of View)

```text
[ 1. Jira Ticket ]           [ 2. Feature Branch ]         [ 3. Code Graph & Context ]
 "KAN-4: Add PUT Endpoint"   Agent switches to main        Agent queries Code Graph
                             & creates 'KAN-4' branch      & reads ARCHITECTURE.md
        │                                  │                               │
        ▼                                  ▼                               ▼
[ 4. Code Implementation ]    [ 5. Test Verification ]      [ 6. GitHub Pull Request ]
 Agent writes Java classes,   Agent runs 'mvn test'         Branch is pushed to GitHub;
 DTOs & updates openapi.yml   to verify no regressions      PR is opened for human review
```

### The Key Pieces:
1. **The Dispatcher (`run_agent.py` & `action.yml`):**
   The "Front Desk". It validates pre-flight Jira credentials, loads environment settings, and boots the agent.
2. **The Brain (`coding_agent/agent.py`):**
   Powered by Google Gemini (`gemini-2.5-flash`), it reasons autonomously across a multi-turn tool-calling loop.
3. **The Code Graph Engine (`coding_agent/tools/codegraph_tools.py`):**
   The "IDE Map". Parses Spring Boot ASTs into an in-memory directed graph (`networkx`), mapping endpoints, beans, repositories, entities, and dependency injection edges.
4. **The Toolbelt (`coding_agent/tools/`):**
   Sandboxed tools for Jira, Git, filesystem, test execution, and GitHub Pull Requests.
5. **The Project Blueprint (`sample-springboot-app/`):**
   Living documentation (`ARCHITECTURE.md`, `DOMAIN_SPEC.md`, `openapi.yml`) embedded in the target repo so the agent adheres to coding standards without guessing.

---

## 🏗️ Architecture & Component Breakdown

```text
code-factory/
├── action.yml                  <-- GitHub Composite Action for custom CI/CD pipelines
├── run_agent.py                <-- Entry point CLI supporting Live AI, Dry-Run & Mock Simulation
├── requirements.txt            <-- Dependencies (google-genai, networkx, requests, pytest, python-dotenv)
├── .env.example                <-- Configuration template (live API keys & mock flags)
├── coding_agent/               <-- Core agent orchestration & tools
│   ├── __init__.py
│   ├── agent.py                <-- Agent declaration, system prompt & workflow rules
│   └── tools/                  <-- Sandboxed agent tools
│       ├── __init__.py
│       ├── jira_tools.py       <-- Jira REST v3/v2 client, ADF parser & mock mode
│       ├── codegraph_tools.py  <-- In-memory Spring Boot Code Graph & query tools
│       ├── repository_tools.py <-- Git branching, collision resolution, recursive filesystem & test runner
│       └── github_tools.py     <-- Remote git push, dry-run simulation & Pull Request creator
└── tests/                      <-- Automated test suite (22 unit/integration tests)
    ├── __init__.py
    ├── test_jira_tools.py
    ├── test_codegraph_tools.py
    ├── test_repository_tools.py
    ├── test_github_tools.py
    └── test_workflow.py
```

---

## 🗺️ Code Graph Capabilities

The agent includes a native **Code Graph Engine** (`codegraph_tools.py`) that parses Spring Boot ASTs into a queryable relational graph:

| Tool | Purpose | Output |
| :--- | :--- | :--- |
| `get_architecture_graph` | Architectural overview | Maps all REST endpoints, controllers, service beans, repositories, JPA entities, and tests in ~300 tokens without reading raw files. |
| `query_code_graph(query_type='routes')` | Route inspection | Discovers endpoints matching a path or HTTP method (e.g. `POST /employees` ➔ `EmployeeController.create`). |
| `query_code_graph(query_type='dependencies')` | Bean graph | Traces constructor injection edges (e.g. `EmployeeController ─► EmployeeService ─► EmployeeRepository`). |
| `query_code_graph(query_type='symbol')` | Symbol lookup | Finds exact declaration file, line number, return type, and parameters for any class or method. |
| `query_code_graph(query_type='impact')` | Blast radius | Computes transitive upstream dependencies: *"If EmployeeRepository changes, what controllers, services, and endpoints are impacted?"* |

---

## 🛠️ Complete Tooling Reference

| Tool | Category | Purpose |
| :--- | :--- | :--- |
| `get_jira_issue` | Jira | Fetches ticket summary, description, and acceptance criteria. Supports Cloud REST API v3/v2 and offline mock mode (`MOCK_JIRA=true`). |
| `prepare_feature_branch` | Git | Sets local identity, switches to `main`, and creates/checks out a feature branch with automated collision resolution (e.g., `KAN-4`, `KAN-4-1`, `KAN-4-2`). |
| `get_architecture_graph` | Code Graph | Ingests structural Spring Boot architecture, REST routes, services, repositories, and entities. |
| `query_code_graph` | Code Graph | Queries routes, bean dependencies, symbol declarations, and blast-radius impact. |
| `list_project_files` | Filesystem | Recursively explores directory structure with depth controls (`max_depth=15`). |
| `read_project_file` | Filesystem | Reads UTF-8 source files with path-traversal prevention. |
| `write_project_file` | Filesystem | Creates or updates code and living documentation files safely. |
| `run_project_tests` | Verification | Executes `mvn test` / `gradle test` (or mock runner if build tools are absent). |
| `get_git_status` / `get_git_diff` | Git | Reviews staged/unstaged changes before committing. |
| `commit_changes` | Git | Stages files and creates a conventional commit referencing the ticket. |
| `push_and_create_pull_request` | GitHub | Pushes branch to `origin` and opens a formatted Pull Request for human review (supports `DRY_RUN=true`). |

---

## 🧪 Modes of Operation

`run_agent.py` provides three flexible modes of operation:

### 1. Offline Simulation Mode (Zero API Keys)
Run the full 7-step pipeline locally without any external credentials or network dependencies. Uses realistic built-in mock Jira specifications (`DEMO-1` for validation rules or `CUT-2` for update endpoints, or any arbitrary ticket key):
```powershell
python run_agent.py --ticket DEMO-1 --mock --repo-dir ../sample-springboot-app
```

### 2. Dry-Run Mode (Live AI & Jira, Simulated Git Push & PR)
Executes live reasoning with Google Gemini and live Jira ticket retrieval, but prevents remote Git pushes or PR creation, keeping all modifications local for safe inspection:
```powershell
python run_agent.py --ticket KAN-4 --dry-run --repo-dir ../sample-springboot-app
```

### 3. Live Autonomous Mode (Full Production Pipeline)
Executes end-to-end against live Jira, Gemini AI, and GitHub, pushing the feature branch and opening a Pull Request:
```powershell
python run_agent.py --ticket KAN-4 --repo-dir ../sample-springboot-app
```

### CLI Options Reference
| Flag | Short | Environment Variable | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `--ticket` | `-t` | `JIRA_ISSUE_KEY` / `JIRA_TICKET_NUMBER` | None | Jira ticket number / issue key (e.g., `DEMO-1`, `KAN-4`) |
| `--repo-dir` | `-r` | `TARGET_REPO_DIR` / `GITHUB_WORKSPACE` | `../sample-springboot-app` or `.` | Target repository workspace path |
| `--model` | `-m` | `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model name |
| `--mock` | | `MOCK_MODE` / `MOCK_JIRA` | `false` | Run in offline mock mode without API keys |
| `--dry-run` | | `DRY_RUN` | `false` | Prevent remote git pushes and live GitHub PR creation |

---

## 🛡️ Workspace State Preservation & Rollback Safety

The agent features an integrated **Workspace Session Manager** (`WorkspaceSession`) to ensure developer workspaces remain clean, predictable, and safe:

1. **Pre-Execution State Snapshot:** Captures the starting branch before any changes occur.
2. **Automated Rollback on Failure or Cancellation:** If execution is aborted (`Ctrl+C` / `SIGINT`) or encounters a fatal configuration failure, uncommitted partial edits are safely discarded (`git reset --hard` & `git clean -fd`) and the repository is returned to its base branch (`main`).
3. **Local Commit Preservation & Incident Reports:** If implementation and tests succeed locally but remote GitHub PR creation fails (e.g., expired token or permission limits), the agent preserves your local feature branch and commit, printing a diagnostic incident report with the exact manual push command:
   ```text
   git -C "<repo-path>" push -u origin <branch-name>
   ```
4. **Semantic Exit Codes:**
   - `0`: Execution completed successfully (`EXIT_SUCCESS`)
   - `1`: Configuration / Pre-flight error (`EXIT_CONFIG_ERROR`)
   - `2`: External service / API / PR failure (`EXIT_EXTERNAL_SERVICE_ERROR`)
   - `3`: Test verification failure (`EXIT_VERIFICATION_ERROR`)
   - `130`: Interrupted via SIGINT / Ctrl+C (`EXIT_INTERRUPTED`)

---

## 💻 Local Testing & Verification

Run the automated test suite (all **22 tests**):
```powershell
python -m unittest discover -s tests -v
```
*(Alternatively, run `pytest` if installed in your environment)*

- `test_jira_tools.py`: ADF parsing, mock tickets (`DEMO-1`, `CUT-2`, arbitrary keys), AC extraction, and error handling.
- `test_codegraph_tools.py`: AST parsing, route discovery, dependency injection graphs, symbol lookup, and blast-radius impact analysis.
- `test_repository_tools.py`: Branch collision counter (`KAN-4`, `KAN-4-1`, `KAN-4-2`), file safety, path traversal protection, sensitive credential isolation, and recursive search.
- `test_github_tools.py`: Repository slug resolution from env/git remotes, Markdown PR generation, and dry-run mode.
- `test_workflow.py`: End-to-end multi-step autonomous tool pipeline test.

---

## 🚀 CI/CD & GitHub Actions Integration

`CodeFactoryAgent` supports two GitHub Actions integration patterns:

### Option A: Reusable Workflow (`workflow_call`) — Recommended
Target repositories (such as `sample-springboot-app`) can trigger `CodeFactoryAgent` with a clean, zero-boilerplate workflow file.

Create `.github/workflows/code-factory-agent.yml` in the target repository:
```yaml
name: 'CodeFactoryAgent'

on:
  # Manual UI Trigger with configurable inputs
  workflow_dispatch:
    inputs:
      jira_ticket_number:
        description: 'Jira Ticket Number (e.g. KAN-4 or DEMO-1)'
        required: true
        type: string
      gemini_model:
        description: 'Gemini model name'
        required: false
        type: choice
        options:
          - 'gemini-2.5-flash'
          - 'gemini-2.5-pro'
        default: 'gemini-2.5-flash'
      dry_run:
        description: 'Simulate git push and PR creation without modifying remote repository'
        required: false
        type: boolean
        default: false
      mock_mode:
        description: 'Run in offline mock mode (testing without live credentials)'
        required: false
        type: boolean
        default: false
      java_version:
        description: 'Java runtime version for target app'
        required: false
        type: string
        default: '21'

  # Automated Webhook Trigger on Jira status change
  repository_dispatch:
    types: [jira_ticket_ready]

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  run-agent:
    name: 'Run CodeFactoryAgent'
    uses: anoopt-2026/code-factory/.github/workflows/agent-runner.yml@main
    with:
      jira_ticket_number: ${{ inputs.jira_ticket_number || github.event.client_payload.jira_ticket_number || github.event.client_payload.ticket_number }}
      gemini_model: ${{ inputs.gemini_model || github.event.client_payload.gemini_model || 'gemini-2.5-flash' }}
      dry_run: ${{ inputs.dry_run || github.event.client_payload.dry_run || false }}
      mock_mode: ${{ inputs.mock_mode || github.event.client_payload.mock_mode || false }}
      java_version: ${{ inputs.java_version || github.event.client_payload.java_version || '21' }}
    secrets: inherit
```

#### Why This Reusable Workflow Pattern is Superior:
- **Centralized Logic:** Java 21 setup, Python 3.11 environment, dependencies, Code Graph parsing, and execution commands live **100% inside `code-factory`**.
- **Zero Maintenance:** Updating agent prompts, tools, or dependencies in `code-factory` immediately benefits all caller repositories without editing their code.
- **Repository-Scoped Security:** Secrets and write permissions remain strictly scoped to the target repository.

### Option B: Composite Action (`action.yml`)
For custom workflows needing direct step-level control, use the repository as a composite action:
```yaml
- name: Run CodeFactoryAgent Action
  uses: anoopt-2026/code-factory@main
  with:
    jira_ticket_number: 'KAN-4'
    gemini_api_key: ${{ secrets.GOOGLE_API_KEY }}
    jira_base_url: ${{ secrets.JIRA_BASE_URL }}
    jira_email: ${{ secrets.JIRA_EMAIL }}
    jira_api_token: ${{ secrets.JIRA_API_TOKEN }}
    github_token: ${{ secrets.GITHUB_TOKEN }}
    dry_run: 'false'
```

---

## 🔒 Security & Sandbox Controls

- **Prompt Injection Defense:** Jira text is treated as passive task requirements (untrusted data). It cannot override agent instructions.
- **Credential Protection:** `.env`, `.env.*`, keys (`*.key`, `*.pem`, `id_rsa`), and certificates (`*.p12`, `*.pfx`) are strictly shielded from read/write tools and git staging.
- **Branch Collision Prevention:** Automatically checks local and remote branches to increment branch names (`KAN-4-1`, `KAN-4-2`), preventing accidental overwrites.
- **Human in the Loop:** The agent works exclusively on feature branches and submits Pull Requests. Direct pushes to `main` are strictly blocked.
