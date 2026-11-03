# CodeFactoryAgent: Autonomous Jira-Driven Software Engineering Agent

`CodeFactoryAgent` is an autonomous AI software engineering bot designed to bridge the gap between a **Jira ticket** and a **GitHub Pull Request**. 

It functions like an automated software engineer on your team: given a ticket key (e.g., `DEMO-1`), it reads the story requirements, studies the target application's technical and domain context, creates an isolated feature branch, writes idiomatic code, updates living documentation, verifies changes with tests, and opens a Pull Request for human review.

---

## 💡 Conceptual Overview (From a Layman's Point of View)

```text
[ 1. Jira Ticket ]           [ 2. Feature Branch ]         [ 3. Project Context ]
 "DEMO-1: Add Input           Agent switches to main        Agent reads ARCHITECTURE.md
  Validation"                 & creates 'DEMO-1' branch     & DOMAIN_SPEC.md for rules
        │                                  │                               │
        ▼                                  ▼                               ▼
[ 4. Code Implementation ]    [ 5. Test Verification ]      [ 6. GitHub Pull Request ]
 Agent writes Java classes,   Agent runs 'mvn test'         Branch is pushed to GitHub;
 DTOs & updates openapi.yml   to verify no regressions      PR is opened for human review
```

### The Four Key Pieces:
1. **The Dispatcher (`run_agent.py` & `action.yml`):**
   The "Front Desk" or "Ignition Switch". It reads CLI parameters and environment variables, determines whether to run in Live Mode or Mock Mode, and boots up the AI agent.
2. **The Brain (`coding_agent/agent.py`):**
   The "Engineer's Mind". Powered by Google Gemini (`gemini-2.5-flash`), it operates on a decision loop. It reads instructions and uses its toolbelt to plan, edit, test, and commit code.
3. **The Toolbelt (`coding_agent/tools/`):**
   The "Hands and Senses". A suite of sandboxed Python functions providing Jira API access, Git branching, recursive file operations, automated test execution, and GitHub Pull Request creation.
4. **The Project Blueprint (`sample-springboot-app/`):**
   The "Engineering Handbook". Living documentation (`ARCHITECTURE.md`, `DOMAIN_SPEC.md`, `openapi.yml`) embedded directly in the target application so the agent adheres to existing coding standards without guessing.

---

## 🏗️ Architecture & Component Breakdown

```text
code-factory/
├── action.yml                  <-- GitHub Composite Action for CI/CD embedding
├── run_agent.py                <-- Entry point CLI supporting Live AI & Mock Simulation
├── requirements.txt            <-- Dependencies (google-genai, requests, python-dotenv, pytest)
├── .env.example                <-- Configuration template (live API keys & mock flags)
├── coding_agent/               <-- Core agent orchestration & tools
│   ├── __init__.py
│   ├── agent.py                <-- Agent declaration, system prompt & workflow rules
│   └── tools/                  <-- Sandboxed agent tools
│       ├── __init__.py
│       ├── jira_tools.py       <-- Jira REST v3/v2 client, ADF parser & mock mode
│       ├── repository_tools.py <-- Git branching, recursive filesystem & test runner
│       └── github_tools.py     <-- Remote git push, dry-run & Pull Request creator
└── tests/                      <-- Automated unit & integration test suite (15 tests)
    ├── __init__.py
    ├── test_jira_tools.py
    ├── test_repository_tools.py
    ├── test_github_tools.py
    └── test_workflow.py
```

---

## 📚 Living Context Engineering Protocol

To prevent AI code generation from making incorrect architectural assumptions, target applications (such as `sample-springboot-app`) contain **living documentation**:

| Living Document | Purpose | Agent Mandate |
| :--- | :--- | :--- |
| **`ARCHITECTURE.md`** | Technical guidelines, layering rules (Controller -> Service -> Repo), HTTP status codes, uniform error payloads, and testing standards. | **Read first** before writing code. Update if a new architectural pattern or library is introduced. |
| **`DOMAIN_SPEC.md`** | Business domain rules, entity invariants (e.g. unique email, non-blank name, positive salary), and endpoint contracts. | **Read first** before designing logic. Update if a new entity, field, or validation rule is added. |
| **`openapi.yml`** | REST API contract definition (schemas, paths, parameters, responses). | **Update on every endpoint change** so API specs never rot. |
| **`README.md`** | Project quickstart, Swagger/H2 URLs, and roadmap backlog checkboxes. | Update backlog checkboxes when a Jira ticket scope is satisfied. |

---

## 🛠️ Tooling Reference

| Tool | Purpose | Detailed Capabilities |
| :--- | :--- | :--- |
| `get_jira_issue` | Fetches Jira requirements | • Supports Jira Cloud REST API v3 and Server/Data Center REST API v2.<br>• Recursively parses Atlassian Document Format (ADF) into clean Markdown headings, bulleted/numbered lists, and code blocks.<br>• Discovers Acceptance Criteria from custom Jira fields (`names` map in `expand=names`) or description headings.<br>• Supports offline mock mode (`MOCK_JIRA=true`) with built-in realistic tickets (`DEMO-1`, `CUT-2`) or custom JSON fixtures. |
| `prepare_feature_branch` | Git workspace setup | • Detects or initializes target Git repository.<br>• Configures local Git identity (`user.name`, `user.email`) in local repo config.<br>• Checks out base branch (`main` or `master`) and creates/switches to a feature branch named after the ticket (e.g. `DEMO-1`). |
| `list_project_files` | Project exploration | • Recursively discovers files and directories with depth control (`max_depth=15`) to handle deep Java package structures.<br>• Strictly shields protected directories (`.git`, `target`, `.idea`, `node_modules`, `.venv`) and secrets (`.env*`). |
| `read_project_file` | Inspects code | • Safe UTF-8 file reader with path-traversal prevention (`..` escaping is blocked).<br>• Enforces maximum file size limit (500 KB). |
| `write_project_file` | Applies code changes | • Creates or updates source files with clean UTF-8 encoding.<br>• Automatically creates missing parent directories.<br>• Enforces security sandboxing, blocking edits to `.env` or cryptographic key files. |
| `run_project_tests` | Verification | • Automatically detects Maven (`mvnw`, `mvnw.cmd`, `mvn`) or Gradle (`gradlew`, `gradle`).<br>• Provides diagnostic feedback to the agent to fix code when tests fail.<br>• Supports diagnostic mock testing (`MOCK_TESTS=true`) when build tools are not present on the host PC. |
| `get_git_status` / `get_git_diff` | Code review | • Returns working-tree status and staged/unstaged diffs for agent self-review before committing. |
| `commit_changes` | Git commit | • Stages all modified and created files (`git add -A`).<br>• Safe against benign whitespace validation failures.<br>• Commits with a conventional commit message (e.g., `feat(DEMO-1): implement validation`). |
| `push_and_create_pull_request` | PR Creation | • Pushes feature branch to remote origin (supports authenticated URL with `GITHUB_TOKEN`).<br>• Formats rich Markdown PR description with Jira requirements, acceptance criteria, change summary, and test logs.<br>• Opens PR via GitHub REST API (handles duplicate open PRs gracefully).<br>• Supports dry-run simulation mode (`DRY_RUN=true`). |

---

## 🧪 Modes of Operation

### 1. Offline & Mock Simulation Mode (Zero API Keys Required)
Use this mode to verify the entire toolchain on your local machine without needing live Jira or Gemini API credentials:
```powershell
python run_agent.py --ticket DEMO-1 --mock --repo-dir ../sample-springboot-app
```
- **What happens:**
  1. Loads built-in mock ticket `DEMO-1` (Employee Validation & Duplicate Email Handling).
  2. Creates branch `DEMO-1` in `sample-springboot-app`.
  3. Discovers all 29 files/folders recursively.
  4. Simulates test verification.
  5. Simulates Pull Request creation against your configured repository slug (`anoopt-2026/sample-springboot-app`).

### 2. Live Autonomous Mode (With Gemini & GitHub Keys)
When you have your Gemini API key and GitHub token:
1. Open `code-factory/.env` and supply:
   ```env
   GOOGLE_API_KEY=AIzaSy...your_gemini_key...
   GITHUB_TOKEN=ghp_...your_github_token...
   GITHUB_REPOSITORY=anoopt-2026/sample-springboot-app
   MOCK_MODE=false
   DRY_RUN=false
   ```
2. Run the agent:
   ```powershell
   python run_agent.py --ticket DEMO-1 --repo-dir ../sample-springboot-app
   ```
- **What happens:** Gemini autonomously calls tools, reads `ARCHITECTURE.md` and `DOMAIN_SPEC.md`, writes Java code and updates `openapi.yml`, runs tests, commits, and opens a real Pull Request on GitHub.

---

## 💻 Local PC Setup & Verification

### Prerequisites
- Python 3.10+ (configured at `C:\WORK\tools\python` or in your system PATH)
- Git installed on PATH

### 1. Verify Installed Dependencies
Ensure required packages are installed in your Python environment:
```powershell
pip install requests python-dotenv pytest google-genai
```

### 2. Run the Automated Test Suite (15 Tests)
All agent tools include unit and integration tests using Python's standard `unittest` library:
```powershell
python -m unittest discover -s tests -v
```
**Test coverage:**
- `test_jira_tools.py`: Tests ADF JSON flattening, markdown heading extraction, and mock mode fallback.
- `test_repository_tools.py`: Tests path-traversal prevention, credential shielding, recursive file scanning, and mock test runner.
- `test_github_tools.py`: Tests repository slug parsing, PR Markdown body formatting, and dry-run execution.
- `test_workflow.py`: End-to-end integration test validating the entire 7-step autonomous tool pipeline.

---

## 🚀 Reusable GitHub Action Integration

To embed `CodeFactoryAgent` in any target repository (like `sample-springboot-app`), create the file:
`.github/workflows/code-factory-agent.yml`

```yaml
name: 'CodeFactoryAgent - Jira Story Implementation'

on:
  workflow_dispatch:
    inputs:
      jira_ticket_number:
        description: 'Jira Ticket Number (e.g. DEMO-1 or CUT-2)'
        required: true
        type: string
      mock_mode:
        description: 'Run in offline mock mode (testing without live credentials)'
        required: false
        type: boolean
        default: false

permissions:
  contents: write
  pull-requests: write

jobs:
  implement-story:
    name: 'Implement Jira Story'
    runs-on: ubuntu-latest

    steps:
      - name: Checkout Target Repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0 # Full history required for branching

      - name: Set up Java 21 Runtime
        uses: actions/setup-java@v4
        with:
          distribution: 'temurin'
          java-version: '21'
          cache: 'maven'

      - name: Run CodeFactoryAgent
        uses: your-org/code-factory@main
        with:
          jira_ticket_number: ${{ github.event.inputs.jira_ticket_number }}
          jira_base_url: ${{ secrets.JIRA_BASE_URL }}
          jira_email: ${{ secrets.JIRA_EMAIL }}
          jira_api_token: ${{ secrets.JIRA_API_TOKEN }}
          gemini_api_key: ${{ secrets.GOOGLE_API_KEY }}
          gemini_model: 'gemini-2.5-flash'
          github_token: ${{ secrets.GITHUB_TOKEN }}
          target_repo_dir: ${{ github.workspace }}
          mock_mode: ${{ github.event.inputs.mock_mode }}
```

---

## 🛡️ Security & Sandbox Controls

- **Prompt Injection Defense:** Jira story descriptions and acceptance criteria are treated strictly as passive requirements. The system prompt instructs the agent to treat Jira content as untrusted data, preventing user-supplied text from executing system attacks.
- **Credential Protection:** `.env`, `.env.*`, private keys (`id_rsa`, `*.key`, `*.pem`), and certificates are strictly blocked from being read, written, or committed.
- **Human in the Loop:** The agent operates exclusively on isolated feature branches and submits Pull Requests. Direct pushes to `main` are prevented, ensuring human engineers always review and merge code.
