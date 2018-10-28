#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
import tempfile
from .dsdl_parser import parse_definition
from .dsdl_definition import DSDLDefinition


_DIRECTORY = None       # type: typing.Optional[tempfile.TemporaryDirectory]


def _define(rel_path: str, text: str) -> DSDLDefinition:
    assert _DIRECTORY
    path = os.path.join(_DIRECTORY.name, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)

    root_namespace_path = os.path.join(_DIRECTORY.name, rel_path.strip(os.sep).split(os.sep)[0])
    out = DSDLDefinition(path, root_namespace_path)
    print('New definition:', out, 'Root NS:', root_namespace_path)
    return out


def _in_n_out(test: typing.Callable[[], None]) -> typing.Callable[[], None]:
    def decorator() -> None:
        global _DIRECTORY
        _DIRECTORY = tempfile.TemporaryDirectory()
        try:
            test()
        finally:
            _DIRECTORY = None   # Preserving the contents for future inspection if needed

    return decorator


@_in_n_out
def _unittest_define() -> None:
    # I DON'T ALWAYS WRITE UNIT TESTS
    d = _define('uavcan/test/65000.Message.1.2.uavcan', '# empty')
    assert _DIRECTORY is not None
    assert d.name == 'uavcan.test.Message'
    assert d.version == (1, 2)
    assert d.regulated_port_id == 65000
    assert d.file_path == os.path.join(_DIRECTORY.name, 'uavcan/test/65000.Message.1.2.uavcan')
    assert open(d.file_path).read() == '# empty'

    # BUT WHEN I DO, I WRITE UNIT TESTS FOR MY UNIT TESTS
    d = _define('uavcan/Service.255.254.uavcan', '# empty 2')
    assert d.name == 'uavcan.Service'
    assert d.version == (255, 254)
    assert d.regulated_port_id is None
    assert d.file_path == os.path.join(_DIRECTORY.name, 'uavcan/Service.255.254.uavcan')
    assert open(d.file_path).read() == '# empty 2'


@_in_n_out
def _unittest_simple() -> None:
    pass
