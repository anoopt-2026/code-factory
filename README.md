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
├── action.yml                  <-- GitHub Composite Action for CI/CD embedding
├── run_agent.py                <-- Entry point CLI supporting Live AI & Mock Simulation
├── requirements.txt            <-- Dependencies (google-genai, networkx, requests, pytest)
├── .env.example                <-- Configuration template (live API keys & mock flags)
├── coding_agent/               <-- Core agent orchestration & tools
│   ├── __init__.py
│   ├── agent.py                <-- Agent declaration, system prompt & workflow rules
│   └── tools/                  <-- Sandboxed agent tools
│       ├── __init__.py
│       ├── jira_tools.py       <-- Jira REST v3/v2 client, ADF parser & mock mode
│       ├── codegraph_tools.py  <-- In-memory Spring Boot Code Graph & query tools
│       ├── repository_tools.py <-- Git branching, recursive filesystem & test runner
│       └── github_tools.py     <-- Remote git push, dry-run & Pull Request creator
└── tests/                      <-- Automated test suite (20 unit/integration tests)
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
| `prepare_feature_branch` | Git | Sets local identity, switches to `main`, and creates/checks out feature branch (e.g. `KAN-4`). |
| `get_architecture_graph` | Code Graph | Ingests structural Spring Boot architecture, REST routes, services, repositories, and entities. |
| `query_code_graph` | Code Graph | Queries routes, bean dependencies, symbol declarations, and blast-radius impact. |
| `list_project_files` | Filesystem | Recursively explores directory structure with depth controls (`max_depth=15`). |
| `read_project_file` | Filesystem | Reads UTF-8 source files with path-traversal prevention. |
| `write_project_file` | Filesystem | Creates or updates code and living documentation files safely. |
| `run_project_tests` | Verification | Executes `mvn test` / `gradle test` (or mock runner if build tools are absent). |
| `get_git_status` / `get_git_diff` | Git | Reviews staged/unstaged changes before committing. |
| `commit_changes` | Git | Stages files and creates a conventional commit referencing the ticket. |
| `push_and_create_pull_request` | GitHub | Pushes branch to `origin` and opens a formatted Pull Request for human review. |

---

## 🧪 Modes of Operation

### 1. Offline Simulation Mode (Zero API Keys)
```powershell
python run_agent.py --ticket DEMO-1 --mock --repo-dir ../sample-springboot-app
```

### 2. Live Autonomous Mode (With Gemini & Jira Keys)
```powershell
python run_agent.py --ticket KAN-4 --repo-dir ../sample-springboot-app
```

---

## 💻 Local Testing & Verification

Run the automated test suite (all **20 tests**):
```powershell
python -m unittest discover -s tests -v
```
- `test_jira_tools.py`: ADF parsing, mock tickets, AC extraction.
- `test_codegraph_tools.py`: AST parsing, route discovery, dependency graph, impact analysis.
- `test_repository_tools.py`: File safety, path traversal protection, recursive search.
- `test_github_tools.py`: Slug parsing, Markdown PR generation, dry-run mode.
- `test_workflow.py`: End-to-end 7-step autonomous tool pipeline test.

---

## 🚀 Reusable Workflow Integration (Zero-Boilerplate for Target Apps)

Target repositories (such as `sample-springboot-app`) can trigger `CodeFactoryAgent` using GitHub's **Reusable Workflow (`workflow_call`)** pattern with a clean, 20-line workflow file:

Create `.github/workflows/code-factory-agent.yml` in the target repository:
```yaml
name: 'CodeFactoryAgent'

on:
  # Manual UI Trigger with ticket number input
  workflow_dispatch:
    inputs:
      jira_ticket_number:
        description: 'Jira Ticket Number (e.g. KAN-4 or DEMO-1)'
        required: true
        type: string
      mock_mode:
        description: 'Run in offline mock mode (testing without live credentials)'
        required: false
        type: boolean
        default: false

  # Automated Webhook Trigger on Jira status change
  repository_dispatch:
    types: [jira_ticket_ready]

jobs:
  run-agent:
    name: 'Run CodeFactoryAgent'
    uses: abhishexing/Code-Factory-Agent/.github/workflows/agent-runner.yml@main
    with:
      jira_ticket_number: ${{ inputs.jira_ticket_number || github.event.client_payload.ticket_number }}
      mock_mode: ${{ inputs.mock_mode || false }}
    secrets: inherit
```

### Why This Reusable Workflow Pattern is Superior:
- **Centralized Logic:** Java 21 setup, Python environment, dependencies, Code Graph parsing, and execution commands live **100% inside `code-factory`**.
- **Zero Maintenance:** Updating agent prompts, tools, or dependencies in `code-factory` immediately benefits all caller repositories without editing their code.
- **Repository-Scoped Security:** Secrets and write permissions remain strictly scoped to the target repository.

---

## 🛡️ Security & Sandbox Controls

- **Prompt Injection Defense:** Jira text is treated as passive requirements (untrusted data).
- **Credential Protection:** `.env`, `.env.*`, keys (`*.key`, `*.pem`, `id_rsa`), and certificates are strictly shielded from read/write tools and git staging.
- **Human in the Loop:** The agent works exclusively on feature branches and submits Pull Requests. Direct pushes to `main` are strictly blocked.
