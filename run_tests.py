
"""PDFApps — Sequential test runner.

Discovers all test files in the 'tests' directory and executes them sequentially
in isolated subprocesses to avoid PySide6 QApplication singleton pollution.
"""

import os
import subprocess
import sys
import time
from pathlib import Path


def find_test_files(tests_dir: Path) -> list[Path]:
    """Find and return all test_*.py files sorted alphabetically."""
    if not tests_dir.is_dir():
        return []
    return sorted(tests_dir.glob("test_*.py"))


def run_test_file(test_file: Path, extra_args: list[str]) -> tuple[bool, float, str]:
    """Run a single test file using pytest in an isolated subprocess.

    Returns:
        (passed, duration_seconds, output)
    """
    cmd = [sys.executable, "-m", "pytest", str(test_file)] + extra_args
    start_time = time.perf_counter()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    duration = time.perf_counter() - start_time
    passed = (result.returncode == 0)
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    return passed, duration, output.strip()


def main() -> int:
    project_root = Path(__file__).resolve().parent
    tests_dir = project_root / "tests"

    extra_args = sys.argv[1:]
    test_files = find_test_files(tests_dir)

    if not test_files:
        print(f"No test files found in {tests_dir}")
        return 1

    print(f"Found {len(test_files)} test suites in {tests_dir.name}/:")
    for tf in test_files:
        print(f"  • {tf.name}")
    print("=" * 70)

    total_start = time.perf_counter()
    failed_suites: list[str] = []
    passed_count = 0

    for i, test_file in enumerate(test_files, start=1):
        print(f"[{i}/{len(test_files)}] Running {test_file.name} ... ", end="", flush=True)
        passed, duration, output = run_test_file(test_file, extra_args)

        if passed:
            passed_count += 1
            print(f"PASSED ({duration:.2f}s)")
        else:
            failed_suites.append(test_file.name)
            print(f"FAILED ({duration:.2f}s)")
            print("-" * 70)
            print(output)
            print("-" * 70)

    total_duration = time.perf_counter() - total_start
    print("=" * 70)
    print(f"Summary: {passed_count}/{len(test_files)} suites passed in {total_duration:.2f}s")

    if failed_suites:
        print("Failed suites:")
        for name in failed_suites:
            print(f"  ✗ {name}")
        return 1

    print("All test suites passed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())