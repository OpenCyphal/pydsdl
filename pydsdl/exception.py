#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing


class DSDLException(Exception):
    """
    This exception is raised in case of a parser failure.
    Fields:
        path    Source file path where the error has occurred. Optional, will be None if unknown.
        line    Source file line number where the error has occurred. Optional, will be None if unknown.
    """

    def __init__(self, text: str, path: typing.Optional[str]=None, line: typing.Optional[int]=None):
        Exception.__init__(self, text)
        self.path = str(path or '')
        self.line = int(line or 0)

    def __str__(self) -> str:
        """Returns a nicely formatted error string in a GCC-like format (can be parsed by e.g. Eclipse error parser)"""
        if self.path and self.line > 0:
            return '%s:%d: %s' % (self.path, self.line, Exception.__str__(self))

        if self.path:
            return '%s: %s' % (self.path, Exception.__str__(self))

        return Exception.__str__(self)

    def __repr__(self) -> str:
        return self.__class__.__name__ + ': ' + repr(self.__str__())


def _unittest_exception() -> None:
    try:
        raise DSDLException('Hello world!')
    except Exception as ex:
        assert str(ex) == 'Hello world!'
        assert repr(ex) == "DSDLException: 'Hello world!'"

    try:
        raise DSDLException('Hello world!', path='path/to/file.uavcan', line=123)
    except Exception as ex:
        assert str(ex) == 'path/to/file.uavcan:123: Hello world!'
        assert repr(ex) == "DSDLException: 'path/to/file.uavcan:123: Hello world!'"

    try:
        raise DSDLException('Hello world!', path='path/to/file.uavcan')
    except Exception as ex:
        assert str(ex) == 'path/to/file.uavcan: Hello world!'
        assert repr(ex) == "DSDLException: 'path/to/file.uavcan: Hello world!'"
