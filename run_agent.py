
#!/usr/bin/env python3
"""
CLI and CI/CD Entry Point for CodeFactoryAgent.

Usage:
    # Production run against live Jira & GitHub:
    python run_agent.py --ticket DEMO-1 --repo-dir /path/to/repo

    # Mock / Offline mode:
    python run_agent.py --ticket DEMO-1 --mock --repo-dir ../sample-springboot-app

    # Dry-run mode:
    python run_agent.py --ticket DEMO-1 --dry-run
"""

import os
import sys
import signal
import argparse
import asyncio
import subprocess
from typing import Any, Optional, List
from pathlib import Path


# Semantic Exit Codes
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1
EXIT_EXTERNAL_SERVICE_ERROR = 2
EXIT_VERIFICATION_ERROR = 3
EXIT_INTERRUPTED = 130


# Ensure the agent root is in sys.path
AGENT_ROOT = Path(__file__).resolve().parent
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))


# Load .env if present
try:
    from dotenv import load_dotenv

    load_dotenv(AGENT_ROOT / ".env")
except ImportError:
    env_file = AGENT_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(
                    key.strip(),
                    value.strip().strip('"').strip("'"),
                )


class WorkspaceSession:
    """Manages repository state and guarantees safe cleanup on failure or exit."""

    def __init__(self, repo_dir: Path, ticket: str):
        self.repo = repo_dir
        self.ticket = ticket
        self.base_branch = "main"
        self.feature_branch = ticket
        self.completed_successfully = False

    def capture_initial_state(self):
        """Record the active branch before making any changes."""
        if not (self.repo / ".git").exists():
            return

        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(self.repo),
                capture_output=True,
                text=True,
                check=False,
            )
            current = result.stdout.strip()
            if current:
                self.base_branch = current
        except Exception:
            pass

    def mark_success(self):
        """Mark session as successfully completed."""
        self.completed_successfully = True

    def cleanup_on_exit(
        self,
        interrupted: bool = False,
        error_msg: Optional[str] = None,
    ):
        """Restore repository state safely."""
        if not (self.repo / ".git").exists():
            return

        if self.completed_successfully:
            return

        print("\n🧹 [Workspace Cleanup] Restoring target repository safety...")

        try:
            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(self.repo),
                capture_output=True,
                text=True,
                check=False,
            )
            is_dirty = bool(status.stdout.strip())

            if is_dirty:
                if interrupted:
                    subprocess.run(
                        [
                            "git",
                            "stash",
                            "save",
                            "-u",
                            f"code-factory-interrupted-{self.ticket}",
                        ],
                        cwd=str(self.repo),
                        capture_output=True,
                        check=False,
                    )
                    print(
                        "   • Uncommitted changes safely stashed as "
                        f"'code-factory-interrupted-{self.ticket}'."
                    )
                else:
                    subprocess.run(
                        ["git", "reset", "--hard", "HEAD"],
                        cwd=str(self.repo),
                        capture_output=True,
                        check=False,
                    )
                    subprocess.run(
                        ["git", "clean", "-fd"],
                        cwd=str(self.repo),
                        capture_output=True,
                        check=False,
                    )
                    print(
                        f"   • Discarded uncommitted partial modifications "
                        f"on '{self.feature_branch}'."
                    )

            current = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(self.repo),
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()

            if current != self.base_branch and self.base_branch:
                subprocess.run(
                    ["git", "checkout", self.base_branch],
                    cwd=str(self.repo),
                    capture_output=True,
                    check=False,
                )
                print(
                    f"   • Switched repository back to "
                    f"'{self.base_branch}' branch."
                )

        except Exception as exc:
            print(f"   ⚠️ Could not fully restore repository: {exc}")


_active_session: Optional[WorkspaceSession] = None


def _sigint_handler(signum, frame):
    """Graceful shutdown handler for Ctrl+C and SIGTERM."""
    print(
        "\n\n⚠️  [Interrupt] Cancellation received "
        "(Ctrl+C). Aborting agent execution..."
    )

    if _active_session:
        _active_session.cleanup_on_exit(interrupted=True)

    print("👋 Agent shut down gracefully. Exiting.")
    sys.exit(EXIT_INTERRUPTED)


signal.signal(signal.SIGINT, _sigint_handler)

if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _sigint_handler)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run CodeFactoryAgent for a Jira ticket."
    )

    parser.add_argument(
        "--ticket",
        "-t",
        dest="ticket",
        default=(
            os.getenv("JIRA_ISSUE_KEY")
            or os.getenv("INPUT_JIRA_ISSUE_KEY")
            or os.getenv("JIRA_TICKET_NUMBER")
            or os.getenv("INPUT_JIRA_TICKET_NUMBER")
            or ""
        ),
        help="Jira ticket number / issue key (e.g. DEMO-1 or PROJ-123)",
    )

    parser.add_argument(
        "--repo-dir",
        "-r",
        dest="repo_dir",
        default=os.getenv("TARGET_REPO_DIR") or os.getenv("GITHUB_WORKSPACE") or "",
        help="Path to the target repository workspace",
    )

    parser.add_argument(
        "--model",
        "-m",
        dest="model",
        default=(
            os.getenv("GEMINI_MODEL")
            or os.getenv("INPUT_GEMINI_MODEL")
            or "gemini-2.5-flash"
        ),
        help="Gemini model name to use",
    )

    parser.add_argument(
        "--mock",
        action="store_true",
        default=(
            os.getenv("MOCK_MODE", "").lower() in ("true", "1", "yes")
            or os.getenv("MOCK_JIRA", "").lower() in ("true", "1", "yes")
        ),
        help="Run in mock/offline mode without live Jira or Gemini API keys",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.getenv("DRY_RUN", "").lower() in ("true", "1", "yes"),
        help="Do not push changes to GitHub or create a live PR",
    )

    return parser.parse_args()


def setup_environment(args):
    """Bridge CLI arguments and GitHub Action inputs into environment variables."""
    if args.ticket:
        os.environ["JIRA_ISSUE_KEY"] = args.ticket

    if args.repo_dir:
        os.environ["TARGET_REPO_DIR"] = str(Path(args.repo_dir).resolve())

    if args.model:
        os.environ["GEMINI_MODEL"] = args.model

    if args.mock:
        os.environ["MOCK_MODE"] = "true"
        os.environ["MOCK_JIRA"] = "true"
        os.environ["MOCK_TESTS"] = "true"
        os.environ["MOCK_GITHUB"] = "true"
        os.environ["DRY_RUN"] = "true"

    if args.dry_run:
        os.environ["DRY_RUN"] = "true"

    # Normalize GitHub Action INPUT_* variables.
    for key, value in list(os.environ.items()):
        if key.startswith("INPUT_") and value:
            normalized_key = key[6:]
            if normalized_key not in os.environ:
                os.environ[normalized_key] = value


def print_jira_ticket_banner(jira_data: dict):
    """Print a human-readable summary of the loaded Jira story."""
    ticket = jira_data.get("issue_key", "UNKNOWN")

    print("\n" + "=" * 65)
    print(f"📋 JIRA TICKET DETAILS: {ticket}")
    print("=" * 65)

    print(f"• Summary:     {jira_data.get('summary', 'N/A')}")
    print(f"• Issue Type:  {jira_data.get('issue_type', 'Story')}")
    print(f"• Priority:    {jira_data.get('priority', 'Normal')}")
    print(f"• Status:      {jira_data.get('status', 'Unknown')}")

    if jira_data.get("issue_url"):
        print(f"• Jira URL:    {jira_data.get('issue_url')}")

    description = jira_data.get("description", "").strip()

    print("\n📝 Description:")
    if description:
        for line in description.splitlines():
            print(f"  {line}")
    else:
        print("  (No description provided in Jira ticket)")

    acceptance_criteria = jira_data.get("acceptance_criteria", "").strip()

    print("\n✅ Acceptance Criteria:")
    if (
        acceptance_criteria
        and acceptance_criteria != "None explicitly specified in Jira issue."
    ):
        for line in acceptance_criteria.splitlines():
            print(f"  {line}")
    else:
        print(
            "  (None explicitly detected in custom fields "
            "or description headings)"
        )

    print("=" * 65 + "\n")


def print_fatal_error(
    stage: str,
    error_message: str,
    troubleshooting: Optional[List[str]] = None,
    ticket: str = "",
):
    """Print a diagnostic incident report."""
    print("\n" + "!" * 65)
    print(f"🚨 AGENT INCIDENT REPORT: {stage}")
    print("!" * 65)

    if ticket:
        print(f"• Ticket:       {ticket}")

    print(f"• Root Cause:   {error_message}\n")

    if troubleshooting:
        print("💡 Suggested Troubleshooting Actions:")
        for item in troubleshooting:
            print(f"   • {item}")

    print("!" * 65 + "\n")


def _log_tool_step(
    step: int,
    tool_name: str,
    tool_args: dict,
    result: Any,
    ticket: str,
):
    """Print informative progress for each autonomous step."""
    print("\n" + "─" * 65)

    if not isinstance(result, dict):
        print(f"⚙️  [Step {step}] {tool_name} completed.")
        print("─" * 65)
        return

    if "error" in result:
        print(f"❌ [Step {step}] {tool_name} reported an issue:")
        print(f"   • Error: {result['error']}")
        print("─" * 65)
        return

    if tool_name in ("get_jira_issue", "get_configured_jira_issue"):
        print("📋 [Step {}] Jira Story Requirements Ingested:".format(step))
        print(f"   • Ticket:     {result.get('issue_key', ticket)}")
        print(f"   • Summary:    {result.get('summary', 'N/A')}")
        print(
            f"   • Status:     {result.get('status', 'Unknown')} "
            f"({result.get('issue_type', 'Story')})"
        )

    elif tool_name in ("prepare_feature_branch", "initialize_workspace"):
        print(f"🌿 [Step {step}] Git Feature Branch Prepared:")
        print(f"   • Ticket:     {result.get('issue_key', ticket)}")
        print(
            f"   • Branch:     {result.get('branch', 'unknown')} "
            f"(branched from '{result.get('base_branch', 'main')}')"
        )
        print(f"   • Base Commit: {result.get('head_commit', 'unknown')}")
        print(f"   • Repository: {result.get('repository', 'unknown')}")

    elif tool_name == "list_project_files":
        entries = result.get("entries", [])
        files = [entry["path"] for entry in entries if entry.get("type") == "file"]

        print(f"📂 [Step {step}] Project Directory Layout Discovered:")
        print(f"   • Target Dir: {result.get('directory', '.')}")
        print(
            f"   • Total:      {result.get('total_entries', len(entries))} "
            f"entries ({len(files)} files)"
        )

        key_files = [
            file_path
            for file_path in files
            if file_path in (
                "ARCHITECTURE.md",
                "DOMAIN_SPEC.md",
                "README.md",
                "pom.xml",
            )
            or file_path.endswith("openapi.yml")
        ]

        if key_files:
            print(
                f"   • Context Docs Identified: {', '.join(key_files)}"
            )

    elif tool_name == "read_project_file":
        file_path = result.get("path", tool_args.get("file_path", ""))
        content = result.get("content", "")

        print(f"📖 [Step {step}] Reading Living Context / Source Code:")
        print(f"   • File:       {file_path}")
        print(
            f"   • Content:    {len(content.splitlines())} lines "
            f"({len(content)} characters)"
        )

    elif tool_name == "write_project_file":
        file_path = result.get("path", tool_args.get("file_path", ""))
        bytes_written = result.get("bytes_written", 0)

        print(f"✍️  [Step {step}] Writing Code / Living Documentation:")
        print(f"   • File:       {file_path}")
        print(f"   • Written:    {bytes_written} bytes")

    elif tool_name == "run_project_tests":
        passed = result.get("tests_passed")
        exit_code = result.get("exit_code", 0)
        status_icon = "✅ PASSED" if passed else "❌ FAILED"

        print(f"🧪 [Step {step}] Automated Test Suite Execution:")
        print(f"   • Outcome:    {status_icon} (Exit code: {exit_code})")

        if result.get("note"):
            print(f"   • Diagnostic: {result['note']}")

        tail = result.get("output_tail", "").strip()
        if tail:
            print("   • Tail Log:")
            for line in tail.splitlines()[-4:]:
                print(f"     | {line}")

    elif tool_name in ("get_git_status", "get_git_diff"):
        print(f"🔍 [Step {step}] Git Status & Working Tree Review:")
        print(f"   • Branch:     {result.get('branch', ticket)}")
        print(f"   • Status:     {result.get('status', 'clean')}")

    elif tool_name == "commit_changes":
        commit = result.get("commit")

        print(f"💾 [Step {step}] Git Commit Created:")
        print(f"   • Commit SHA: {commit[:8] if commit else 'N/A'}")
        print(f"   • Branch:     {result.get('branch', ticket)}")
        print(f"   • Message:    \"{result.get('message', '')}\"")

    elif tool_name == "push_and_create_pull_request":
        print(f"🎉 [Step {step}] GitHub Pull Request Opened for Review:")
        print(f"   • PR Link:    {result.get('pull_request_url', 'N/A')}")
        print(
            f"   • Target:     {result.get('branch', ticket)} "
            f"➔ {result.get('base_branch', 'main')}"
        )
        print(f"   • Summary:    {result.get('message', '')}")

    elif tool_name == "search_symbols":
        print(f"🔍 [Step {step}] CodeGraph Symbol Search:")
        print(f"   • Query:      {tool_args.get('query')}")
        print(
            f"   • Matches:    "
            f"{result.get('total_matches', len(result.get('symbols', [])))}"
        )

    elif tool_name == "get_symbol_definition":
        print(f"📖 [Step {step}] CodeGraph Symbol Definition:")
        print(
            f"   • Symbol:     "
            f"{result.get('name', tool_args.get('symbol_name'))}"
        )
        print(f"   • File:       {result.get('file_path', 'N/A')}")

    elif tool_name == "find_callers_and_callees":
        print(f"🕸️  [Step {step}] CodeGraph Call Graph Traversal:")
        print(
            f"   • Symbol:     "
            f"{result.get('symbol', tool_args.get('symbol_name'))}"
        )
        print(
            f"   • Inbound:    "
            f"{len(result.get('callers_inbound', []))} callers"
        )
        print(
            f"   • Outbound:   "
            f"{len(result.get('callees_outbound', []))} callees"
        )

    elif tool_name == "get_dependency_context":
        print(f"📦 [Step {step}] CodeGraph Bounded Context Package:")
        print(
            f"   • Symbol:     "
            f"{result.get('name', tool_args.get('symbol_name'))}"
        )
        print(
            f"   • Tests:      "
            f"{len(result.get('related_tests', []))} related tests"
        )

    elif tool_name == "get_code_graph_summary":
        print(f"🗺️  [Step {step}] CodeGraph Architectural Summary:")
        print(f"   • Files:      {result.get('files_count', 0)} files")
        print(f"   • Symbols:    {result.get('symbols_count', 0)} symbols")

    else:
        print(f"⚙️  [Step {step}] {tool_name} completed successfully.")

    print("─" * 65)


def _initialize_codegraph(target_repo_path: Path):
    """
    Initialize and index CodeGraph when enabled and the parser is available.

    CodeGraph is optional: initialization failure must not prevent the
    agent from continuing with its normal repository tools.
    """
    from coding_agent.services.codegraph_service import CodeGraphService

    if not CodeGraphService.is_enabled():
        print("ℹ️  [CodeGraph] Disabled by CODEGRAPH_ENABLED.")
        return None

    if not CodeGraphService.is_parser_available():
        print(
            "⚠️  [CodeGraph] Tree-sitter Java parser unavailable. "
            "Continuing without CodeGraph indexing."
        )
        return None

    try:
        print("🧠 [Pre-flight] Initializing CodeGraph repository intelligence...")

        service = CodeGraphService.get_instance(target_repo_path)
        result = service.ensure_indexed()

        if result.get("status") == "success":
            print(
                f"   • CodeGraph indexed "
                f"{result.get('indexed_files', 0)} files in repository."
            )
        else:
            print(
                f"⚠️  [CodeGraph] Indexing returned status: "
                f"{result.get('status', 'unknown')}"
            )

        return service

    except Exception as exc:
        print(f"⚠️  [CodeGraph] Initialization failed: {exc}")
        print("   • Continuing with the standard repository tools.")
        return None


async def run_simulation_mode(
    ticket: str,
    session: WorkspaceSession,
) -> int:
    """Run simulated agent pipeline without a live Gemini API key."""
    from coding_agent.tools.jira_tools import get_jira_issue
    from coding_agent.tools.repository_tools import (
        prepare_feature_branch,
        list_project_files,
        run_project_tests,
        get_git_status,
    )
    from coding_agent.tools.github_tools import push_and_create_pull_request
    from coding_agent.tools.codegraph_tools import get_code_graph_summary

    print("\n[Simulation Mode] Executing end-to-end tool pipeline...")

    # Step 1: Jira Issue Fetch
    jira_result = get_jira_issue(ticket)
    _log_tool_step(
        1,
        "get_jira_issue",
        {"issue_key": ticket},
        jira_result,
        ticket,
    )

    if "error" in jira_result:
        return EXIT_EXTERNAL_SERVICE_ERROR

    # Step 2: Prepare Feature Branch
    branch_result = prepare_feature_branch(ticket)
    _log_tool_step(
        2,
        "prepare_feature_branch",
        {"issue_key": ticket},
        branch_result,
        ticket,
    )

    if "error" in branch_result:
        return EXIT_CONFIG_ERROR

    # Step 3: Initialize and summarize CodeGraph
    _initialize_codegraph(session.repo)

    graph_result = get_code_graph_summary()
    _log_tool_step(
        3,
        "get_code_graph_summary",
        {},
        graph_result,
        ticket,
    )

    # Step 4: Inspect project
    files_result = list_project_files()
    _log_tool_step(
        4,
        "list_project_files",
        {},
        files_result,
        ticket,
    )

    # Step 5: Run tests
    test_result = run_project_tests(ticket)
    _log_tool_step(
        5,
        "run_project_tests",
        {"issue_key": ticket},
        test_result,
        ticket,
    )

    # Step 6: Git status
    status_result = get_git_status()
    _log_tool_step(
        6,
        "get_git_status",
        {},
        status_result,
        ticket,
    )

    # Step 7: PR creation simulation
    pr_result = push_and_create_pull_request(
        issue_key=ticket,
        summary=jira_result.get("summary", ""),
        description=jira_result.get("description", ""),
        acceptance_criteria=jira_result.get("acceptance_criteria", ""),
        changes_summary=(
            "Agent verified workspace, inspected CodeGraph summary, "
            "and validated requirements."
        ),
        test_summary=test_result.get(
            "output_tail",
            "All tests verified.",
        ),
    )

    _log_tool_step(
        7,
        "push_and_create_pull_request",
        {},
        pr_result,
        ticket,
    )

    if isinstance(pr_result, dict) and "error" in pr_result:
        return EXIT_EXTERNAL_SERVICE_ERROR

    session.mark_success()

    print("\n" + "=" * 65)
    print("🎉 Offline pipeline validation succeeded!")
    print("=" * 65)

    return EXIT_SUCCESS


async def run_agent_async(
    ticket: str,
    is_mock: bool = False,
) -> int:
    """Execute the agent with workspace safety and error handling."""
    global _active_session

    from coding_agent.tools.jira_tools import get_jira_issue

    print("=" * 65)
    print(f"🚀 Starting CodeFactoryAgent for ticket: {ticket}")
    print(
        f"📁 Target repository: "
        f"{os.getenv('TARGET_REPO_DIR', 'Default')}"
    )
    print(
        f"🤖 Model: "
        f"{os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}"
    )
    print(
        f"🧪 Mock/Offline Mode: "
        f"{'Enabled' if is_mock else 'Disabled'}"
    )
    print("=" * 65)

    # Validate target repository directory.
    repo_dir_setting = os.getenv(
        "TARGET_REPO_DIR",
        "../sample-springboot-app",
    )
    target_repo_path = Path(repo_dir_setting).resolve()

    if not target_repo_path.is_dir():
        print_fatal_error(
            stage="Target Repository Directory Not Found",
            error_message=(
                "The specified target repository path does not exist: "
                f"{target_repo_path}"
            ),
            troubleshooting=[
                "Check TARGET_REPO_DIR in code-factory/.env",
                "Ensure the target repository exists at that location",
                "Specify --repo-dir <path> explicitly when invoking run_agent.py",
            ],
            ticket=ticket,
        )
        return EXIT_CONFIG_ERROR

    # Initialize workspace session.
    session = WorkspaceSession(target_repo_path, ticket)
    session.capture_initial_state()
    _active_session = session

    try:
        # Pre-flight: retrieve and validate Jira requirements.
        print(
            f"🔍 [Pre-flight] Retrieving and validating Jira "
            f"requirements for '{ticket}'..."
        )

        jira_data = get_jira_issue(ticket)

        if "error" in jira_data:
            print_fatal_error(
                stage=f"Failed to Retrieve Jira Ticket '{ticket}'",
                error_message=jira_data["error"],
                troubleshooting=[
                    "Verify JIRA_BASE_URL in code-factory/.env",
                    "Verify JIRA_EMAIL matches your Atlassian account email",
                    "Verify JIRA_API_TOKEN is valid and active",
                    f"Verify that ticket '{ticket}' exists and is accessible",
                    "Use --mock to run with built-in test tickets",
                ],
                ticket=ticket,
            )
            return EXIT_EXTERNAL_SERVICE_ERROR

        print_jira_ticket_banner(jira_data)

        # If mock mode or Gemini API key is missing, use simulation.
        has_api_key = bool(
            os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )

        if is_mock or not has_api_key:
            if not has_api_key:
                print(
                    "ℹ️  [Notice] No GOOGLE_API_KEY found in environment. "
                    "Running in offline simulation mode."
                )

            return await run_simulation_mode(ticket, session)

        # Initialize optional CodeGraph service.
        _initialize_codegraph(target_repo_path)

        # Live Gemini execution.
        try:
            from google import genai
            from google.genai import types

            from coding_agent.agent import root_agent

            from coding_agent.tools import (
                get_jira_issue,
                prepare_feature_branch,
                list_project_files,
                read_project_file,
                write_project_file,
                run_project_tests,
                get_git_status,
                get_git_diff,
                commit_changes,
                push_and_create_pull_request,
                search_symbols,
                get_symbol_definition,
                find_callers_and_callees,
                get_dependency_context,
                get_code_graph_summary,
            )

            api_key = (
                os.getenv("GOOGLE_API_KEY")
                or os.getenv("GEMINI_API_KEY")
            )
            model = os.getenv(
                "GEMINI_MODEL",
                "gemini-2.5-flash",
            )

            client = genai.Client(api_key=api_key)

            # All tools exposed to Gemini.
            tools = [
                get_jira_issue,
                prepare_feature_branch,
                list_project_files,
                read_project_file,
                write_project_file,
                run_project_tests,
                get_git_status,
                get_git_diff,
                commit_changes,
                push_and_create_pull_request,
                search_symbols,
                get_symbol_definition,
                find_callers_and_callees,
                get_dependency_context,
                get_code_graph_summary,
            ]

            tool_map = {
                function.__name__: function
                for function in tools
            }

            prompt = (
                f"Please implement the requirements and acceptance "
                f"criteria for Jira ticket '{ticket}'.\n"
                f"Ticket summary: {jira_data.get('summary')}\n\n"
                f"Workflow instructions:\n"
                f"1. Call prepare_feature_branch with "
                f"issue_key='{ticket}' to create or switch to the feature branch.\n"
                f"2. Read living documentation "
                f"(ARCHITECTURE.md, DOMAIN_SPEC.md, openapi.yml) "
                f"using read_project_file if present.\n"
                f"3. MANDATORY CODEGRAPH CODE EXPLORATION: "
                f"Before writing code or reading whole source files, "
                f"use CodeGraph when available:\n"
                f"   - Call search_symbols with relevant keywords "
                f"to locate domain entities, services, and repositories.\n"
                f"   - Call get_symbol_definition to inspect signatures, "
                f"annotations, and source snippets.\n"
                f"   - Call find_callers_and_callees or "
                f"get_dependency_context to understand dependencies "
                f"and interactions.\n"
                f"   - Call get_code_graph_summary to understand "
                f"the overall project structure.\n"
                f"   - If CodeGraph is disabled or unavailable, "
                f"continue using the repository file tools.\n"
                f"4. Implement all required changes using "
                f"write_project_file, including code, migrations, "
                f"tests, and API documentation where applicable.\n"
                f"5. Call run_project_tests to verify the implementation.\n"
                f"6. Call get_git_diff and get_git_status to review changes.\n"
                f"7. Call commit_changes with a message like "
                f"'feat({ticket}): ...'.\n"
                f"8. Call push_and_create_pull_request to submit "
                f"the Pull Request for human review.\n"
                f"9. Output your final summary."
            )

            print(
                f"🤖 Invoking Gemini ({model}) "
                f"with autonomous multi-step reasoning..."
            )

            chat = client.chats.create(
                model=model,
                config=types.GenerateContentConfig(
                    system_instruction=root_agent.instruction,
                    tools=tools,
                ),
            )

            # Token tracking across all Gemini responses.
            total_prompt_tokens = 0
            total_candidate_tokens = 0

            def track_usage(response, turn_label: str):
                """Accumulate token usage reported by Gemini."""
                nonlocal total_prompt_tokens
                nonlocal total_candidate_tokens

                usage = getattr(response, "usage_metadata", None)

                if not usage:
                    return

                prompt_tokens = (
                    getattr(usage, "prompt_token_count", 0) or 0
                )
                candidate_tokens = (
                    getattr(usage, "candidates_token_count", 0) or 0
                )

                total_prompt_tokens += prompt_tokens
                total_candidate_tokens += candidate_tokens

                print(
                    f"📊 [{turn_label}] "
                    f"Prompt Tokens: {prompt_tokens} | "
                    f"Output Tokens: {candidate_tokens} | "
                    f"Cumulative Total: "
                    f"{total_prompt_tokens + total_candidate_tokens}"
                )

            # Initial Gemini turn.
            response = chat.send_message(prompt)
            track_usage(response, "Initial Turn")

            step = 1
            max_steps = 30

            last_branch = ticket
            last_commit = None
            pr_error = None
            pr_url = None

            # Multi-turn function-calling loop.
            while response.function_calls and step <= max_steps:
                tool_responses = []

                for call in response.function_calls:
                    tool_name = call.name
                    tool_args = call.args or {}

                    if tool_name in tool_map:
                        try:
                            function_result = tool_map[tool_name](
                                **tool_args
                            )
                        except Exception as exc:
                            function_result = {"error": str(exc)}
                    else:
                        function_result = {
                            "error": f"Unknown tool: {tool_name}"
                        }

                    _log_tool_step(
                        step,
                        tool_name,
                        tool_args,
                        function_result,
                        ticket,
                    )

                    if isinstance(function_result, dict):
                        if function_result.get("branch"):
                            last_branch = function_result["branch"]
                            session.feature_branch = last_branch

                        if function_result.get("commit"):
                            last_commit = function_result["commit"]

                        if tool_name == "push_and_create_pull_request":
                            if "error" in function_result:
                                pr_error = function_result["error"]
                            elif function_result.get("pull_request_url"):
                                pr_url = function_result["pull_request_url"]

                    # Fail fast on critical branch creation failures.
                    if (
                        isinstance(function_result, dict)
                        and "error" in function_result
                        and tool_name in (
                            "prepare_feature_branch",
                            "initialize_workspace",
                        )
                    ):
                        print_fatal_error(
                            stage=f"Git Branching Failure for '{ticket}'",
                            error_message=function_result["error"],
                            troubleshooting=[
                                "Check if target repository is a valid Git repo",
                                "Ensure no merge conflicts or blocking changes exist",
                            ],
                            ticket=ticket,
                        )
                        return EXIT_CONFIG_ERROR

                    tool_responses.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": function_result},
                        )
                    )

                step += 1

                # Send tool results back to Gemini and track this response.
                response = chat.send_message(tool_responses)
                track_usage(response, f"Turn {step} Response")

            if response.function_calls and step > max_steps:
                print(
                    f"⚠️  Maximum tool execution limit "
                    f"({max_steps}) reached."
                )

            # A local commit means the generated work should be preserved.
            if last_commit:
                session.mark_success()

            print("\n" + "=" * 65)

            if pr_error:
                print(
                    "⚠️  CodeFactoryAgent Finished with Warnings / "
                    "Incomplete PR:"
                )
            else:
                print(
                    "🎉 CodeFactoryAgent Autonomous Execution "
                    "Finished Successfully!"
                )

            print("=" * 65)

            if response.text:
                print(response.text)

            # Token usage summary.
            print("\n📊 Gemini Token Usage Summary")
            print(f"   • Prompt tokens:     {total_prompt_tokens}")
            print(f"   • Output tokens:     {total_candidate_tokens}")
            print(
                f"   • Total tokens:      "
                f"{total_prompt_tokens + total_candidate_tokens}"
            )

            if not total_prompt_tokens and not total_candidate_tokens:
                print(
                    "   • Usage metadata was not available "
                    "from the provider responses."
                )

            if pr_url:
                print(f"\n🔗 Pull Request: {pr_url}")

            if pr_error:
                print("\n" + "!" * 65)
                print("🚨 PULL REQUEST CREATION FAILED")
                print("!" * 65)
                print(f"• Ticket:       {ticket}")
                print(
                    f"• Branch:       {last_branch} "
                    "(All code and tests committed locally)"
                )

                if last_commit:
                    print(f"• Commit SHA:   {last_commit}")

                print(f"• Root Cause:   {pr_error}")
                print("\n💡 Manual Push Command:")
                print(
                    f"   git -C \"{target_repo_path}\" "
                    f"push -u origin {last_branch}"
                )
                print("!" * 65 + "\n")

                return EXIT_EXTERNAL_SERVICE_ERROR

            return EXIT_SUCCESS

        except Exception as exc:
            print_fatal_error(
                stage="Gemini AI Invocation Failed",
                error_message=str(exc),
                troubleshooting=[
                    "Verify GOOGLE_API_KEY in code-factory/.env is correct and active",
                    "Ensure your Gemini model name is valid",
                    "Check network connectivity to the Gemini API",
                ],
                ticket=ticket,
            )
            return EXIT_EXTERNAL_SERVICE_ERROR

    finally:
        # Guarantee repository safety and restoration on failure or exit.
        session.cleanup_on_exit()
        _active_session = None


def main():
    args = parse_args()
    setup_environment(args)

    ticket = os.getenv("JIRA_ISSUE_KEY", "").strip()

    if not ticket:
        if args.mock:
            ticket = "DEMO-1"
            os.environ["JIRA_ISSUE_KEY"] = ticket
        else:
            print_fatal_error(
                stage="Missing Ticket Key",
                error_message="No Jira ticket key provided.",
                troubleshooting=[
                    "Pass --ticket <KEY> (e.g. python run_agent.py --ticket KAN-4)",
                    "Or set JIRA_ISSUE_KEY in code-factory/.env",
                ],
            )
            sys.exit(EXIT_CONFIG_ERROR)

    exit_code = asyncio.run(
        run_agent_async(ticket, is_mock=args.mock)
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
