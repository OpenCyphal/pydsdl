#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import urllib.parse


class ParseError(Exception):       # PEP8 says that the "Exception" suffix is redundant and should not be used.
    """
    This exception is raised in case if the parser discovers an error in the DSDL code, or if it encounters
    an internal failure that can be associated with a particular construct in the DSDL definition.
    This is the base class for all exceptions raised by the parser's inner logic,
    excepting its entry function which also can raise ValueError when provided with incorrect inputs.
    Fields:
        path    Source file path where the error has occurred. Optional, will be None if unknown.
        line    Source file line number where the error has occurred. Optional, will be None if unknown.
                The path is always known if the line number is set.
    """

    def __init__(self,
                 text: str,
                 path: typing.Optional[str]=None,
                 line: typing.Optional[int]=None):
        Exception.__init__(self, text)
        self._path = path
        self._line = line

    def set_error_location_if_unknown(self,
                                      path: typing.Optional[str]=None,
                                      line: typing.Optional[int]=None) -> None:
        if not self._path and path:
            self._path = path

        if not self._line and line:
            self._line = line

    @property
    def path(self) -> typing.Optional[str]:
        return self._path

    @property
    def line(self) -> typing.Optional[int]:
        return self._line

    def __str__(self) -> str:
        """Returns a nicely formatted error string in a GCC-like format (can be parsed by e.g. Eclipse error parser)"""
        if self.path and self.line:
            return '%s:%d: %s' % (self.path, self.line, Exception.__str__(self))

        if self.path:
            return '%s: %s' % (self.path, Exception.__str__(self))

        return Exception.__str__(self)

    def __repr__(self) -> str:
        return self.__class__.__name__ + ': ' + repr(self.__str__())


class InternalError(ParseError):
    """
    This exception is used to report internal errors in the parser itself that prevented it from
    processing the definitions.
    """
    def __init__(self,
                 text: typing.Optional[str]=None,
                 path: typing.Optional[str]=None,
                 line: typing.Optional[int]=None,
                 culprit: typing.Optional[Exception]=None):
        if culprit is not None:
            report_text = 'PLEASE REPORT AT https://github.com/UAVCAN/pydsdl/issues/new?title=' + \
                          urllib.parse.quote(repr(culprit))
            if text:
                text = text + ' ' + report_text
            else:   # pragma: no cover
                text = report_text

        if not text:
            text = ''

        super(InternalError, self).__init__(text=text, path=path, line=line)


class InvalidDefinitionError(ParseError):
    """
    This exception is used to point out mistakes and errors in DSDL definitions.
    """
    pass


def _unittest_error() -> None:
    try:
        raise ParseError('Hello world!')
    except Exception as ex:
        assert str(ex) == 'Hello world!'
        assert repr(ex) == "ParseError: 'Hello world!'"

    try:
        raise ParseError('Hello world!', path='path/to/file.uavcan', line=123)
    except Exception as ex:
        assert str(ex) == 'path/to/file.uavcan:123: Hello world!'
        assert repr(ex) == "ParseError: 'path/to/file.uavcan:123: Hello world!'"

    try:
        raise ParseError('Hello world!', path='path/to/file.uavcan')
    except Exception as ex:
        assert str(ex) == 'path/to/file.uavcan: Hello world!'
        assert repr(ex) == "ParseError: 'path/to/file.uavcan: Hello world!'"


def _unittest_internal_error_github_reporting() -> None:
    try:
        raise InternalError(path='FILE_PATH',
                            line=42)
    except ParseError as ex:
        assert ex.path == 'FILE_PATH'
        assert ex.line == 42
        assert str(ex) == 'FILE_PATH:42: '

    try:
        try:
            try:    # TRY HARDER
                raise InternalError(text='BASE TEXT',
                                    culprit=Exception('ERROR TEXT'))
            except ParseError as ex:
                ex.set_error_location_if_unknown(path='FILE_PATH')
                raise
        except ParseError as ex:
            ex.set_error_location_if_unknown(line=42)
            raise
    except ParseError as ex:
        print(ex)
        assert ex.path == 'FILE_PATH'
        assert ex.line == 42
        # We have to ignore the last couple of characters because Python before 3.7 reprs Exceptions like this:
        #   Exception('ERROR TEXT',)
        # But newer Pythons do it like this:
        #   Exception('ERROR TEXT')
        assert str(ex).startswith(
            'FILE_PATH:42: BASE TEXT '
            'PLEASE REPORT AT https://github.com/UAVCAN/pydsdl/issues/new?title=Exception%28%27ERROR%20TEXT%27'
        )

    try:
        raise InternalError(text='BASE TEXT',
                            path='FILE_PATH')
    except ParseError as ex:
        assert str(ex) == 'FILE_PATH: BASE TEXT'
