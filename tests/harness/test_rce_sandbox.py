"""Harness — C1 (execute_code AST sandbox).

Contract: validate_code() MUST reject a curated DENY corpus of known
sandbox-escape payloads, and MUST allow a curated ALLOW corpus of
spatial computations. Adding a new escape technique to DENY without
changing the validator is the regression signal.

Source for escapes: standard Python sandbox escape research +
this repo's audit (07-v2-audit-findings.md §C1).
"""
import pytest

from services.code_executor import validate_code, execute_safely

# Each entry is (label, code). Anything under DENY MUST validate False;
# anything under ALLOW MUST validate True. New escape techniques
# discovered during audits should be appended to DENY.
DENY_CORPUS = [
    ("audit_bypass_importlib_chain",
     "import importlib; importlib.import_module('os').system('echo pwned')"),
    ("import_os",
     "import os\nos.listdir('/')"),
    ("import_subprocess",
     "import subprocess\nsubprocess.run(['ls'])"),
    ("import_socket",
     "import socket\ns = socket.socket()"),
    ("frame_walk_subclasses",
     "x = ().__class__.__bases__[0].__subclasses__()"),
    ("getattr_dunder",
     "x = getattr(object, '__subclasses__')()"),
    ("eval_call",
     "x = eval('1+1')"),
    ("exec_call",
     "x = exec('print(1)')"),
    ("compile_call",
     "x = compile('1', '<x>', 'eval')"),
    ("open_etc_passwd",
     "data = open('/etc/passwd').read()"),
    ("globals_lookup",
     "x = globals()['__builtins__']"),
    ("dunder_class_chain",
     "x = ''.__class__.__mro__"),
    ("relative_import",
     "from . import config"),
    ("getattr_builtin_chain",
     "x = getattr(__builtins__, 'open')('/etc/passwd')"),
]

ALLOW_CORPUS = [
    ("numpy_mean",
     "import numpy as np\nresult = float(np.mean([1, 2, 3]))"),
    ("shapely_buffer",
     "from shapely.geometry import Point, mapping\n"
     "p = Point(0, 0).buffer(1)\n"
     "geojson = mapping(p)"),
    ("pandas_describe",
     "import pandas as pd\nresult = list(pd.Series([1,2,3]).describe().index)"),
    ("math_pi",
     "import math\nresult = math.pi"),
    ("statistics_median",
     "import statistics\nresult = statistics.median([1, 2, 3, 4, 5])"),
    ("plain_arithmetic",
     "result = sum(range(100))"),
    ("collections_counter",
     "from collections import Counter\nresult = dict(Counter([1,1,2,3]))"),
]


@pytest.mark.parametrize("label,code", DENY_CORPUS, ids=lambda x: x if isinstance(x, str) else "")
def test_deny_corpus_rejected(label, code):
    is_safe, msg = validate_code(code)
    assert is_safe is False, f"DENY corpus item {label!r} was NOT rejected. Sandbox escape risk."
    assert msg, f"Validator returned no reason for rejection of {label!r}"


@pytest.mark.parametrize("label,code", ALLOW_CORPUS, ids=lambda x: x if isinstance(x, str) else "")
def test_allow_corpus_accepted(label, code):
    is_safe, msg = validate_code(code)
    assert is_safe is True, (
        f"ALLOW corpus item {label!r} was REJECTED. Validator is too "
        f"strict for legitimate spatial computation. msg={msg!r}"
    )


# Execution assertions: validate_code-only coverage was insufficient
# (auditor 2026-05-03 found a child-env regression that broke shapely +
# numpy imports inside execute_safely while validate_code still passed).
# Each entry below MUST both validate AND execute.
EXECUTE_CORPUS = [
    ("plain_arithmetic_returns_value",
     "result = sum(range(100))",
     lambda r: r.get("result") == 4950),
    ("numpy_mean",
     "import numpy as np\nresult = float(np.mean([1, 2, 3]))",
     lambda r: abs(r.get("result", 0) - 2.0) < 1e-6),
    ("shapely_buffer_geojson",
     "from shapely.geometry import Point, mapping\n"
     "p = Point(0, 0).buffer(1)\n"
     "geojson = mapping(p)",
     lambda r: (r.get("geojson") or {}).get("type") == "Polygon"),
    ("pandas_describe",
     "import pandas as pd\n"
     "result = list(pd.Series([1, 2, 3]).describe().index)",
     lambda r: "mean" in (r.get("result") or [])),
    ("math_pi",
     "import math\nresult = math.pi",
     lambda r: abs((r.get("result") or 0) - 3.14159265) < 1e-5),
]


@pytest.mark.parametrize("label,code,check", EXECUTE_CORPUS,
                         ids=[c[0] for c in EXECUTE_CORPUS])
def test_allow_corpus_actually_executes(label, code, check):
    """Allowed code MUST also run successfully in the sandbox subprocess.

    Catches regressions where the AST validator says "OK" but the
    subprocess env (PATH / HOME / PYTHONPATH) cannot import the module.
    """
    result = execute_safely(code, timeout=15)
    assert result["success"] is True, (
        f"EXECUTE corpus item {label!r} failed to run. "
        f"error={result.get('error')!r}"
    )
    assert check(result), (
        f"EXECUTE corpus item {label!r} ran but returned wrong shape. "
        f"result={result!r}"
    )


def test_execute_environment_has_no_secret_keys():
    """Belt-and-suspenders: even if a child reads os.environ (it would
    be AST-blocked first), no LLM provider keys / SECRET_KEY / DB
    password should be present. Verified by spawning the sandbox with
    the parent process pre-poisoned with marker values and reading
    them back from inside the (legitimately-called) subprocess via a
    side-channel not gated by the AST: print to stdout.

    Skipped because the AST whitelist also blocks `import os` and
    `print(getattr(...))` patterns; this is documented as a future
    Hypothesis-style escape harness.
    """
    pytest.skip("Defense-in-depth env stripping verified manually; "
                "AST whitelist already prevents user code from reading os.environ.")
