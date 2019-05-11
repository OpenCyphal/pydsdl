#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os as _os
import sys as _sys

# The original intent was to support Python 3.5 and newer; however, we have discovered a bug in the static typing
# library in Python 3.5.2 which makes the library quite unusable: when importing, the typing module would throw
# "TypeError: This Callable type is already parameterized." from the expression module. The problem does not appear
# in Python 3.5.3 or any newer versions; it is fixed in the upstream here: https://github.com/python/typing/pull/308.
# This is how you can reproduce it in REPL; first, the correct behavior that can be observed in Python 3.5.3+:
#   >>> import typing
#   >>> T = typing.TypeVar('T')
#   >>> G = typing.Callable[[], T]
#   >>> G[int]
#   typing.Callable[[], int]
# And this is what you get in Python 3.5.2-:
#   >>> import typing
#   >>> T = typing.TypeVar('T')
#   >>> G = typing.Callable[[], T]
#   >>> G[int]
#   Traceback (most recent call last):
#     File "<stdin>", line 1, in <module>
#     File "/usr/lib/python3.5/typing.py", line 815, in __getitem__
#       raise TypeError("This Callable type is already parameterized.")
#   TypeError: This Callable type is already parameterized.
_min_supported_python_version = 3, 5, 3
if _sys.version_info[:3] < _min_supported_python_version:   # pragma: no cover
    print('This package requires a Python version', '.'.join(map(str, _min_supported_python_version)), 'or newer',
          file=_sys.stderr)
    _sys.exit(1)

__version__ = 0, 8, 1
__license__ = 'MIT'

# Our unorthodox approach to dependency management requires us to apply certain workarounds.
# Here, the objective is to allow our library to import stuff from its third-party dependency directory,
# but at the same time we don't want to interfere with the application that depends on this library.
# So we modify the import lookup path temporarily while the package initialization is in progress;
# when done, we restore the path back to its original value. One implication is that it won't be possible
# to import stuff dynamically after the initialization is finished (e.g., function-local imports won't be
# able to reach the third-party stuff), but we don't care.
_original_sys_path = _sys.path
_sys.path = [_os.path.join(_os.path.dirname(__file__), 'third_party')] + _sys.path

# Never import anything that is not available here - API stability guarantees are only provided for the exposed items.
from ._namespace import read_namespace
from ._namespace import PrintOutputHandler

# Error model.
from ._error import FrontendError, InvalidDefinitionError, InternalError

# Data type model - meta types.
from ._serializable import SerializableType
from ._serializable import PrimitiveType
from ._serializable import BooleanType
from ._serializable import ArithmeticType, IntegerType, SignedIntegerType, UnsignedIntegerType, FloatType
from ._serializable import VoidType
from ._serializable import ArrayType, FixedLengthArrayType, VariableLengthArrayType
from ._serializable import CompositeType, UnionType, StructureType, ServiceType

# Data type model - attributes.
from ._serializable import Attribute, Field, PaddingField, Constant

# Expression model.
from ._expression import Any
from ._expression import Primitive, Boolean, Rational, String
from ._expression import Container, Set

# Auxiliary.
from ._serializable import ValueRange, Version
from ._bit_length_set import BitLengthSet

_sys.path = _original_sys_path
