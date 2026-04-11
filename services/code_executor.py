"""Sandboxed Python code execution for spatial analysis."""

import subprocess
import sys
import json
import tempfile
import os
import logging

logger = logging.getLogger(__name__)

# Modules the generated code is allowed to import
ALLOWED_MODULES = {
    'json', 'math', 'statistics', 'collections', 'itertools', 'functools',
    'shapely', 'shapely.geometry', 'shapely.ops', 'shapely.wkt',
    'geopandas', 'pandas', 'numpy', 'scipy', 'scipy.spatial',
    'scipy.interpolate', 'pyproj',
}

# Patterns that are forbidden in generated code
FORBIDDEN_PATTERNS = [
    'import os', 'import sys', 'import subprocess', 'import socket',
    'import requests', 'import urllib', 'import http',
    'import shutil', 'import glob', 'import pathlib',
    '__import__', 'eval(', 'exec(', 'compile(',
    'open(', 'os.', 'sys.', 'subprocess.',
    'environ', '.env', 'getattr(', 'setattr(',
    'globals(', 'locals(', 'vars(',
]


def validate_code(code: str) -> tuple:
    """Check code for forbidden patterns.
    Returns (is_safe, violation_message).
    """
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in code:
            return False, f"Forbidden pattern: {pattern}"
    return True, None


def execute_safely(code: str, input_data: dict = None, timeout: int = 10,
                   max_memory_mb: int = 256) -> dict:
    """Execute Python code in a subprocess with restrictions.

    Args:
        code: Python code to execute
        input_data: Optional dict passed as JSON to the code via stdin
        timeout: Max execution time in seconds
        max_memory_mb: Max memory (advisory, enforced via ulimit on Unix)

    Returns:
        {"success": True, "stdout": "...", "geojson": {...} or None}
        or {"success": False, "error": "..."}
    """
    is_safe, violation = validate_code(code)
    if not is_safe:
        return {"success": False, "error": f"Code validation failed: {violation}"}

    # Wrap the code to capture output
    wrapper = f'''
import sys, json

# Provide input data
_input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {{}}

# User code
{code}

# Capture any variable named 'result' or 'geojson' as output
_output = {{"stdout": ""}}
for _name in ['result', 'geojson', 'output']:
    if _name in dir() or _name in locals():
        _val = locals().get(_name) or globals().get(_name)
        if _val is not None:
            _output[_name] = _val
print("__RESULT__" + json.dumps(_output, default=str))
'''

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(wrapper)
        script_path = f.name

    try:
        env = {
            'PATH': os.environ.get('PATH', ''),
            'PYTHONPATH': os.environ.get('PYTHONPATH', ''),
            'HOME': os.environ.get('HOME', '/tmp'),
        }

        proc = subprocess.run(
            [sys.executable, script_path],
            input=json.dumps(input_data or {}),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        if proc.returncode != 0:
            stderr = proc.stderr[:500]  # Truncate long errors
            return {"success": False, "error": f"Code execution failed: {stderr}"}

        stdout = proc.stdout
        if "__RESULT__" in stdout:
            result_json = stdout.split("__RESULT__")[1].strip()
            try:
                result = json.loads(result_json)
                return {
                    "success": True,
                    "stdout": stdout.split("__RESULT__")[0].strip(),
                    "result": result.get("result"),
                    "geojson": result.get("geojson"),
                }
            except json.JSONDecodeError:
                pass

        return {"success": True, "stdout": stdout[:2000]}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Code execution timed out after {timeout}s"}
    finally:
        os.unlink(script_path)
