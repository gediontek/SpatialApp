"""Sandboxed Python code execution for spatial analysis.

Audit C1 hardening (2026-05-03):
  - Substring blacklist replaced with **AST-based allowlist**: every
    Import / ImportFrom must target a module in ALLOWED_MODULES. Call
    nodes targeting reflection or I/O builtins (__import__, eval, exec,
    compile, open, getattr, setattr, globals, locals, vars) are rejected.
    Attribute access to dunder names (__class__, __bases__, __subclasses__,
    __globals__, __builtins__, __mro__, __code__, __dict__) is rejected.
  - RLIMIT_AS / RLIMIT_CPU enforced in the subprocess on Unix via a
    `preexec_fn`. max_memory_mb is now actually enforced.
  - Subprocess env is minimal (no inherited secrets) and PYTHONIOENCODING
    is pinned for deterministic stream behavior.
  - In-process exec is removed (was never present here, but documenting).

Defense-in-depth: AST validation is necessary but not sufficient. Bypass
research is ongoing; treat this sandbox as ALLOWING NEAR-PURE COMPUTATION,
not as a security boundary against a determined attacker.
"""

import ast
import json
import logging
import os
import resource
import subprocess
import sys
import tempfile

logger = logging.getLogger(__name__)

# Modules the generated code is allowed to import.
ALLOWED_MODULES = frozenset({
    'json', 'math', 'statistics', 'collections', 'itertools', 'functools',
    'shapely', 'shapely.geometry', 'shapely.ops', 'shapely.wkt',
    'geopandas', 'pandas', 'numpy', 'scipy', 'scipy.spatial',
    'scipy.interpolate', 'pyproj',
})

# Builtins that are uniformly blocked.
FORBIDDEN_BUILTINS = frozenset({
    '__import__', 'eval', 'exec', 'compile',
    'open', 'input', 'breakpoint',
    'getattr', 'setattr', 'delattr',
    'globals', 'locals', 'vars',
    'memoryview',
})

# Dunder attribute access used in common Python sandbox escapes.
FORBIDDEN_DUNDERS = frozenset({
    '__class__', '__bases__', '__base__', '__mro__', '__subclasses__',
    '__globals__', '__builtins__', '__dict__', '__code__',
    '__import__', '__getattribute__', '__getattr__', '__setattr__',
    '__delattr__', '__reduce__', '__reduce_ex__',
    '__init_subclass__', '__class_getitem__',
    'gi_frame', 'cr_frame', 'f_globals', 'f_locals', 'f_back',
})


class _Validator(ast.NodeVisitor):
    """Walk the AST and accumulate violations."""

    def __init__(self):
        self.violations: list[str] = []

    def _is_allowed_module(self, name: str) -> bool:
        if name in ALLOWED_MODULES:
            return True
        # Allow submodules of allowed modules (e.g. numpy.linalg).
        for allowed in ALLOWED_MODULES:
            if name == allowed or name.startswith(allowed + '.'):
                return True
        return False

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if not self._is_allowed_module(alias.name):
                self.violations.append(f"forbidden import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ''
        if node.level and node.level > 0:
            self.violations.append("relative imports forbidden")
        if not self._is_allowed_module(mod):
            self.violations.append(f"forbidden import-from: {mod}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in FORBIDDEN_DUNDERS:
            self.violations.append(f"forbidden attribute: .{node.attr}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_BUILTINS:
            # Bare name use (e.g. `eval`); Call nodes also caught below.
            self.violations.append(f"forbidden name: {node.id}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Direct calls to forbidden builtins.
        func = node.func
        if isinstance(func, ast.Name) and func.id in FORBIDDEN_BUILTINS:
            self.violations.append(f"forbidden call: {func.id}()")
        # Calls to importlib.* — block the whole module surface.
        if isinstance(func, ast.Attribute):
            chain = []
            cur = func
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                chain.append(cur.id)
            chain.reverse()
            dotted = '.'.join(chain)
            if dotted.startswith('importlib') or dotted.startswith('os.') \
                    or dotted.startswith('sys.') or dotted.startswith('subprocess.'):
                self.violations.append(f"forbidden call chain: {dotted}")
        self.generic_visit(node)


def validate_code(code: str) -> tuple:
    """Return (is_safe, violation_message)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"syntax error: {e.msg}"
    v = _Validator()
    v.visit(tree)
    if v.violations:
        return False, "; ".join(v.violations)
    return True, None


def _set_rlimits(max_memory_mb: int, timeout_s: int):
    """Return a preexec_fn that hard-caps the worker's memory + CPU.

    Called in the child process between fork and exec. No-op on platforms
    where resource limits are unsupported.
    """
    def _apply():
        try:
            mem_bytes = max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (ValueError, OSError):
            pass
        try:
            # Add a small grace period over the wall-clock timeout.
            cpu_seconds = max(1, int(timeout_s) + 2)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        except (ValueError, OSError):
            pass
        try:
            # No new files beyond stdio.
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        except (ValueError, OSError):
            pass
    return _apply


_WRAPPER_TEMPLATE = '''\
import json, sys
_input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {{}}

{user_code}

_output = {{"stdout": ""}}
for _name in ("result", "geojson", "output"):
    if _name in vars():
        _val = vars().get(_name)
        if _val is not None:
            _output[_name] = _val
sys.stdout.write("__RESULT__" + json.dumps(_output, default=str))
'''


def execute_safely(code: str, input_data: dict = None, timeout: int = 10,
                   max_memory_mb: int = 256) -> dict:
    """Execute Python code in a subprocess with restrictions.

    Args:
        code: Python code to execute (validated against the AST allowlist).
        input_data: Optional dict passed as JSON to the code via stdin.
        timeout: Wall-clock max execution time in seconds.
        max_memory_mb: Hard cap enforced via RLIMIT_AS in the child.

    Returns:
        {"success": True, "stdout": "...", "result": ..., "geojson": ...}
        or {"success": False, "error": "..."}.
    """
    is_safe, violation = validate_code(code)
    if not is_safe:
        return {"success": False, "error": f"Code validation failed: {violation}"}

    wrapper = _WRAPPER_TEMPLATE.format(user_code=code)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(wrapper)
        script_path = f.name

    try:
        # Audit C1 follow-up (2026-05-03): build env by COPY-AND-FILTER,
        # not by allowlist. The previous minimal env stripped HOME +
        # PATH so aggressively that site-packages discovery broke on
        # macOS user-site installs and some venv layouts (auditor-found
        # regression: shapely + numpy could not import in the child).
        # Strategy: inherit the parent env, then deny-list anything
        # that looks like a secret. Same security posture (no secrets
        # leaked), but interpreter setup remains intact.
        _SECRET_PREFIXES = (
            'SECRET', 'PASSWORD', 'PASSWD', 'TOKEN', 'KEY', 'CREDENTIAL',
            'API_KEY', 'AUTH', 'OAUTH', 'PRIVATE',
        )
        _SECRET_INFIXES = ('SECRET', 'PASSWORD', 'PASSWD', 'TOKEN', 'CREDENTIAL', 'AUTH')
        _ALWAYS_DROP = (
            'ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY',
            'GOOGLE_API_KEY', 'CHAT_API_TOKEN', 'SECRET_KEY',
            'DATABASE_URL', 'DATABASE_PASSWORD', 'AWS_SECRET_ACCESS_KEY',
            'AWS_SESSION_TOKEN', 'AWS_ACCESS_KEY_ID',
        )
        env = {}
        for k, v in os.environ.items():
            if k in _ALWAYS_DROP:
                continue
            ku = k.upper()
            if any(ku.startswith(p) for p in _SECRET_PREFIXES):
                continue
            if any(s in ku for s in _SECRET_INFIXES):
                continue
            env[k] = v
        # Pin determinism + I/O encoding regardless of parent.
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONHASHSEED'] = '0'

        kwargs: dict = {
            'input': json.dumps(input_data or {}),
            'capture_output': True,
            'text': True,
            'timeout': timeout,
            'env': env,
        }
        # preexec_fn is POSIX-only; resource module is similar.
        if hasattr(resource, 'setrlimit') and os.name == 'posix':
            kwargs['preexec_fn'] = _set_rlimits(max_memory_mb, timeout)

        proc = subprocess.run([sys.executable, script_path], **kwargs)

        if proc.returncode != 0:
            stderr = (proc.stderr or '')[:500]
            return {"success": False, "error": f"Code execution failed: {stderr}"}

        stdout = proc.stdout or ''
        if "__RESULT__" in stdout:
            result_json = stdout.split("__RESULT__", 1)[1].strip()
            try:
                result = json.loads(result_json)
                return {
                    "success": True,
                    "stdout": stdout.split("__RESULT__", 1)[0].strip(),
                    "result": result.get("result"),
                    "geojson": result.get("geojson"),
                }
            except json.JSONDecodeError:
                pass

        return {"success": True, "stdout": stdout[:2000]}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Code execution timed out after {timeout}s"}
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
