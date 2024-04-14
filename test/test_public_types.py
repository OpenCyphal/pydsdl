# Copyright (C) OpenCyphal Development Team  <opencyphal.org>
# Copyright Amazon.com Inc. or its affiliates.
# SPDX-License-Identifier: MIT

# pylint: disable=redefined-outer-name
# pylint: disable=logging-fstring-interpolation
import cProfile
import io
import logging
import pstats
from pathlib import Path
from pstats import SortKey

import pytest

import pydsdl


@pytest.fixture
def public_types() -> Path:
    return Path("test") / "public_regulated_data_types" / "uavcan"


def dsdl_printer(dsdl_file: Path, line: int, message: str) -> None:
    """
    Prints the DSDL file.
    """
    logging.info(f"{dsdl_file}:{line}: {message}")


def _unittest_public_types_namespaces(public_types: Path) -> None:
    """
    Sanity check to ensure that the public types can be read. This also allows us to debug
    against a real dataset.
    """
    pr = cProfile.Profile()
    pr.enable()
    _ = pydsdl.read_namespace(public_types)
    pr.disable()
    s = io.StringIO()
    sortby = SortKey.TIME
    ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
    ps.print_stats()
    print(s.getvalue())


def _unittest_public_types_files(public_types: Path) -> None:
    """
    Sanity check to ensure that the public types can be read. This also allows us to debug
    against a real dataset.
    """
    pr = cProfile.Profile()
    pr.enable()
    node_types = list(public_types.glob("node/**/*.dsdl"))
    assert(len(node_types) > 0)
    _ = pydsdl.read_files(node_types, {"uavcan"})
    pr.disable()
    s = io.StringIO()
    sortby = SortKey.TIME
    ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
    ps.print_stats()
    print(s.getvalue())
