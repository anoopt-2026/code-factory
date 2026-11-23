# Architecture Specification: CodeFactoryAgent

This document provides a comprehensive technical architecture specification of the `code-factory` codebase. It reflects the concrete implementation present in the repository and serves as foundational context for engineering and autonomous self-hosting tasks.

---

## 1. System Topology & Directory Structure

The system is organized into an orchestration layer, an agent configuration layer, a modular tool suite, and an automated test suite:

```text
code-factory/
├── run_agent.py                     # CLI entrypoint, argument parsing, session lifecycle & tool loop
├── action.yml                       # Composite GitHub Action for embedding in target repos
├── requirements.txt                 # Core dependencies (google-genai, networkx, requests, etc.)
├── .github/
│   └── workflows/
│       └── agent-runner.yml         # Reusable GitHub Actions workflow (workflow_call)
├── coding_agent/                    # Core agent package
│   ├── __init__.py                  # Package declaration, root_agent & Ponytail principles export
│   ├── agent.py                     # Agent definition, Ponytail instructions, and tool bindings
│   └── tools/                       # Modular tool implementations
│       ├── __init__.py              # Central tool registry and __all__ exports
│       ├── jira_tools.py            # Jira Cloud REST API & ADF parsing + mock issues
│       ├── repository_tools.py      # Sandboxed filesystem, Git operations, test execution
│       ├── codegraph_tools.py       # In-memory Java AST parser & NetworkX code graph
│       └── github_tools.py          # Git push authentication & GitHub PR creation
└── tests/                           # Unit and workflow test suites
    ├── test_jira_tools.py           # Jira parsing and mock issue validation
    ├── test_repository_tools.py     # Filesystem bounds, mock tests, Git branching
    ├── test_codegraph_tools.py      # Java AST parsing, dependency edges, impact queries
    ├── test_github_tools.py         # PR generation and dry-run payloads
    ├── test_workflow.py             # 8-step autonomous tool pipeline integration test
    └── test_ponytail_mode.py        # Ponytail Mode minimal & maintainable generation tests
```

---

## 2. Component Responsibilities

### 2.1 `run_agent.py` (CLI Orchestrator & Execution Driver)
`run_agent.py` is the execution root of the system. It handles:
- **CLI & Argument Parsing (`parse_args`):** Parses `--ticket`, `--repo-dir`, `--model`, `--mock`, `--dry-run`, and Ponytail mode controls (`--ponytail`, `--no-ponytail`).
- **Environment Normalization (`setup_environment`):** Maps GitHub Action inputs (`INPUT_*`) and `.env` variables into standard configuration keys, setting `PONYTAIL_MODE`.
- **Session Safety & Rollback (`WorkspaceSession`):** Captures the active repository branch before operations begin; intercepts `SIGINT`/`SIGTERM` via signal handlers; executes automated Git cleanup (`git reset --hard`, `git clean -fd`, or `git stash`) on interruption or fatal failure.
- **Pre-flight Validation:** Verifies the existence of `TARGET_REPO_DIR` and pre-fetches the Jira issue before launching AI reasoning.
- **Step Logging (`_log_tool_step`):** Formats real-time terminal diagnostics with icon markers for each autonomous tool call, including Ponytail diff audits.
- **Dual Execution Pipelines:**
  - `run_simulation_mode`: Deterministic offline pipeline for testing without Gemini credentials, asserting Ponytail minimal changes and diff review.
  - `run_agent_async`: Multi-turn conversational tool-calling loop using Google GenAI SDK with Ponytail directives embedded in the reasoning prompt.

### 2.2 `coding_agent/agent.py` (Agent Specification & Ponytail Mode)
Defines the `root_agent` configuration:
- Configures default model name (`gemini-2.5-flash`).
- Declares the **Ponytail Mode Principles** and **Mandatory 10-Step Workflow** system instruction covering Jira ingestion, branching, CodeGraph inspection, living documentation reading, minimal idiomatic implementation, test verification, diff review, commit, and PR creation.
- Binds the 14 public tool functions to the agent instance. Includes a fallback `Agent` class for environments where `google.adk.agents` is not installed.
- Exports `PONYTAIL_PRINCIPLES` and `is_ponytail_mode_enabled()` for runtime inspection and testing.

### 2.3 `coding_agent/tools/` (Tool Ecosystem)
Contains discrete, single-responsibility tool modules. Each function is designed to be directly callable by Gemini as a tool call and returns a JSON-serializable dictionary.

---

## 3. Ponytail Mode Architecture & Principles

Ponytail Mode governs code generation across all agent operations to ensure minimal, reusable, and maintainable software modifications:

### 3.1 The 5 Core Ponytail Principles
1. **Reuse Existing Implementations:**
   - Ingest existing architecture, services, repositories, and utilities before creating new components.
   - Reuse existing functionality and avoid duplicate logic or boilerplate implementations.
2. **Minimal Code Changes:**
   - Modify only files strictly necessary to satisfy the Jira ticket requirements and acceptance criteria.
   - Avoid unrelated refactoring, cosmetic restyling, or unnecessary code churn.
   - Do not introduce unnecessary classes, interfaces, generic wrappers, or abstractions.
3. **YAGNI (You Aren't Gonna Need It) Principle:**
   - Implement only explicitly required functionality.
   - Avoid speculative features, premature generalizations, and hypothetical extensibility.
   - Do not introduce third-party dependencies without a clear, explicit requirement.
4. **Architecture Compliance:**
   - Follow existing project architecture, package structures, naming conventions, and coding patterns.
   - Adhere strictly to the living documentation (`ARCHITECTURE.md`, `DOMAIN_SPEC.md`, `openapi.yml`).
5. **Implementation & Diff Review:**
   - Review the generated Git diff (`get_git_diff` and `get_git_status`) before committing.
   - Identify and remove any accidental, temporary, or unnecessary modifications.
   - Ensure all functional requirements and tests are preserved without regressions.

---

## 4. Execution Workflows & Gemini Integration

### 4.1 Live Gemini Execution Workflow (`run_agent_async`)
When `GOOGLE_API_KEY` or `GEMINI_API_KEY` is present and `--mock` is disabled:

```text
User / CI Command
       │
       ▼
run_agent.py: main() -> run_agent_async()
       │
       ├─► 1. Pre-flight Check: validate TARGET_REPO_DIR
       ├─► 2. WorkspaceSession: capture current branch (e.g. main)
       ├─► 3. Pre-flight Jira Fetch: get_jira_issue(ticket)
       ├─► 4. Ponytail Config: evaluate PONYTAIL_MODE (default: enabled)
       ├─► 5. Initialize google.genai.Client(api_key)
       ├─► 6. chat = client.chats.create(model, config)
       │       (system_instruction = root_agent.instruction, tools = tool_list)
       │
       ▼
Multi-turn Conversation Loop (up to max_steps = 30):
 ┌───► chat.send_message(prompt with Ponytail directives or tool_responses)
 │     │
 │     ├─► If response.function_calls:
 │     │     For each call in response.function_calls:
 │     │       1. Dispatch to tool_map[call.name](**call.args)
 │     │       2. _log_tool_step(step, name, args, result, ticket)
 │     │       3. Record branch, commit, PR status
 │     │       4. Fail-fast on critical errors (e.g. branch creation failure)
 │     │       5. Format types.Part.from_function_response(...)
 │     │     Loop continues with tool responses
 │     │
 │     └─► If no function_calls:
 │           Loop terminates. Print final agent response text.
 └─────────────────────────────────────────────────────────
       │
       ▼
Session Completion:
 - If local commit created -> session.mark_success()
 - If PR error occurred -> output manual push instruction & return EXIT_EXTERNAL_SERVICE_ERROR
 - Finally: session.cleanup_on_exit() runs (no-op if marked success)
```

### 4.2 Simulation / Offline Mode (`run_simulation_mode`)
When `--mock` is specified or no Gemini API key is configured, `run_agent.py` executes a fixed sequential pipeline:
1. `get_jira_issue(ticket)` (reads mock issue or live Jira)
2. `prepare_feature_branch(ticket)`
3. `get_architecture_graph()`
4. `list_project_files()`
5. `run_project_tests(ticket)`
6. `get_git_diff()` & `get_git_status()` (Ponytail diff review)
7. `push_and_create_pull_request(ticket, ...)` (dry-run simulation reflecting Ponytail principles)

---

## 5. Tool Architecture & Registration Process

### 5.1 Tool Contract Pattern
Every tool function adheres to the following structural conventions:
- **Pure Function Signature:** Annotated parameters with docstrings explaining argument meaning.
- **Context Awareness:** Functions operating in the repository accept an optional `issue_key: Optional[str] = None`.
- **Structured Dictionary Returns:** 
  - On success: Returns operational keys (e.g., `{"success": True, "path": ..., ...}`).
  - On failure: Returns `{"error": "<descriptive message>"}` rather than raising uncaught exceptions, allowing the LLM to inspect errors and self-correct.

### 5.2 Exact Tool Registration Process
To introduce a new tool into `code-factory`, the tool must be registered across three core locations:

1. **Step 1: Implement the function in a tool module**
   - Place in an existing file under `coding_agent/tools/` or create a new `coding_agent/tools/<new>_tools.py`.
   - Ensure the return type is a dictionary and all exceptions are caught and converted to `{"error": str(exc)}`.

2. **Step 2: Export in `coding_agent/tools/__init__.py`**
   - Import the function and add its string name to `__all__`.

3. **Step 3: Register with Agent in `coding_agent/agent.py`**
   - Import the tool from `.tools.<new>_tools`.
   - Add the tool to the `tools=[...]` list of `root_agent`.
   - Update `root_agent.instruction` if the agent must follow specific workflow rules when calling it.

4. **Step 4: Register in `run_agent.py`**
   - Import the tool into `run_agent_async()` inside `run_agent.py`.
   - Add the tool function to the local `tools = [...]` list (which forms `tool_map`).
   - (Optional) Add a custom formatting block in `_log_tool_step()` to render clean terminal progress when the tool executes.

---

## 6. Repository Management, Git & Safety Bounds

### 6.1 Repository Path Resolution (`_get_target_repo`)
Target repository path is resolved with the following priority order:
1. `TARGET_REPO_DIR` environment variable.
2. `GITHUB_WORKSPACE` environment variable (in GitHub Actions).
3. Sibling or parent-adjacent `sample-springboot-app` directory.
4. Current working directory (`Path.cwd()`).

### 6.2 Sandboxed Path Access (`_safe_file`)
All file reads, writes, and directory scans pass through `_safe_file()`:
- **Path Traversal Shield:** Rejects absolute paths or relative paths resolving outside the target repository root.
- **Protected Directories (`EXCLUDED_DIRS`):** Completely excludes `.git`, `.idea`, `.vscode`, `target`, `.mvn`, `__pycache__`, `node_modules`, `build`, and `.venv`.
- **Protected File Names (`PROTECTED_NAMES`):** Blocks access to `.env`, `.env.local`, `.env.production`, `id_rsa`, and `id_ed25519`.
- **File Extension Shields:** Writing files with `.pem`, `.key`, `.p12`, or `.pfx` is strictly prohibited.
- **Size Bounds:** Reading or writing files exceeding `500,000` bytes (`MAX_FILE_BYTES`) is rejected.

### 6.3 Git Operations & Branching Logic
All Git commands execute via `_git(repo, *args)` using `subprocess.run`:
- **Predictable Identity:** Configures `user.name` (default: `CodeFactoryAgent`) and `user.email` (default: `codefactoryagent@users.noreply.github.com`).
- **Collision Counter:** Before creating feature branches, `prepare_feature_branch` queries local branches and remote heads via `git ls-remote`. If `KAN-4` exists, it increments to `KAN-4-1`, `KAN-4-2`, etc.
- **Commit Constraints:** `commit_changes` enforces single-line messages under 200 characters and runs `git diff --cached --quiet` to prevent empty commits.
- **Remote Push:** `push_and_create_pull_request` tries standard Git push; if rejected, falls back to authenticated token URL (`https://x-access-token:{token}@github.com/{slug}.git`).

---

## 7. CodeGraph Architecture & Integration

Located in `coding_agent/tools/codegraph_tools.py`, the Code Graph Engine builds an in-memory `networkx.DiGraph` directly from Java source files (`src/main/java` and `src/test/java`) without external language servers:

### 7.1 Two-Phase AST Construction
1. **Phase 1 (Discovery):** Scans all `.java` files for class, interface, and record declarations via regex. Determines component role (`controller`, `service`, `repository`, `entity`, `test`) via Spring annotations (`@RestController`, `@Service`, `@Entity`, etc.).
2. **Phase 2 (Relationships & Routes):**
   - Parses constructor parameters to create `INJECTS` edges between Spring beans.
   - Parses HTTP mapping annotations (`@GetMapping`, `@PostMapping`, etc.) to create `ENDPOINT` nodes and `HANDLED_BY` edges.
   - Parses repository inheritance (`extends JpaRepository<Entity, ID>`) to create `MANAGES` edges to entities.

### 7.2 Query Capabilities
- `get_architecture_graph()`: Returns an aggregated architectural map (total endpoints, route mappings, service beans, repositories, entities, and tests).
- `query_code_graph(query_type, target)`:
  - `routes`: Filters endpoints by path pattern or HTTP verb.
  - `dependencies`: Lists outbound (`depends_on`) and inbound (`depended_by`) bean dependencies.
  - `symbol`: Finds exact file path, line number, return type, and method parameters.
  - `impact`: Uses `networkx.ancestors()` to compute the full upstream blast radius of modifying a target class.

---

## 8. Test Structure & Test Execution Mechanisms

### 8.1 Existing Test Suites
The `tests/` directory contains unit and integration tests executed using Python's standard `unittest` framework:
- `test_jira_tools.py`: Validates Atlassian Document Format (ADF) flattening, acceptance criteria regex extraction, and mock issue retrieval.
- `test_repository_tools.py`: Validates path escape prevention, protected file blocking, file read/write operations, and branch collision counting.
- `test_github_tools.py`: Validates repository slug parsing and dry-run Pull Request markdown generation.
- `test_codegraph_tools.py`: Validates in-memory AST graph creation, route discovery, bean dependency tracing, and blast radius calculation.
- `test_workflow.py`: End-to-end multi-tool mock execution simulating a full issue implementation cycle with diff review.
- `test_ponytail_mode.py`: Validates Ponytail Mode configuration, 5 core principles, system prompt incorporation, CLI arguments, and PR tool preservation.

### 8.2 Repository Test Execution Mechanism (`run_project_tests`)
`run_project_tests` verifies changes in the target workspace:
- **Build Tool Detection:** Searches for `pom.xml` (Maven), `build.gradle`/`build.gradle.kts` (Gradle), or `tests/` (Python `unittest`).
- **Execution:** Invokes `./mvnw -B test`, `./gradlew test`, or `python -m unittest discover -s tests`.
- **Timeout:** Enforces a 300-second execution limit (`COMMAND_TIMEOUT_SECONDS`).
- **Diagnostic Return:** Returns `tests_passed: bool`, `exit_code: int`, and `output_tail: str` (last 10,000 characters of stdout/stderr).
- **Mock Mode:** If `MOCK_TESTS=true` or `MOCK_MODE=true` AND build tools are not present on PATH, it returns simulated test results.
