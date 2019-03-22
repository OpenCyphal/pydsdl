#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import sys

if sys.version_info[:2] < (3, 5):   # pragma: no cover
    print('A newer version of Python is required', file=sys.stderr)
    sys.exit(1)

__version__ = 0, 4, 0
__license__ = 'MIT'

# Our unorthodox approach to dependency management requires us to apply certain workarounds.
# Here, the objective is to allow our library to import stuff from its third-party dependency directory,
# but at the same time we don't want to interfere with the application that depends on this library.
# So we modify the import lookup path temporarily while the package initialization is in progress;
# when done, we restore the path back to its original value. One implication is that it won't be possible
# to import stuff dynamically after the initialization is finished (e.g., function-local imports won't be
# able to reach the third-party stuff), but we don't care.
_original_sys_path = sys.path
sys.path = [os.path.join(os.path.dirname(__file__), 'third_party')] + sys.path

# Never import anything that is not available here - API stability guarantees are only provided for the exposed items.
from .namespace import read_namespace
from .namespace import PrintOutputHandler

# Error model.
from .error import FrontendError, InvalidDefinitionError, InternalError

# Data type model - meta types.
from .data_type import DataType
from .data_type import PrimitiveType
from .data_type import BooleanType
from .data_type import ArithmeticType, IntegerType, SignedIntegerType, UnsignedIntegerType, FloatType
from .data_type import VoidType
from .data_type import ArrayType, FixedLengthArrayType, VariableLengthArrayType
from .data_type import CompoundType, UnionType, StructureType, ServiceType

# Data type model - attributes.
from .data_type import Attribute, Field, PaddingField, Constant

# Data type model - auxiliary.
from .data_type import BitLengthRange, ValueRange, Version

# Expression model.
from .expression import Any
from .expression import Primitive, Boolean, Rational, String
from .expression import Container, Set

sys.path = _original_sys_path
