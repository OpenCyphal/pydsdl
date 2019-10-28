#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import re
import string
from ._serializable import TypeParameterError


class InvalidNameError(TypeParameterError):
    pass


def check_name(name: str) -> None:
    if not name:
        raise InvalidNameError('Name or namespace component cannot be empty')

    if name[0] not in _VALID_FIRST_CHARACTERS_OF_NAME:
        raise InvalidNameError('Name or namespace component cannot start with %r' % name[0])

    for char in name:
        if char not in _VALID_CONTINUATION_CHARACTERS_OF_NAME:
            raise InvalidNameError('Name or namespace component cannot contain %r' % char)

    for pat in _DISALLOWED_NAME_PATTERNS:
        if re.match(pat + '$', name, flags=re.IGNORECASE):
            raise InvalidNameError('Disallowed name: %r matches the following pattern: %s' % (name, pat))


_VALID_FIRST_CHARACTERS_OF_NAME = string.ascii_letters + '_'
_VALID_CONTINUATION_CHARACTERS_OF_NAME = _VALID_FIRST_CHARACTERS_OF_NAME + string.digits

# Disallowed name patterns apply to any part of any name, e.g., an attribute name, a namespace component,
# type name, etc. The pattern must produce an exact match to trigger a name error. All patterns are case-insensitive.
_DISALLOWED_NAME_PATTERNS = [
    r'truncated',
    r'saturated',
    r'true',
    r'false',
    r'bool',
    r'void\d*',
    r'u?int\d*',
    r'u?q\d+_\d+',
    r'float\d*',
    r'optional',
    r'aligned',
    r'const',
    r'struct',
    r'super',
    r'template',
    r'enum',
    r'self',
    r'and',
    r'or',
    r'not',
    r'auto',
    r'type',
    r'con',
    r'prn',
    r'aux',
    r'nul',
    r'com\d',
    r'lpt\d',
    r'_.*_',
]


def _unittest_check_name() -> None:
    from pytest import raises

    check_name('abc')
    check_name('_abc')
    check_name('abc_')
    check_name('abc0')

    with raises(InvalidNameError):
        check_name('0abc')

    with raises(InvalidNameError):
        check_name('_abc_')

    with raises(InvalidNameError):
        check_name('a-bc')

    with raises(InvalidNameError):
        check_name('')

    with raises(InvalidNameError):
        check_name('truncated')

    with raises(InvalidNameError):
        check_name('COM1')

    with raises(InvalidNameError):
        check_name('Aux')

    with raises(InvalidNameError):
        check_name('float128')

    with raises(InvalidNameError):
        check_name('q16_8')

    with raises(InvalidNameError):
        check_name('uq1_32')
