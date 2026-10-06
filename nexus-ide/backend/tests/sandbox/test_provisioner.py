"""Tests for StackProvisioner dependency detection and installation."""
from __future__ import annotations

from unittest.mock import MagicMock

from backend.sandbox.provisioner import (
    StackProvisioner,
)


class TestDependencyDetection:
    def test_detect_python_requests(self) -> None:
        prov = StackProvisioner()
        code = "import requests\nresponse = requests.get('https://example.com')"
        deps = prov.detect_dependencies(code, "python")
        assert "requests" in deps

    def test_detect_python_pydantic(self) -> None:
        prov = StackProvisioner()
        code = "from pydantic import BaseModel\nclass User(BaseModel): ..."
        deps = prov.detect_dependencies(code, "python")
        assert "pydantic" in deps

    def test_detect_python_multiple(self) -> None:
        prov = StackProvisioner()
        code = """
import requests
import numpy as np
from pydantic import BaseModel
"""
        deps = prov.detect_dependencies(code, "python")
        assert "requests" in deps
        assert "numpy" in deps
        assert "pydantic" in deps

    def test_detect_python_no_deps(self) -> None:
        prov = StackProvisioner()
        code = "print('hello')\nx = 1 + 2"
        deps = prov.detect_dependencies(code, "python")
        assert deps == []

    def test_detect_node_express(self) -> None:
        prov = StackProvisioner()
        code = "const express = require('express');"
        deps = prov.detect_dependencies(code, "javascript")
        assert "express" in deps

    def test_detect_node_lodash(self) -> None:
        prov = StackProvisioner()
        code = "import _ from 'lodash';\n_.map([1, 2], x => x * 2);"
        deps = prov.detect_dependencies(code, "javascript")
        assert "lodash" in deps

    def test_detect_bash_no_deps(self) -> None:
        prov = StackProvisioner()
        code = "echo hello"
        deps = prov.detect_dependencies(code, "bash")
        assert deps == []


class TestStackProvisioner:
    def test_provision_python_package(self) -> None:
        container = MagicMock()
        container.exec_run.return_value = MagicMock(
            exit_code=0,
            output=(b"Successfully installed requests-2.31.0", b""),
        )

        prov = StackProvisioner()
        result = prov.provision(container, "python", ["requests"])
        assert result.success is True
        assert "requests" in result.packages_installed
        assert result.packages_failed == []

    def test_provision_python_package_failure(self) -> None:
        container = MagicMock()
        container.exec_run.return_value = MagicMock(
            exit_code=1,
            output=(b"", b"Could not find a version that satisfies"),
        )

        prov = StackProvisioner()
        result = prov.provision(container, "python", ["nonexistent-pkg-12345"])
        assert result.success is False
        assert result.packages_installed == []
        assert "nonexistent-pkg-12345" in result.packages_failed

    def test_provision_node_package(self) -> None:
        container = MagicMock()
        container.exec_run.side_effect = [
            # npm init -y
            MagicMock(exit_code=0, output=(b"", b"")),
            # npm install express
            MagicMock(exit_code=0, output=(b"added 1 package", b"")),
        ]

        prov = StackProvisioner()
        result = prov.provision(container, "javascript", ["express"])
        assert result.success is True
        assert "express" in result.packages_installed

    def test_get_default_packages(self) -> None:
        prov = StackProvisioner()
        py_defaults = prov.get_default_packages("python")
        assert "pytest" in py_defaults
        assert "requests" in py_defaults
        assert "pydantic" in py_defaults

        js_defaults = prov.get_default_packages("javascript")
        assert "jest" in js_defaults
        assert "express" in js_defaults

        bash_defaults = prov.get_default_packages("bash")
        assert bash_defaults == []
