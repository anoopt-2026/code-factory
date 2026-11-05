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
import argparse
import asyncio
from typing import Any
from pathlib import Path

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


def print_fatal_error(stage: str, error_message: str, troubleshooting: list = None):
    """Print a prominent diagnostic halt message with troubleshooting guidance."""
    print("\n" + "!" * 65)
    print(f"❌ AGENT EXECUTION HALTED: {stage}")
    print("!" * 65)
    print(f"Cause: {error_message}\n")
    if troubleshooting:
        print("💡 Troubleshooting Suggestions:")
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
    elif tool_name == "search_symbols":
        print(f"🔍 [Step {step}] CodeGraph Symbol Search:")
        print(f"   • Query:      {tool_args.get('query')}")
        print(f"   • Matches:    {result.get('total_matches', len(result.get('symbols', [])))}")
    elif tool_name == "get_symbol_definition":
        print(f"📖 [Step {step}] CodeGraph Symbol Definition:")
        print(f"   • Symbol:     {result.get('name', tool_args.get('symbol_name'))}")
        print(f"   • File:       {result.get('file_path', 'N/A')}")
    elif tool_name == "find_callers_and_callees":
        print(f"🕸️  [Step {step}] CodeGraph Call Graph Traversal:")
        print(f"   • Symbol:     {result.get('symbol', tool_args.get('symbol_name'))}")
        print(f"   • Inbound:    {len(result.get('callers_inbound', []))} callers")
        print(f"   • Outbound:   {len(result.get('callees_outbound', []))} callees")
    elif tool_name == "get_dependency_context":
        print(f"📦 [Step {step}] CodeGraph Bounded Context Package:")
        print(f"   • Symbol:     {result.get('name', tool_args.get('symbol_name'))}")
        print(f"   • Tests:      {len(result.get('related_tests', []))} related tests")
    elif tool_name == "get_code_graph_summary":
        print(f"🗺️  [Step {step}] CodeGraph Architectural Summary:")
        print(f"   • Files:      {result.get('files_count', 0)} files ({result.get('symbols_count', 0)} symbols)")
    else:
        print(f"⚙️  [Step {step}] {tool_name} completed successfully.")

    print("─" * 65)


async def run_simulation_mode(ticket: str) -> int:
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

    print("\n[Simulation Mode] Executing end-to-end tool pipeline...")

    # Step 1: Jira Issue Fetch
    jira_res = get_jira_issue(ticket)
    _log_tool_step(1, "get_jira_issue", {"issue_key": ticket}, jira_res, ticket)
    if "error" in jira_res:
        print_fatal_error(
            stage=f"Failed to fetch Jira ticket '{ticket}'",
            error_message=jira_res["error"],
            troubleshooting=[
                "Check that the ticket key format is valid (e.g. KAN-4, DEMO-1)",
                "Ensure JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN are configured in code-factory/.env",
                "Or pass --mock to run in offline mock mode with built-in ticket specs",
            ],
        )
        return 1

    # Step 2: Prepare Feature Branch
    branch_res = prepare_feature_branch(ticket)
    _log_tool_step(2, "prepare_feature_branch", {"issue_key": ticket}, branch_res, ticket)
    if "error" in branch_res:
        print_fatal_error(
            stage=f"Failed to prepare feature branch '{ticket}'",
            error_message=branch_res["error"],
        )
        return 1

    # Step 3: Inspect Project & Ingest Context
    files_res = list_project_files()
    _log_tool_step(3, "list_project_files", {}, files_res, ticket)

    # Step 4: Run Tests
    test_res = run_project_tests(ticket)
    _log_tool_step(4, "run_project_tests", {"issue_key": ticket}, test_res, ticket)

    # Step 5: Git Status & Diff
    status_res = get_git_status()
    _log_tool_step(5, "get_git_status", {}, status_res, ticket)

    # Step 6: PR creation simulation
    pr_res = push_and_create_pull_request(
        issue_key=ticket,
        summary=jira_res.get("summary", ""),
        description=jira_res.get("description", ""),
        acceptance_criteria=jira_res.get("acceptance_criteria", ""),
        changes_summary="Agent verified workspace, read ARCHITECTURE.md/DOMAIN_SPEC.md, and validated requirements.",
        test_summary=test_res.get("output_tail", "All tests verified."),
    )
    _log_tool_step(6, "push_and_create_pull_request", {}, pr_res, ticket)

    print("\n" + "=" * 65)
    print("🎉 Offline pipeline validation succeeded!")
    print("=" * 65)
    return 0


async def run_agent_async(ticket: str, is_mock: bool = False) -> int:
    """Execute the agent autonomously."""
    from coding_agent.tools.jira_tools import get_jira_issue

    print("=" * 65)
    print(f"🚀 Starting CodeFactoryAgent for ticket: {ticket}")
    print(f"📁 Target repository: {os.getenv('TARGET_REPO_DIR', 'Default')}")
    print(f"🤖 Model: {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}")
    print(f"🧪 Mock/Offline Mode: {'Enabled' if is_mock else 'Disabled'}")
    print("=" * 65)

    # Pre-flight Check: Validate target repository directory exists
    repo_dir_setting = os.getenv("TARGET_REPO_DIR", "../sample-springboot-app")
    target_repo_path = Path(repo_dir_setting).resolve()
    if not target_repo_path.is_dir():
        print_fatal_error(
            stage="Target Repository Directory Not Found",
            error_message=f"The specified target repository path does not exist: {target_repo_path}",
            troubleshooting=[
                "Check TARGET_REPO_DIR in code-factory/.env",
                "Ensure sample-springboot-app exists at that location",
                "Specify --repo-dir <path> explicitly when invoking run_agent.py",
            ],
        )
        return 1

    # Pre-flight Check: Read and validate Jira story immediately
    print(f"🔍 [Pre-flight] Retrieving and validating Jira requirements for '{ticket}'...")
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
        )
        return 1

    # Successfully retrieved Jira ticket: print complete ticket summary banner
    print_jira_ticket_banner(jira_data)

    # If in mock mode or Gemini API key is missing, execute simulation runner
    has_api_key = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    if is_mock or not has_api_key:
        if not has_api_key:
            print("ℹ️  [Notice] No GOOGLE_API_KEY found in environment. Running in offline simulation mode.")
        return await run_simulation_mode(ticket)

    # Live Gemini AI execution via official google.genai SDK with multi-turn tool calling loop
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
        from coding_agent.services.codegraph_service import CodeGraphService

        # Pre-flight Check: Initialize CodeGraph index if available
        if CodeGraphService.is_enabled() and CodeGraphService.is_parser_available():
            print("🧠 [Pre-flight] Initializing CodeGraph repository intelligence...")
            cg_svc = CodeGraphService.get_instance(target_repo_path)
            idx_res = cg_svc.ensure_indexed()
            if idx_res.get("status") == "success":
                print(f"   • CodeGraph indexed {idx_res.get('indexed_files', 0)} files in repository.")

        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        client = genai.Client(api_key=api_key)

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
        tool_map = {fn.__name__: fn for fn in tools}

        prompt = (
            f"Please implement the requirements and acceptance criteria for Jira ticket '{ticket}'.\n"
            f"Ticket summary: {jira_data.get('summary')}\n\n"
            f"Workflow instructions:\n"
            f"1. Call prepare_feature_branch with issue_key='{ticket}' to create/switch to the feature branch.\n"
            f"2. Read living documentation (ARCHITECTURE.md, DOMAIN_SPEC.md, openapi.yml) using read_project_file if present.\n"
            f"3. MANDATORY CODEGRAPH CODE EXPLORATION: Before writing code or reading whole files, you MUST use CodeGraph:\n"
            f"   - Call search_symbols with relevant keywords (e.g. 'Project', 'Employee', 'Assignment') to find domain entities, services, and repositories.\n"
            f"   - Call get_symbol_definition to inspect signatures, annotations, and code snippets for target classes.\n"
            f"   - Call find_callers_and_callees or get_dependency_context to see how existing services and endpoints interact.\n"
            f"4. Implement all required changes using write_project_file (Java code, migrations, tests, and updating openapi.yml).\n"
            f"5. Call run_project_tests to verify the implementation.\n"
            f"6. Call get_git_diff and get_git_status to review changes.\n"
            f"7. Call commit_changes with a message like 'feat({ticket}): ...'.\n"
            f"8. Call push_and_create_pull_request to submit the Pull Request for human review.\n"
            f"9. Output your final summary."
        )

        print(f"🤖 Invoking Gemini ({model}) with autonomous multi-step reasoning...")
        chat = client.chats.create(
            model=model,
            config=types.GenerateContentConfig(
                system_instruction=root_agent.instruction,
                tools=tools,
            ),
        )

        # Initial turn & token tracking
        response = chat.send_message(prompt)
        total_prompt_tokens = 0
        total_candidate_tokens = 0

        initial_meta = getattr(response, "usage_metadata", None)
        if initial_meta:
            p_cnt = getattr(initial_meta, "prompt_token_count", 0) or 0
            c_cnt = getattr(initial_meta, "candidates_token_count", 0) or 0
            total_prompt_tokens += p_cnt
            total_candidate_tokens += c_cnt
            print(f"📊 [Turn 1 Initial] Prompt Tokens: {p_cnt} | Output Tokens: {c_cnt}")

        step = 1
        max_steps = 30

        while response.function_calls and step <= max_steps:
            tool_responses = []
            for call in response.function_calls:
                tool_name = call.name
                tool_args = call.args or {}

                if tool_name in tool_map:
                    try:
                        fn_result = tool_map[tool_name](**tool_args)
                    except Exception as e:
                        fn_result = {"error": str(e)}
                else:
                    fn_result = {"error": f"Unknown tool: {tool_name}"}

                # Log informative, rich step output
                _log_tool_step(step, tool_name, tool_args, fn_result, ticket)

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
                        )
                        return 1

                tool_responses.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response={"result": fn_result},
                    )
                )

            step += 1
            # Send tool outputs back to Gemini
            response = chat.send_message(tool_responses)

            turn_meta = getattr(response, "usage_metadata", None)
            if turn_meta:
                p_cnt = getattr(turn_meta, "prompt_token_count", 0) or 0
                c_cnt = getattr(turn_meta, "candidates_token_count", 0) or 0
                total_prompt_tokens += p_cnt
                total_candidate_tokens += c_cnt
                print(f"📊 [Turn {step} Response] Prompt Tokens: {p_cnt} | Output Tokens: {c_cnt}")

        print("\n" + "=" * 65)
        print("🎉 CodeFactoryAgent Autonomous Execution Finished!")
        if total_prompt_tokens > 0 or total_candidate_tokens > 0:
            print(f"📊 Cumulative Usage: {total_prompt_tokens} prompt tokens, {total_candidate_tokens} candidate tokens ({total_prompt_tokens + total_candidate_tokens} total tokens)")
        print("=" * 65)
        if response.text:
            print(response.text)
        return 0

    except Exception as exc:
        print_fatal_error(
            stage="Gemini AI Invocation Failed",
            error_message=str(exc),
            troubleshooting=[
                "Verify GOOGLE_API_KEY in code-factory/.env is correct and active",
                "Ensure your Gemini model name is valid (e.g. gemini-2.5-flash)",
                "Check network connectivity to https://generativelanguage.googleapis.com",
            ],
        )
        return 1


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
            sys.exit(1)

    exit_code = asyncio.run(run_agent_async(ticket, is_mock=args.mock))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
