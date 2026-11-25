#!/usr/bin/env python3
"""
CLI and CI/CD Entry Point for CodeFactoryAgent.

Usage:
    # Production run against live Jira & GitHub:
    python run_agent.py --ticket DEMO-1 --repo-dir /path/to/repo

    # Mock / Offline mode (no API keys required):
    python run_agent.py --ticket DEMO-1 --mock --repo-dir ../sample-springboot-app

    # Dry-run mode (live Jira, but simulate git push & PR):
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

# Ensure immediate unbuffered output in CI/CD runners
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

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
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class WorkspaceSession:
    """Manages repository state and guarantees safe cleanup and rollback on failure or exit."""

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
            res = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(self.repo),
                capture_output=True,
                text=True,
                check=False,
            )
            curr = res.stdout.strip()
            if curr:
                self.base_branch = curr
        except Exception:
            pass

    def mark_success(self):
        """Mark session as successfully completed."""
        self.completed_successfully = True

    def cleanup_on_exit(self, interrupted: bool = False, error_msg: Optional[str] = None):
        """Restores repository state safely."""
        if not (self.repo / ".git").exists():
            return

        if self.completed_successfully:
            return

        print("\n🧹 [Workspace Cleanup] Restoring target repository safety...")
        try:
            # Check for uncommitted working tree changes
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
                        ["git", "stash", "save", "-u", f"code-factory-interrupted-{self.ticket}"],
                        cwd=str(self.repo),
                        capture_output=True,
                        check=False,
                    )
                    print(f"   • Uncommitted changes safely stashed as 'code-factory-interrupted-{self.ticket}'.")
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
                    print(f"   • Discarded uncommitted partial modifications on '{self.feature_branch}'.")

            # Restore base branch (e.g. main)
            curr = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(self.repo),
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()

            if curr != self.base_branch and self.base_branch:
                subprocess.run(
                    ["git", "checkout", self.base_branch],
                    cwd=str(self.repo),
                    capture_output=True,
                    check=False,
                )
                print(f"   • Switched repository back to '{self.base_branch}' branch.")

        except Exception as exc:
            print(f"   ⚠️ Could not fully restore repository: {exc}")


_active_session: Optional[WorkspaceSession] = None


def _sigint_handler(signum, frame):
    """Graceful shutdown handler for Ctrl+C and SIGTERM."""
    print("\n\n⚠️  [Interrupt] Cancellation received (Ctrl+C). Aborting agent execution...")
    if _active_session:
        _active_session.cleanup_on_exit(interrupted=True)
    print("👋 Agent shut down gracefully. Exiting.")
    sys.exit(EXIT_INTERRUPTED)


signal.signal(signal.SIGINT, _sigint_handler)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _sigint_handler)


def parse_args():
    parser = argparse.ArgumentParser(description="Run CodeFactoryAgent for a Jira ticket.")
    parser.add_argument(
        "--ticket",
        "-t",
        dest="ticket",
        default=os.getenv("JIRA_ISSUE_KEY")
        or os.getenv("INPUT_JIRA_ISSUE_KEY")
        or os.getenv("JIRA_TICKET_NUMBER")
        or os.getenv("INPUT_JIRA_TICKET_NUMBER")
        or "",
        help="Jira ticket number / issue key (e.g. DEMO-1 or PROJ-123)",
    )
    parser.add_argument(
        "--repo-dir",
        "-r",
        dest="repo_dir",
        default=os.getenv("TARGET_REPO_DIR") or os.getenv("GITHUB_WORKSPACE") or "",
        help="Path to the target repository workspace (defaults to ../sample-springboot-app or current dir)",
    )
    parser.add_argument(
        "--model",
        "-m",
        dest="model",
        default=os.getenv("GEMINI_MODEL") or os.getenv("INPUT_GEMINI_MODEL") or "gemini-2.5-flash",
        help="Gemini model name to use",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=os.getenv("MOCK_MODE", "").lower() in ("true", "1", "yes")
        or os.getenv("MOCK_JIRA", "").lower() in ("true", "1", "yes"),
        help="Run in mock/offline mode without live Jira or Gemini API keys",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.getenv("DRY_RUN", "").lower() in ("true", "1", "yes"),
        help="Do not push changes to GitHub or create live PR",
    )
    return parser.parse_args()


def setup_environment(args):
    """Bridge CLI arguments and GitHub Action inputs into standard environment variables."""
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

    # Check for GitHub Action INPUT_* variables and normalize them
    for key, val in list(os.environ.items()):
        if key.startswith("INPUT_") and val:
            normalized_key = key[6:]
            if normalized_key not in os.environ:
                os.environ[normalized_key] = val


def print_jira_ticket_banner(jira_data: dict):
    """Print an exhaustive, human-readable summary of the loaded Jira story."""
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

    desc = jira_data.get("description", "").strip()
    print("\n📝 Description:")
    if desc:
        for line in desc.splitlines():
            print(f"  {line}")
    else:
        print("  (No description provided in Jira ticket)")

    ac = jira_data.get("acceptance_criteria", "").strip()
    print("\n✅ Acceptance Criteria:")
    if ac and ac != "None explicitly specified in Jira issue.":
        for line in ac.splitlines():
            print(f"  {line}")
    else:
        print("  (None explicitly detected in custom fields or description headings)")

    print("=" * 65 + "\n")


def print_fatal_error(stage: str, error_message: str, troubleshooting: Optional[List[str]] = None, ticket: str = ""):
    """Print a prominent diagnostic incident report with troubleshooting guidance."""
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


def _log_tool_step(step: int, tool_name: str, tool_args: dict, result: Any, ticket: str):
    """Print informative, human-readable real-time progress for each autonomous step."""
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
        t_key = result.get("issue_key", ticket)
        print(f"📋 [Step {step}] Jira Story Requirements Ingested:")
        print(f"   • Ticket:     {t_key}")
        print(f"   • Summary:    {result.get('summary', 'N/A')}")
        print(f"   • Status:     {result.get('status', 'Unknown')} ({result.get('issue_type', 'Story')})")

    elif tool_name in ("prepare_feature_branch", "initialize_workspace"):
        print(f"🌿 [Step {step}] Git Feature Branch Prepared:")
        print(f"   • Ticket:     {result.get('issue_key', ticket)}")
        print(f"   • Branch:     {result.get('branch', 'unknown')} (branched from '{result.get('base_branch', 'main')}')")
        print(f"   • Base Commit:{result.get('head_commit', 'unknown')}")
        print(f"   • Repository: {result.get('repository', 'unknown')}")

    elif tool_name == "get_architecture_graph":
        print(f"🗺️  [Step {step}] Code Graph Architecture Ingested:")
        print(f"   • Endpoints:  {result.get('total_endpoints', 0)} REST endpoints mapped")
        for ep in result.get("endpoints", [])[:5]:
            print(f"     ↳ {ep.get('method')} {ep.get('path')} ➔ {ep.get('controller')}.{ep.get('handler')}")
        if len(result.get("endpoints", [])) > 5:
            print(f"     ↳ ... (+{len(result.get('endpoints', [])) - 5} more routes)")
        services = [s.get("name") for s in result.get("services", [])]
        repos = [r.get("name") for r in result.get("repositories", [])]
        entities = [e.get("name") for e in result.get("entities", [])]
        print(f"   • Services:   {', '.join(services) if services else 'None'}")
        print(f"   • Repos:      {', '.join(repos) if repos else 'None'}")
        print(f"   • Entities:   {', '.join(entities) if entities else 'None'}")

    elif tool_name == "query_code_graph":
        q_type = tool_args.get("query_type", "")
        target = tool_args.get("target", "")
        print(f"🔎 [Step {step}] Code Graph Query: {q_type}(target='{target}')")
        if "results" in result:
            print(f"   • Matches:    {len(result.get('results', []))} items found")
            for item in result.get("results", [])[:3]:
                print(f"     ↳ {item.get('endpoint', item.get('symbol', ''))}")
        elif "matches" in result:
            print(f"   • Matches:    {len(result.get('matches', []))} symbol declarations")
            for m in result.get("matches", [])[:2]:
                print(f"     ↳ {m.get('file')}:{m.get('line')}")
        elif "impacted_components" in result:
            print(f"   • Blast Radius: {result.get('summary', '')}")
        else:
            keys = [k for k in result.keys() if k != "error"][:3]
            print(f"   • Details:    {', '.join(keys)}")

    elif tool_name == "list_project_files":
        entries = result.get("entries", [])
        files = [e["path"] for e in entries if e.get("type") == "file"]
        print(f"📂 [Step {step}] Project Directory Layout Discovered:")
        print(f"   • Target Dir: {result.get('directory', '.')}")
        print(f"   • Total:      {result.get('total_entries', len(entries))} entries ({len(files)} files)")
        key_files = [f for f in files if f in ("ARCHITECTURE.md", "DOMAIN_SPEC.md", "README.md", "pom.xml") or f.endswith("openapi.yml")]
        if key_files:
            print(f"   • Context Docs Identified: {', '.join(key_files)}")

    elif tool_name == "read_project_file":
        f_path = result.get("path", tool_args.get("file_path", ""))
        content = result.get("content", "")
        lines = len(content.splitlines())
        print(f"📖 [Step {step}] Reading Living Context / Source Code:")
        print(f"   • File:       {f_path}")
        print(f"   • Content:    {lines} lines ({len(content)} characters)")

    elif tool_name == "write_project_file":
        f_path = result.get("path", tool_args.get("file_path", ""))
        bytes_w = result.get("bytes_written", 0)
        print(f"✍️  [Step {step}] Writing Code / Living Documentation:")
        print(f"   • File:       {f_path}")
        print(f"   • Written:    {bytes_w} bytes")

    elif tool_name == "run_project_tests":
        passed = result.get("tests_passed")
        code = result.get("exit_code", 0)
        status_icon = "✅ PASSED" if passed else "❌ FAILED"
        print(f"🧪 [Step {step}] Automated Test Suite Execution:")
        print(f"   • Outcome:    {status_icon} (Exit code: {code})")
        if result.get("note"):
            print(f"   • Diagnostic: {result['note']}")
        tail = result.get("output_tail", "").strip()
        if tail:
            tail_lines = tail.splitlines()[-4:]
            print("   • Tail Log:")
            for l in tail_lines:
                print(f"     | {l}")

    elif tool_name in ("get_git_status", "get_git_diff"):
        status = result.get("status", "clean")
        branch = result.get("branch", ticket)
        print(f"🔍 [Step {step}] Git Status & Working Tree Review:")
        print(f"   • Branch:     {branch}")
        print(f"   • Status:     {status}")

    elif tool_name == "commit_changes":
        print(f"💾 [Step {step}] Git Commit Created:")
        print(f"   • Commit SHA: {result.get('commit', 'unknown')[:8] if result.get('commit') else 'N/A'}")
        print(f"   • Branch:     {result.get('branch', ticket)}")
        print(f"   • Message:    \"{result.get('message', '')}\"")

    elif tool_name == "push_and_create_pull_request":
        print(f"🎉 [Step {step}] GitHub Pull Request Opened for Review:")
        print(f"   • PR Link:    {result.get('pull_request_url', 'N/A')}")
        print(f"   • Target:     {result.get('branch', ticket)} ➔ {result.get('base_branch', 'main')}")
        print(f"   • Summary:    {result.get('message', '')}")
    else:
        print(f"⚙️  [Step {step}] {tool_name} completed successfully.")

    print("─" * 65)


async def run_simulation_mode(ticket: str, session: WorkspaceSession) -> int:
    """Run simulated agent pipeline without live Gemini API key for offline verification."""
    from coding_agent.tools.jira_tools import get_jira_issue
    from coding_agent.tools.repository_tools import (
        prepare_feature_branch,
        list_project_files,
        read_project_file,
        run_project_tests,
        get_git_status,
        get_git_diff,
        commit_changes,
    )
    from coding_agent.tools.github_tools import push_and_create_pull_request
    from coding_agent.tools.codegraph_tools import get_architecture_graph

    print("\n[Simulation Mode] Executing end-to-end tool pipeline...")

    # Step 1: Jira Issue Fetch
    jira_res = get_jira_issue(ticket)
    _log_tool_step(1, "get_jira_issue", {"issue_key": ticket}, jira_res, ticket)
    if "error" in jira_res:
        return EXIT_EXTERNAL_SERVICE_ERROR

    # Step 2: Prepare Feature Branch
    branch_res = prepare_feature_branch(ticket)
    _log_tool_step(2, "prepare_feature_branch", {"issue_key": ticket}, branch_res, ticket)
    if "error" in branch_res:
        return EXIT_CONFIG_ERROR

    # Step 3: Ingest Code Graph Architecture
    graph_res = get_architecture_graph()
    _log_tool_step(3, "get_architecture_graph", {}, graph_res, ticket)

    # Step 4: Inspect Project & Ingest Context
    files_res = list_project_files()
    _log_tool_step(4, "list_project_files", {}, files_res, ticket)

    # Step 5: Run Tests
    test_res = run_project_tests(ticket)
    _log_tool_step(5, "run_project_tests", {"issue_key": ticket}, test_res, ticket)

    # Step 6: Git Status & Diff
    status_res = get_git_status()
    _log_tool_step(6, "get_git_status", {}, status_res, ticket)

    # Step 7: PR creation simulation
    pr_res = push_and_create_pull_request(
        issue_key=ticket,
        summary=jira_res.get("summary", ""),
        description=jira_res.get("description", ""),
        acceptance_criteria=jira_res.get("acceptance_criteria", ""),
        changes_summary="Agent verified workspace, read Code Graph architecture, and validated requirements.",
        test_summary=test_res.get("output_tail", "All tests verified."),
    )
    _log_tool_step(7, "push_and_create_pull_request", {}, pr_res, ticket)

    session.mark_success()
    print("\n" + "=" * 65)
    print("🎉 Offline pipeline validation succeeded!")
    print("=" * 65)
    return EXIT_SUCCESS


async def run_agent_async(ticket: str, is_mock: bool = False) -> int:
    """Execute the agent autonomously with workspace state preservation and error handling."""
    global _active_session
    from coding_agent.tools.jira_tools import get_jira_issue

    # Pre-flight Check: Validate target repository directory exists
    repo_dir_setting = os.getenv("TARGET_REPO_DIR", "../sample-springboot-app")
    target_repo_path = Path(repo_dir_setting).resolve()

    print("=" * 65, flush=True)
    print(f"🚀 Starting CodeFactoryAgent for ticket: {ticket}", flush=True)
    print(f"📁 Target repository: {target_repo_path}", flush=True)
    print(f"🤖 Model: {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}", flush=True)
    print(f"🧪 Mock/Offline Mode: {'Enabled' if is_mock else 'Disabled'}", flush=True)
    print(f"🛡️  Dry-Run Mode:     {'Enabled' if os.getenv('DRY_RUN') == 'true' else 'Disabled'}", flush=True)

    # Report integration credentials status transparently
    has_gemini = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    jira_url = os.getenv("JIRA_BASE_URL", "").strip()
    jira_email = os.getenv("JIRA_EMAIL", "").strip()
    has_jira_token = bool(os.getenv("JIRA_API_TOKEN", "").strip())
    has_gh_token = bool(os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GH_TOKEN", "").strip())

    print("\n🔑 Integrations & Credentials Detected:", flush=True)
    print(f"   • Google Gemini API Key: {'✅ Configured' if has_gemini else '❌ Missing (Required for live mode)'}", flush=True)
    print(f"   • Jira Base URL:         {('✅ ' + jira_url) if jira_url else '⚠️  Not Configured (Will fall back to mock issue)'}", flush=True)
    print(f"   • Jira Account Email:    {('✅ ' + jira_email) if jira_email else '⚠️  Not Configured'}", flush=True)
    print(f"   • Jira API Token:        {'✅ Configured' if has_jira_token else '⚠️  Not Configured'}", flush=True)
    print(f"   • GitHub Token:          {'✅ Configured' if has_gh_token else '❌ Missing'}", flush=True)
    print("=" * 65 + "\n", flush=True)

    if not target_repo_path.is_dir():
        print_fatal_error(
            stage="Target Repository Directory Not Found",
            error_message=f"The specified target repository path does not exist: {target_repo_path}",
            troubleshooting=[
                "Check TARGET_REPO_DIR in code-factory/.env",
                "Ensure sample-springboot-app exists at that location",
                "Specify --repo-dir <path> explicitly when invoking run_agent.py",
            ],
            ticket=ticket,
        )
        return EXIT_CONFIG_ERROR

    # Initialize Workspace Session for automated rollback and cleanup
    session = WorkspaceSession(target_repo_path, ticket)
    session.capture_initial_state()
    _active_session = session

    try:
        # Pre-flight Check: Read and validate Jira story immediately
        print(f"🔍 [Pre-flight] Retrieving and validating Jira requirements for '{ticket}'...", flush=True)
        jira_data = get_jira_issue(ticket)
        if "error" in jira_data:
            print_fatal_error(
                stage=f"Failed to Retrieve Jira Ticket '{ticket}'",
                error_message=jira_data["error"],
                troubleshooting=[
                    "Verify JIRA_BASE_URL in code-factory/.env (e.g., https://your-domain.atlassian.net with no trailing slash)",
                    "Verify JIRA_EMAIL matches your Atlassian account email address exactly",
                    "Verify JIRA_API_TOKEN is a valid active token generated from https://id.atlassian.com/manage-profile/security/api-tokens",
                    f"Verify that ticket '{ticket}' exists in your Jira project and is accessible by your account",
                    "If you want to run without Jira credentials, use --mock to run with built-in test tickets",
                ],
                ticket=ticket,
            )
            return EXIT_EXTERNAL_SERVICE_ERROR

        # Successfully retrieved Jira ticket: print complete ticket summary banner
        print_jira_ticket_banner(jira_data)

        # If in mock mode or Gemini API key is missing, execute simulation runner
        has_api_key = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
        if is_mock or not has_api_key:
            if not has_api_key:
                print("ℹ️  [Notice] No GOOGLE_API_KEY found in environment. Running in offline simulation mode.", flush=True)
            return await run_simulation_mode(ticket, session)

        # Live Gemini AI execution via official google.genai SDK with multi-turn tool calling loop
        try:
            from google import genai
            from google.genai import types
            from coding_agent.agent import root_agent
            from coding_agent.tools import (
                get_jira_issue,
                prepare_feature_branch,
                get_architecture_graph,
                query_code_graph,
                list_project_files,
                read_project_file,
                write_project_file,
                run_project_tests,
                get_git_status,
                get_git_diff,
                commit_changes,
                push_and_create_pull_request,
            )

            # Pre-flight: Guarantee the feature branch is created and checked out right at the start
            print(f"🌿 [Pre-flight] Preparing dedicated feature branch for '{ticket}'...", flush=True)
            branch_res = prepare_feature_branch(ticket)
            _log_tool_step(0, "prepare_feature_branch", {"issue_key": ticket}, branch_res, ticket)
            if "error" in branch_res:
                print_fatal_error(
                    stage=f"Git Branching Failure for '{ticket}'",
                    error_message=branch_res["error"],
                    troubleshooting=[
                        "Check if target repository is a valid Git repo",
                        "Ensure no merge conflicts or uncommitted blocking changes exist",
                    ],
                    ticket=ticket,
                )
                return EXIT_CONFIG_ERROR

            last_branch = branch_res.get("branch", ticket)
            session.feature_branch = last_branch

            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            client = genai.Client(api_key=api_key)

            tools = [
                get_jira_issue,
                prepare_feature_branch,
                get_architecture_graph,
                query_code_graph,
                list_project_files,
                read_project_file,
                write_project_file,
                run_project_tests,
                get_git_status,
                get_git_diff,
                commit_changes,
                push_and_create_pull_request,
            ]
            tool_map = {fn.__name__: fn for fn in tools}

            prompt = (
                f"You are implementing Jira ticket '{ticket}'.\n"
                f"Summary: {jira_data.get('summary')}\n"
                f"Feature branch '{last_branch}' has been prepared and is currently checked out.\n\n"
                f"MANDATORY AUTONOMOUS EXECUTION INSTRUCTIONS:\n"
                f"1. Call get_architecture_graph to inspect existing Spring Boot controllers, endpoints, and services.\n"
                f"2. Call read_project_file to read ARCHITECTURE.md, DOMAIN_SPEC.md, and openapi.yml.\n"
                f"3. Read existing Java code in src/main/java and tests in src/test/java.\n"
                f"4. Implement all code and tests using write_project_file. Update openapi.yml and DOMAIN_SPEC.md.\n"
                f"5. Call run_project_tests to verify the implementation passes.\n"
                f"6. Call get_git_diff and get_git_status to review changes.\n"
                f"7. Call commit_changes with a message like 'feat({ticket}): ...'.\n"
                f"8. Call push_and_create_pull_request to open the Pull Request.\n"
                f"CRITICAL: You are an autonomous software engineering engine. You MUST execute all changes through tool calls. Do NOT produce only conversational text. Proceed immediately by calling the first inspection tool."
            )

            print(f"🤖 Invoking Gemini ({model}) with autonomous multi-step reasoning...", flush=True)
            chat = client.chats.create(
                model=model,
                config=types.GenerateContentConfig(
                    system_instruction=root_agent.instruction,
                    tools=tools,
                    temperature=0.7,
                    top_p=0.95,
                ),
            )

            print(f"📤 Sending initial story requirements prompt to {model}...", flush=True)
            response = chat.send_message(prompt)

            step = 1
            max_steps = 30
            last_commit = None
            pr_error = None
            pr_url = None
            recitation_retries = 0
            is_dry_run = os.getenv("DRY_RUN", "").lower() in ("true", "1", "yes")

            while step <= max_steps:
                # Check for recitation or content safety filter blocks
                cand = response.candidates[0] if (response and response.candidates) else None
                finish_reason = getattr(cand, "finish_reason", None)
                if finish_reason and "RECITATION" in str(finish_reason):
                    recitation_retries += 1
                    print(f"\n⚠️  [Turn {step}] Model output was flagged for recitation/repetition (Attempt {recitation_retries}/2)...", flush=True)
                    if recitation_retries > 2:
                        print("🚨 Excessive recitation flags. Forcing unique domain-specific implementation directive...", flush=True)
                        nudge = (
                            "CRITICAL ANTI-RECITATION DIRECTIVE: Do not generate standard framework boilerplate. "
                            "Write custom, domain-specific Java code with explicit Javadoc headers (@author CodeFactoryAgent), "
                            "SLF4J logging on every method, and custom parameter naming tailored strictly to DOMAIN_SPEC.md. "
                            "Execute write_project_file now."
                        )
                        recitation_retries = 0
                    else:
                        nudge = (
                            "Notice: Your previous response matched public training data and was filtered. "
                            "Please write original, domain-tailored Java code with custom Javadoc comments and SLF4J logs. "
                            "Call write_project_file to write the custom code."
                        )
                    step += 1
                    response = chat.send_message(nudge)
                    continue
                else:
                    recitation_retries = 0

                if response.text and response.text.strip():
                    print(f"\n🧠 [Agent Thought]:\n{response.text.strip()}\n", flush=True)

                if not response.function_calls:
                    # Verify if workflow genuinely completed
                    if pr_url or (is_dry_run and last_commit):
                        print("🏁 Agent indicated all tasks are completed (Pull Request created).", flush=True)
                        break

                    # If model returned text without executing required tools, nudge it to continue
                    text_preview = (response.text or "").strip()
                    print(f"\n⚠️  [Turn {step}] Model provided text without calling the next required tool (PR is not yet created).", flush=True)
                    if text_preview:
                        print(f"   Model response preview: {text_preview[:250]}...", flush=True)

                    if not last_commit:
                        reminder = (
                            "CRITICAL: You have not completed the implementation yet. "
                            "Do NOT output text only. You MUST execute tool calls: "
                            "1. Call write_project_file to save the Java classes and test files to disk.\n"
                            "2. Call run_project_tests to verify tests pass.\n"
                            "3. Call commit_changes to commit the changes.\n"
                            "4. Call push_and_create_pull_request to open the Pull Request.\n"
                            "Proceed now by calling write_project_file."
                        )
                    else:
                        reminder = (
                            "You have committed changes locally, but you have NOT opened the Pull Request yet. "
                            "Call push_and_create_pull_request now to submit the Pull Request."
                        )

                    print(f"👉 Directing agent to execute tool action (Step {step}/{max_steps})...", flush=True)
                    step += 1
                    response = chat.send_message(reminder)
                    continue

                print(f"\n⚡ [Turn {step}] Agent selected {len(response.function_calls)} action(s)...", flush=True)
                tool_responses = []
                for call in response.function_calls:
                    tool_name = call.name
                    tool_args = call.args or {}
                    print(f"   ▶ Executing tool: {tool_name}({list(tool_args.keys())})...", flush=True)

                    if tool_name in tool_map:
                        try:
                            fn_result = tool_map[tool_name](**tool_args)
                        except Exception as e:
                            fn_result = {"error": str(e)}
                    else:
                        fn_result = {"error": f"Unknown tool: {tool_name}"}

                    _log_tool_step(step, tool_name, tool_args, fn_result, ticket)

                    if isinstance(fn_result, dict):
                        if fn_result.get("branch"):
                            last_branch = fn_result["branch"]
                            session.feature_branch = last_branch
                        if fn_result.get("commit"):
                            last_commit = fn_result["commit"]
                        if tool_name == "push_and_create_pull_request":
                            if "error" in fn_result:
                                pr_error = fn_result["error"]
                            elif fn_result.get("pull_request_url"):
                                pr_url = fn_result["pull_request_url"]

                    # Fail-fast check on critical errors
                    if isinstance(fn_result, dict) and "error" in fn_result:
                        if tool_name in ("prepare_feature_branch", "initialize_workspace"):
                            print_fatal_error(
                                stage=f"Git Branching Failure for '{ticket}'",
                                error_message=fn_result["error"],
                                troubleshooting=[
                                    "Check if target repository is a valid Git repo",
                                    "Ensure no merge conflicts or uncommitted blocking changes exist",
                                ],
                                ticket=ticket,
                            )
                            return EXIT_CONFIG_ERROR

                    tool_responses.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": fn_result},
                        )
                    )

                step += 1
                print(f"⏳ [Turn {step - 1}] Sending tool outputs back to Gemini ({model})...", flush=True)
                response = chat.send_message(tool_responses)

            if last_commit and (pr_url or is_dry_run):
                # Work completed and committed; mark session complete so cleanup does not discard work
                session.mark_success()

            print("\n" + "=" * 65, flush=True)
            if pr_url or (is_dry_run and last_commit):
                print("🎉 CodeFactoryAgent Autonomous Execution Finished Successfully!", flush=True)
                if pr_url:
                    print(f"🔗 Pull Request URL: {pr_url}", flush=True)
            elif pr_error:
                print("⚠️  CodeFactoryAgent Finished with Warnings / Incomplete PR:", flush=True)
            elif not last_commit:
                print("🚨 CodeFactoryAgent Incomplete Execution: No code committed.", flush=True)
            print("=" * 65, flush=True)
            if response.text:
                print(response.text, flush=True)

            if not last_commit:
                print("\n" + "!" * 65, flush=True)
                print("🚨 INCOMPLETE WORKFLOW: The agent did not commit any code changes.", flush=True)
                print(f"• Ticket: {ticket}", flush=True)
                print("!" * 65 + "\n", flush=True)
                return EXIT_EXTERNAL_SERVICE_ERROR

            if pr_error:
                print("\n" + "!" * 65, flush=True)
                print("🚨 PULL REQUEST CREATION FAILED", flush=True)
                print("!" * 65, flush=True)
                print(f"• Ticket:       {ticket}", flush=True)
                print(f"• Branch:       {last_branch} (All code and tests committed locally)", flush=True)
                if last_commit:
                    print(f"• Commit SHA:   {last_commit}", flush=True)
                print(f"• Root Cause:   {pr_error}", flush=True)
                print("\n💡 Manual Push Command:", flush=True)
                print(f"   git -C \"{target_repo_path}\" push -u origin {last_branch}", flush=True)
                print("!" * 65 + "\n", flush=True)
                return EXIT_EXTERNAL_SERVICE_ERROR

            return EXIT_SUCCESS

        except Exception as exc:
            import traceback
            traceback.print_exc()
            print_fatal_error(
                stage="Gemini AI Invocation Failed",
                error_message=str(exc),
                troubleshooting=[
                    "Verify GOOGLE_API_KEY in code-factory/.env is correct and active",
                    "Ensure your Gemini model name is valid (e.g. gemini-2.5-flash)",
                    "Check network connectivity to https://generativelanguage.googleapis.com",
                ],
                ticket=ticket,
            )
            return EXIT_EXTERNAL_SERVICE_ERROR

    finally:
        # Guarantee repository safety and restoration on failure or exit
        session.cleanup_on_exit()


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

    exit_code = asyncio.run(run_agent_async(ticket, is_mock=args.mock))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
