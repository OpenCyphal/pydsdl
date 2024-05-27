# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

# pylint: disable=broad-except

import typing
from pathlib import Path
import urllib.parse


class FrontendError(Exception):  # PEP8 says that the "Exception" suffix is redundant and should not be used.
    """
    This is the root exception type for all custom exceptions defined in the library.
    This type itself is not expected to be particularly useful to the library user;
    please refer to the direct descendants instead.
    """

    def __init__(self, text: str, path: typing.Optional[Path] = None, line: typing.Optional[int] = None):
        Exception.__init__(self, text)
        self._path = path
        self._line = line

    def set_error_location_if_unknown(
        self, path: typing.Optional[Path] = None, line: typing.Optional[int] = None
    ) -> None:
        """
        Entries that are already known will be left unchanged.
        This is useful when propagating exceptions through recursive instances,
        e.g., when processing nested definitions.
        """
        if not self._path and path:
            self._path = path

        if not self._line and line:
            self._line = line

    @property
    def path(self) -> typing.Optional[Path]:
        """Source file path where the error has occurred, if known."""
        return self._path

    @property
    def line(self) -> typing.Optional[int]:
        """
        Source file line number (first line numbered 1) where the error has occurred, if known.
        The path is always known if the line number is set.
        """
        return self._line

    @property
    def text(self) -> str:
        return Exception.__str__(self)

    def __str__(self) -> str:
        """
        Nicely formats an error string in the typical error format ``[file:[line:]]description``.
        Example::

            uavcan/internet/udp/500.HandleIncomingPacket.1.0.dsdl:33: Error such and such
        """
        if self.path and self.line:
            return "%s:%d: %s" % (self.path.as_posix(), self.line, self.text)

        if self.path:
            return "%s: %s" % (self.path.as_posix(), self.text)

        return self.text

    def __repr__(self) -> str:
        return self.__class__.__name__ + ": " + repr(self.__str__())


class InternalError(FrontendError):
    """
    This exception is used to report internal errors in the front end itself that prevented it from
    processing the definitions. Every occurrence should be reported to the developers.
    """

    def __init__(
        self,
        text: typing.Optional[str] = None,
        path: typing.Optional[Path] = None,
        line: typing.Optional[int] = None,
        culprit: typing.Optional[Exception] = None,
    ):
        if culprit is not None:
            report_text = (
                "PLEASE REPORT AT https://github.com/OpenCyphal/pydsdl/issues/new?title="
                + urllib.parse.quote(repr(culprit))
            )
            if text:
                text = text + " " + report_text
            else:  # pragma: no cover
                text = report_text

        if not text:
            text = ""

        super().__init__(text=text, path=path, line=line)


class InvalidDefinitionError(FrontendError):
    """
    This exception type is used to point out mistakes and errors in DSDL definitions.
    This type is inherited by a dozen of specialized exception types; however, the class hierarchy beneath
    this type may be unstable and should not be relied upon by the application directly.
    """


def _unittest_error() -> None:
    try:
        raise FrontendError("Hello world!")
    except Exception as ex:
        assert str(ex) == "Hello world!"
        assert repr(ex) == "FrontendError: 'Hello world!'"

    try:
        raise FrontendError("Hello world!", path=Path("path/to/file.dsdl"), line=123)
    except Exception as ex:
        assert str(ex) == "path/to/file.dsdl:123: Hello world!"
        assert repr(ex) == "FrontendError: 'path/to/file.dsdl:123: Hello world!'"

    try:
        raise FrontendError("Hello world!", path=Path("path/to/file.dsdl"))
    except Exception as ex:
        assert str(ex) == "path/to/file.dsdl: Hello world!"
        assert repr(ex) == "FrontendError: 'path/to/file.dsdl: Hello world!'"


def _unittest_internal_error_github_reporting() -> None:
    try:
        raise InternalError(path=Path("FILE_PATH"), line=42)
    except FrontendError as ex:
        assert ex.path == Path("FILE_PATH")
        assert ex.line == 42
        assert str(ex) == "FILE_PATH:42: "

    try:
        try:
            try:  # TRY HARDER
                raise InternalError(text="BASE TEXT", culprit=Exception("ERROR TEXT"))
            except FrontendError as ex:
                ex.set_error_location_if_unknown(path=Path("FILE_PATH"))
                raise
        except FrontendError as ex:
            ex.set_error_location_if_unknown(line=42)
            raise
    except FrontendError as ex:
        print(ex)
        assert ex.path == Path("FILE_PATH")
        assert ex.line == 42
        # We have to ignore the last couple of characters because Python before 3.7 reprs Exceptions like this:
        #   Exception('ERROR TEXT',)
        # But newer Pythons do it like this:
        #   Exception('ERROR TEXT')
        assert str(ex).startswith(
            "FILE_PATH:42: BASE TEXT "
            "PLEASE REPORT AT https://github.com/OpenCyphal/pydsdl/issues/new?title=Exception%28%27ERROR%20TEXT%27"
        )

    try:
        raise InternalError(text="BASE TEXT", path=Path("FILE_PATH"))
    except FrontendError as ex:
        assert str(ex) == "FILE_PATH: BASE TEXT"
