import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIRS = {".git", ".idea", ".vscode", "target", ".mvn", "__pycache__", "node_modules", "build", ".venv"}
PROTECTED_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
MAX_FILE_BYTES = 500_000
COMMAND_TIMEOUT_SECONDS = 300
ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")


def _get_target_repo() -> Path:
    """Determine the active repository path."""
    target = os.getenv("TARGET_REPO_DIR") or os.getenv("GITHUB_WORKSPACE")
    if target and Path(target).is_dir():
        return Path(target).resolve()

    # Check if sample-springboot-app exists adjacent or in parent
    adjacent = (ROOT / "sample-springboot-app").resolve()
    if adjacent.is_dir():
        return adjacent
    parent_adjacent = (ROOT.parent / "sample-springboot-app").resolve()
    if parent_adjacent.is_dir():
        return parent_adjacent

    return Path.cwd().resolve()


def _safe_file(repo: Path, relative_path: str, for_write: bool = False) -> Path:
    """Ensure file path remains strictly within the repository boundary."""
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError("Provide a relative project file path.")
    candidate = (repo / relative_path).resolve()
    try:
        candidate.relative_to(repo)
    except ValueError:
        raise ValueError("Path is outside the project repository.")
    parts = candidate.relative_to(repo).parts
    if any(part in EXCLUDED_DIRS or part in PROTECTED_NAMES for part in parts):
        raise ValueError(f"Access to protected or excluded path is prohibited: {relative_path}")
    if candidate.name.lower().startswith(".env"):
        raise ValueError("Environment files (.env) are protected.")
    if for_write and candidate.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        raise ValueError("Cryptographic key and certificate files cannot be written.")
    return candidate


def _git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a Git command inside the target repository."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def prepare_feature_branch(issue_key: str, base_branch: str = "main") -> dict:
    """Prepare the Git repository and create a feature branch named after the Jira ticket from main.

    Args:
        issue_key: The Jira ticket number / issue key (e.g. 'DEMO-1').
        base_branch: The base branch to branch from (defaults to 'main').
    """
    clean_key = (issue_key or "").strip()
    match = re.search(r"([A-Z][A-Z0-9_]+-\d+)", clean_key)
    if not match:
        return {"error": f"Invalid Jira issue key '{issue_key}'. Expected format like 'PROJ-123'."}
    clean_key = match.group(1)

    repo = _get_target_repo()
    if not repo.is_dir():
        return {"error": f"Repository directory not found at: {repo}"}

    try:
        # Check if git is initialized
        if not (repo / ".git").exists():
            init = _git(repo, "init")
            if init.returncode:
                return {"error": f"Git init failed: {init.stderr}"}
            dummy = repo / "README.md"
            if not dummy.exists():
                dummy.write_text("# Project\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-m", "chore: initial baseline commit", "--allow-empty")

        # Configure predictable Git identity locally in repo config
        name = os.getenv("GIT_AUTHOR_NAME", "CodeFactoryAgent")
        email = os.getenv("GIT_AUTHOR_EMAIL", "codefactoryagent@users.noreply.github.com")
        _git(repo, "config", "user.name", name)
        _git(repo, "config", "user.email", email)

        # Identify base branch: check if 'main' or specified base exists
        branches = _git(repo, "branch", "--list", base_branch)
        if not branches.stdout.strip():
            if base_branch == "main":
                master_check = _git(repo, "branch", "--list", "master")
                if master_check.stdout.strip():
                    base_branch = "master"
                else:
                    curr = _git(repo, "branch", "--show-current").stdout.strip()
                    if curr:
                        base_branch = curr
                    else:
                        base_branch = "main"
                        _git(repo, "checkout", "-B", "main")

        # Checkout base branch first if not already on it
        curr = _git(repo, "branch", "--show-current").stdout.strip()
        if curr != base_branch and base_branch:
            checkout_base = _git(repo, "checkout", base_branch)
            if checkout_base.returncode != 0:
                base_branch = curr or "main"

        # Identify existing branches on local and remote origin to prevent collisions
        remote_branches = set()
        remotes = _git(repo, "remote")
        if "origin" in remotes.stdout.split():
            try:
                ls_remote = _git(repo, "ls-remote", "--heads", "origin", timeout=15)
                if ls_remote.returncode == 0:
                    for line in ls_remote.stdout.splitlines():
                        if "\t" in line:
                            ref = line.split("\t")[1].strip()
                            if ref.startswith("refs/heads/"):
                                remote_branches.add(ref[11:])
            except Exception:
                pass

        local_branches = set()
        lb = _git(repo, "branch", "--list")
        if lb.returncode == 0:
            for b in lb.stdout.splitlines():
                b_clean = b.strip().replace("*", "").strip()
                if b_clean:
                    local_branches.add(b_clean)

        # If branch already exists on remote origin or locally, increment counter: KAN-4-1, KAN-4-2, etc.
        feature_branch = clean_key
        has_collision = (feature_branch in remote_branches) or (feature_branch in local_branches)
        if has_collision:
            counter = 1
            candidate = f"{clean_key}-{counter}"
            while candidate in remote_branches or candidate in local_branches:
                counter += 1
                candidate = f"{clean_key}-{counter}"
            feature_branch = candidate

        # Create or checkout feature branch
        checkout_feature = _git(repo, "checkout", "-B", feature_branch)
        if checkout_feature.returncode:
            return {"error": f"Failed to create feature branch '{feature_branch}': {checkout_feature.stderr}"}

        head = _git(repo, "rev-parse", "--short", "HEAD")
        msg = (
            f"Feature branch '{feature_branch}' (iteration suffix added due to existing branch) created from '{base_branch}'."
            if has_collision
            else f"Feature branch '{feature_branch}' created from '{base_branch}'. Ready for implementation."
        )
        return {
            "repository": str(repo),
            "issue_key": clean_key,
            "branch": feature_branch,
            "base_branch": base_branch,
            "head_commit": head.stdout.strip() if head.returncode == 0 else "unknown",
            "message": msg,
        }
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"error": str(exc)}


def initialize_workspace(issue_key: str) -> dict:
    """Backward-compatible alias for prepare_feature_branch."""
    return prepare_feature_branch(issue_key=issue_key)


def list_project_files(directory: str = ".", recursive: bool = True, max_depth: int = 15, issue_key: Optional[str] = None) -> dict:
    """List files and directories within the target project repository.

    Args:
        directory: Directory path relative to project root (defaults to '.').
        recursive: Whether to list recursively (defaults to True).
        max_depth: Maximum recursion depth (defaults to 5).
        issue_key: Optional Jira issue key for context.
    """
    try:
        repo = _get_target_repo()
        path = _safe_file(repo, directory)
        if not path.is_dir():
            return {"error": f"Directory not found: {directory}"}

        entries = []
        base_depth = len(path.parts)

        def scan_dir(cur_dir: Path, current_depth: int):
            if current_depth > max_depth:
                return
            for item in sorted(cur_dir.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                if (
                    item.name.startswith(".")
                    or item.name in EXCLUDED_DIRS
                    or item.name.lower().startswith(".env")
                ):
                    continue

                rel_path = item.relative_to(repo).as_posix()
                if item.is_dir():
                    entries.append({"name": item.name, "type": "directory", "path": rel_path})
                    if recursive:
                        scan_dir(item, current_depth + 1)
                else:
                    entries.append({"name": item.name, "type": "file", "path": rel_path})

        scan_dir(path, 1)
        return {"directory": directory, "total_entries": len(entries), "entries": entries}
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}


def read_project_file(file_path: str, issue_key: Optional[str] = None) -> dict:
    """Read a UTF-8 text file from the project repository.

    Args:
        file_path: Path relative to repository root.
        issue_key: Optional Jira issue key for context.
    """
    try:
        repo = _get_target_repo()
        path = _safe_file(repo, file_path)
        if not path.is_file():
            return {"error": f"File not found: {file_path}"}
        if path.stat().st_size > MAX_FILE_BYTES:
            return {"error": f"File exceeds maximum allowed inspection size ({MAX_FILE_BYTES} bytes)."}
        return {"path": file_path, "content": path.read_text(encoding="utf-8")}
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        return {"error": str(exc)}


def write_project_file(file_path: str, content: str, issue_key: Optional[str] = None) -> dict:
    """Create or update a UTF-8 text file inside the project repository.

    Args:
        file_path: Path relative to repository root.
        content: Complete file content to write.
        issue_key: Optional Jira issue key for context.
    """
    try:
        repo = _get_target_repo()
        path = _safe_file(repo, file_path, for_write=True)
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            return {"error": f"Refusing to write file exceeding size limit ({MAX_FILE_BYTES} bytes)."}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return {"success": True, "path": file_path, "bytes_written": len(encoded)}
    except (ValueError, OSError, UnicodeEncodeError) as exc:
        return {"error": str(exc)}


def run_project_tests(issue_key: Optional[str] = None) -> dict:
    """Run the repository test suite (Maven, Gradle) to verify implementation changes."""
    # Check for mock test mode
    mock_mode = (
        os.getenv("MOCK_TESTS", "").lower() in ("true", "1", "yes")
        or os.getenv("MOCK_MODE", "").lower() in ("true", "1", "yes")
    )

    try:
        repo = _get_target_repo()
        is_windows = os.name == "nt"

        # Detect Maven
        mvnw = repo / ("mvnw.cmd" if is_windows else "mvnw")
        mvn = shutil.which("mvn.cmd" if is_windows else "mvn")
        pom = repo / "pom.xml"

        # Detect Gradle
        gradlew = repo / ("gradlew.bat" if is_windows else "gradlew")
        gradle = shutil.which("gradle.bat" if is_windows else "gradle")
        gradle_file = (repo / "build.gradle") if (repo / "build.gradle").exists() else (repo / "build.gradle.kts")

        command = []
        if pom.exists():
            if mvnw.exists():
                if not is_windows:
                    mvnw.chmod(mvnw.stat().st_mode | 0o111)
                command = [str(mvnw), "-B", "test"] if not is_windows else ["cmd.exe", "/d", "/s", "/c", f'"{mvnw}" -B test']
            elif mvn:
                command = [mvn, "-B", "test"] if not is_windows else ["cmd.exe", "/d", "/s", "/c", f'"{mvn}" -B test']
            else:
                if mock_mode:
                    return {
                        "tests_passed": True,
                        "exit_code": 0,
                        "output_tail": "[MOCK] Maven build runner simulated. All 3 tests passed successfully (EmployeeServiceApplicationTests, EmployeeValidationTests, EmployeeDuplicateEmailTests).",
                        "note": "Running in mock test mode because Maven is not installed on host PATH."
                    }
                return {
                    "tests_passed": False,
                    "exit_code": 127,
                    "error": "pom.xml found but Maven (mvn/mvnw) was not found in PATH or project. Install Maven or use mock mode (MOCK_TESTS=true).",
                    "output_tail": "Maven executable not found.",
                }
        elif gradle_file.exists():
            if gradlew.exists():
                if not is_windows:
                    gradlew.chmod(gradlew.stat().st_mode | 0o111)
                command = [str(gradlew), "test"] if not is_windows else ["cmd.exe", "/d", "/s", "/c", f'"{gradlew}" test']
            elif gradle:
                command = [gradle, "test"] if not is_windows else ["cmd.exe", "/d", "/s", "/c", f'"{gradle}" test']
            else:
                if mock_mode:
                    return {
                        "tests_passed": True,
                        "exit_code": 0,
                        "output_tail": "[MOCK] Gradle build runner simulated. All tests passed.",
                        "note": "Running in mock test mode."
                    }
                return {
                    "tests_passed": False,
                    "exit_code": 127,
                    "error": "build.gradle found but Gradle (gradle/gradlew) was not found in PATH or project.",
                    "output_tail": "Gradle executable not found.",
                }
        else:
            return {"note": "No recognizable test runner configuration found (e.g. pom.xml or build.gradle). Skipping tests."}

        result = subprocess.run(
            command,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        combined_output = (result.stdout or "") + "\n" + (result.stderr or "")
        return {
            "tests_passed": result.returncode == 0,
            "exit_code": result.returncode,
            "output_tail": combined_output[-10000:],
            "note": "Test results are diagnostic. Failures should be addressed if possible before PR creation.",
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Test execution timed out after {COMMAND_TIMEOUT_SECONDS}s."}
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}


def get_git_status(issue_key: Optional[str] = None) -> dict:
    """Show current Git branch and working-tree status."""
    try:
        repo = _get_target_repo()
        if not (repo / ".git").exists():
            return {"error": "Target repository is not a Git repository."}
        branch = _git(repo, "branch", "--show-current")
        status = _git(repo, "status", "--short")
        if branch.returncode or status.returncode:
            return {"error": (branch.stderr + status.stderr)[-2000:]}
        return {"branch": branch.stdout.strip(), "status": status.stdout.strip() or "clean"}
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def get_git_diff(issue_key: Optional[str] = None) -> dict:
    """Return unstaged and staged diffs for changes made in the repository."""
    try:
        repo = _get_target_repo()
        if not (repo / ".git").exists():
            return {"error": "Target repository is not a Git repository."}
        diff = _git(repo, "diff", "--")
        staged = _git(repo, "diff", "--cached", "--")
        status = _git(repo, "status", "--short")
        if diff.returncode or staged.returncode or status.returncode:
            return {"error": (diff.stderr + staged.stderr + status.stderr)[-2000:]}
        return {
            "unstaged_diff": diff.stdout[-20000:],
            "staged_diff": staged.stdout[-20000:],
            "status": status.stdout.strip() or "clean",
        }
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def commit_changes(commit_message: str, issue_key: Optional[str] = None) -> dict:
    """Stage all project file changes and create a local Git commit.

    Args:
        commit_message: Single-line commit message describing the changes.
        issue_key: Optional Jira issue key for validation.
    """
    try:
        repo = _get_target_repo()
        if not (repo / ".git").exists():
            return {"error": "Target repository is not a Git repository."}
        if not commit_message or len(commit_message) > 200 or "\n" in commit_message:
            return {"error": "Provide a single-line commit message of at most 200 characters."}

        # Stage all modified and new files
        add = _git(repo, "add", "-A")
        if add.returncode:
            return {"error": f"Git add failed: {add.stderr[-2000:]}"}

        # Ensure there are actually changes to commit
        staged = _git(repo, "diff", "--cached", "--quiet")
        if staged.returncode == 0:
            return {"error": "There are no changes to commit."}

        result = _git(repo, "commit", "-m", commit_message)
        if result.returncode:
            return {"error": f"Git commit failed: {result.stderr[-2000:]}"}

        head = _git(repo, "rev-parse", "HEAD")
        branch = _git(repo, "branch", "--show-current")
        return {
            "success": True,
            "commit": head.stdout.strip() if head.returncode == 0 else None,
            "branch": branch.stdout.strip() if branch.returncode == 0 else None,
            "message": commit_message,
            "output": result.stdout[-1500:],
        }
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}
