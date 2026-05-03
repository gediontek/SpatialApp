"""Harness — C1 (execute_code AST sandbox).

Contract: validate_code() MUST reject a curated DENY corpus of known
sandbox-escape payloads, and MUST allow a curated ALLOW corpus of
spatial computations. Adding a new escape technique to DENY without
changing the validator is the regression signal.

Source for escapes: standard Python sandbox escape research +
this repo's audit (07-v2-audit-findings.md §C1).
"""
import pytest

from services.code_executor import validate_code

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
