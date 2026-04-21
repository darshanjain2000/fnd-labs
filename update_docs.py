"""
update_docs.py — Auto-update markdown docs after code changes.

- Scans staged/committed code for changes to strategies, config, or CLI.
- Updates README.md, AGENTS.md, docs/plan.md, docs/ARCHITECTURE.md as per .skills/update_docs_for_backtest_optuna.md.
- Intended for use in a git post-commit hook.
"""
import subprocess
import sys
from pathlib import Path

SKILL_PATH = Path(__file__).parent / ".skills" / "update_docs_for_backtest_optuna.md"
DOCS = [
    "README.md",
    "AGENTS.md",
    "docs/plan.md",
    "docs/ARCHITECTURE.md",
]


def get_staged_files() -> list[str]:
    result = subprocess.run(["git", "diff", "--name-only", "--cached"], capture_output=True, text=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> None:
    staged = get_staged_files()
    if not staged:
        print("No staged files. Skipping doc update.")
        return
    # For demo: just print what would be updated
    print("Staged files:", staged)
    print("Would update docs as per:", SKILL_PATH)
    for doc in DOCS:
        if Path(doc).exists():
            print(f"[SIMULATED] Would update {doc} using {SKILL_PATH}")
    # Real implementation would parse SKILL_PATH and apply updates
    # using LLM or rule-based logic

if __name__ == "__main__":
    main()
