# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import re
import string
import typing  # pylint: disable=W0611
from ._serializable import TypeParameterError


class InvalidNameError(TypeParameterError):
    pass


def check_name(name: str) -> None:
    """
    Ensure that the name complies with the requirements set out in the Specification;
    raise :class:`InvalidNameError` if not.
    """
    if not name:
        raise InvalidNameError("Name or namespace component cannot be empty")

    name = name.lower()

    if name[0] not in _VALID_FIRST_CHARACTERS_OF_NAME:
        raise InvalidNameError("Name or namespace component cannot start with %r" % name[0])

    for char in name:
        if char not in _VALID_CONTINUATION_CHARACTERS_OF_NAME:
            raise InvalidNameError("Name or namespace component cannot contain %r" % char)

    for pat in _DISALLOWED_NAME_PATTERNS:
        if isinstance(pat, str):
            if pat == name:
                raise InvalidNameError("Disallowed name: %r matches the following string: %s" % (name, pat))
        elif pat.match(name):
            raise InvalidNameError("Disallowed name: %r matches the following pattern: %s" % (name, pat))


_VALID_FIRST_CHARACTERS_OF_NAME = string.ascii_letters + "_"
_VALID_CONTINUATION_CHARACTERS_OF_NAME = _VALID_FIRST_CHARACTERS_OF_NAME + string.digits

# Disallowed name patterns apply to any part of any name, e.g., an attribute name, a namespace component,
# type name, etc. The pattern must produce an exact match to trigger a name error. All patterns are case-insensitive.
_DISALLOWED_NAME_PATTERNS = [
    "truncated",
    "saturated",
    "true",
    "false",
    "bool",
    re.compile(r"void\d*$"),
    re.compile(r"u?int\d*$"),
    re.compile(r"u?q\d+_\d+$"),
    re.compile(r"float\d*$"),
    "optional",
    "aligned",
    "const",
    "struct",
    "super",
    "template",
    "enum",
    "self",
    "and",
    "or",
    "not",
    "auto",
    "type",
    "con",
    "prn",
    "aux",
    "nul",
    re.compile(r"com\d$"),
    re.compile(r"lpt\d$"),
    re.compile(r"_.*_$"),
]  # type: typing.List[typing.Union[str, typing.Pattern[str]]]


def _unittest_check_name() -> None:
    from pytest import raises

    check_name("abc")
    check_name("_abc")
    check_name("abc_")
    check_name("abc0")

    with raises(InvalidNameError):
        check_name("0abc")

    with raises(InvalidNameError):
        check_name("_abc_")

    with raises(InvalidNameError):
        check_name("a-bc")

    with raises(InvalidNameError):
        check_name("")

    with raises(InvalidNameError):
        check_name("truncated")

    with raises(InvalidNameError):
        check_name("COM1")

    with raises(InvalidNameError):
        check_name("Aux")

    with raises(InvalidNameError):
        check_name("float128")

    with raises(InvalidNameError):
        check_name("q16_8")

    with raises(InvalidNameError):
        check_name("uq1_32")
