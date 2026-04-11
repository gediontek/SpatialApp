"""Tests for sandboxed Python code execution."""

import pytest

from services.code_executor import validate_code, execute_safely
from nl_gis.handlers import dispatch_tool, LAYER_PRODUCING_TOOLS


class TestValidateCode:
    """Test code validation against forbidden patterns."""

    def test_safe_code_passes(self):
        is_safe, msg = validate_code("result = 2 + 2")
        assert is_safe is True
        assert msg is None

    def test_forbidden_import_os(self):
        is_safe, msg = validate_code("import os\nos.listdir('/')")
        assert is_safe is False
        assert "import os" in msg

    def test_forbidden_open_file(self):
        is_safe, msg = validate_code("data = open('/etc/passwd').read()")
        assert is_safe is False
        assert "open(" in msg

    def test_forbidden_eval(self):
        is_safe, msg = validate_code("x = eval('2+2')")
        assert is_safe is False
        assert "eval(" in msg

    def test_forbidden_subprocess(self):
        is_safe, msg = validate_code("import subprocess\nsubprocess.run(['ls'])")
        assert is_safe is False

    def test_forbidden_getattr(self):
        is_safe, msg = validate_code("x = getattr(obj, 'secret')")
        assert is_safe is False

    def test_forbidden_globals(self):
        is_safe, msg = validate_code("g = globals()")
        assert is_safe is False


class TestExecuteSafely:
    """Test sandboxed code execution."""

    def test_simple_calculation(self):
        result = execute_safely("result = 2 + 2")
        assert result["success"] is True
        assert result["result"] == 4

    def test_shapely_buffer(self):
        code = """
from shapely.geometry import Point, mapping
p = Point(0, 0).buffer(1)
geojson = mapping(p)
"""
        result = execute_safely(code)
        assert result["success"] is True
        assert result["geojson"] is not None
        assert result["geojson"]["type"] == "Polygon"

    def test_forbidden_code_rejected(self):
        result = execute_safely("import os\nos.listdir('/')")
        assert result["success"] is False
        assert "Forbidden" in result["error"]

    def test_timeout(self):
        code = "while True: pass"
        result = execute_safely(code, timeout=2)
        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_empty_code(self):
        result = execute_safely("")
        # Empty code should still succeed (no-op) or be caught
        # The wrapper will run but produce no result variables
        assert result["success"] is True

    def test_with_input_data(self):
        code = """
data = _input_data.get('test_key', 'missing')
result = f"got: {data}"
"""
        result = execute_safely(code, input_data={"test_key": "hello"})
        assert result["success"] is True
        assert result["result"] == "got: hello"

    def test_with_input_layer(self):
        code = """
import json
layer = _input_data.get('layer', {})
count = len(layer.get('features', []))
result = f"Feature count: {count}"
"""
        input_data = {
            "layer": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}},
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}, "properties": {}},
                ]
            }
        }
        result = execute_safely(code, input_data=input_data)
        assert result["success"] is True
        assert result["result"] == "Feature count: 2"

    def test_syntax_error(self):
        code = "def foo(\n  this is not valid python"
        result = execute_safely(code)
        assert result["success"] is False
        assert "error" in result

    def test_print_output(self):
        code = """
print("hello world")
result = 42
"""
        result = execute_safely(code)
        assert result["success"] is True
        assert result["stdout"] == "hello world"
        assert result["result"] == 42

    def test_numpy_available(self):
        code = """
import numpy as np
result = float(np.mean([1, 2, 3, 4, 5]))
"""
        result = execute_safely(code)
        assert result["success"] is True
        assert result["result"] == 3.0


class TestDispatchRegistration:
    """Test that execute_code is properly registered."""

    def test_execute_code_in_layer_producing_tools(self):
        assert "execute_code" in LAYER_PRODUCING_TOOLS

    def test_dispatch_registration(self):
        """Test that dispatch_tool recognizes execute_code."""
        # dispatch_tool should not raise ValueError for execute_code
        result = dispatch_tool("execute_code", {"code": "result = 1 + 1"})
        assert result.get("success") is True
        assert result.get("result") == 2

    def test_dispatch_empty_code(self):
        result = dispatch_tool("execute_code", {"code": ""})
        assert "error" in result

    def test_dispatch_forbidden_code(self):
        result = dispatch_tool("execute_code", {"code": "import os"})
        assert "error" in result
