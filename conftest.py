#
# Copyright (C) OpenCyphal Development Team  <opencyphal.org>
# Copyright Amazon.com Inc. or its affiliates.
# SPDX-License-Identifier: MIT
#
"""
Configuration for pytest tests including fixtures and hooks.
"""

import tempfile
from pathlib import Path
from typing import Any, Optional

import pytest


# +-------------------------------------------------------------------------------------------------------------------+
# | TEST FIXTURES
# +-------------------------------------------------------------------------------------------------------------------+
class TemporaryDsdlContext:
    """
    Powers the temp_dsdl_factory test fixture.
    """
    def __init__(self) -> None:
        self._base_dir: Optional[Any] = None

    def new_file(self, file_path: Path, text: str | None = None) -> Path:
        if file_path.is_absolute():
            raise ValueError(f"{file_path} is an absolute path. The test fixture requires relative paths to work.")
        file = self.base_dir / file_path
        file.parent.mkdir(parents=True, exist_ok=True)
        if text is not None:
            file.write_text(text)
        return file

    @property
    def base_dir(self) -> Path:
        if self._base_dir is None:
            self._base_dir = tempfile.TemporaryDirectory()
        return Path(self._base_dir.name).resolve()

    def _test_path_finalizer(self) -> None:
        """
        Finalizer to clean up any temporary directories created during the test.
        """
        if self._base_dir is not None:
            self._base_dir.cleanup()
            del self._base_dir
            self._base_dir = None

@pytest.fixture(scope="function")
def temp_dsdl_factory(request: pytest.FixtureRequest) -> Any:  # pylint: disable=unused-argument
    """
    Fixture for pydsdl tests that have to create files as part of the test. This object stays in-scope for a given
    test method and does not requires a context manager in the test itself.

    Call `new_file(path)` to create a new file path in the fixture's temporary directory. This will create all
    uncreated parent directories but will _not_ create the file unless text is provided: `new_file(path, "hello")`
    """
    f = TemporaryDsdlContext()
    request.addfinalizer(f._test_path_finalizer)  # pylint: disable=protected-access
    return f



@pytest.fixture
def public_types() -> Path:
    """
    Path to the public regulated data types directory used for tests.
    """
    return Path(".dsdl-test") / "uavcan"
