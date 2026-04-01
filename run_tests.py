#!/usr/bin/env python
"""
Test runner script - runs all test files and reports summary.

Usage:
    python run_tests.py         # Run all tests
    python run_tests.py -v      # Verbose output
    python run_tests.py -q      # Quiet mode (summary only)
"""
import subprocess
import sys
import os
from pathlib import Path

# Test files to run in order
TEST_FILES = [
    'tests/test_modules.py',
    'tests/test_qbittorrent_api.py',
    'tests/test_qbittorrent_api_errors.py',
    'tests/test_rss_rules.py',
    'tests/test_integration.py',
    'tests/test_filtering.py',
    'tests/test_validation.py',
    'tests/test_config_and_sonarr_upgrades.py',
    'tests/test_gui_components.py',
    'tests/test_treeview_display.py',
    'tests/test_import_export_edge_cases.py',
    'tests/test_entrypoint_and_dialog_singletons.py',
]


def run_tests(verbose=False, quiet=False):
    """Run all test files and collect results."""
    # Change to project root
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    # Add project root to PYTHONPATH for imports
    env = os.environ.copy()
    pythonpath = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = str(project_root) + (os.pathsep + pythonpath if pythonpath else '')
    # Ensure UTF-8 output for Unicode characters in test output
    env['PYTHONIOENCODING'] = 'utf-8'
    
    results = []
    print("=" * 60)
    print("RUNNING ALL TESTS")
    print("=" * 60)
    
    for test_file in TEST_FILES:
        if not Path(test_file).exists():
            print(f"\n⚠ Skipping {test_file} (not found)")
            continue
            
        print(f"\n{'─' * 60}")
        print(f"Running: {test_file}")
        print("─" * 60)
        
        # Run each test module via pytest so pytest-style tests and fixtures execute.
        cmd = [sys.executable, '-m', 'pytest', test_file]
        if quiet:
            cmd.append('-q')
        elif verbose:
            cmd.append('-v')

        result = subprocess.run(
            cmd,
            capture_output=quiet,
            text=True,
            env=env
        )
        
        success = result.returncode == 0
        results.append((test_file, success))
        
        if quiet and not success:
            # Show output only on failure in quiet mode
            print(result.stdout)
            print(result.stderr)
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for test_file, success in results:
        status = "✓ PASSED" if success else "✗ FAILED"
        print(f"  {status}: {test_file}")
    
    passed = sum(1 for _, s in results if s)
    failed = len(results) - passed
    
    print("─" * 60)
    print(f"Total: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == '__main__':
    verbose = '-v' in sys.argv
    quiet = '-q' in sys.argv
    
    success = run_tests(verbose=verbose, quiet=quiet)
    sys.exit(0 if success else 1)
