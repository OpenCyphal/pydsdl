# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

# pylint: disable=wrong-import-position

import os as _os
import sys as _sys

__version__ = "1.12.1"
__version_info__ = tuple(map(int, __version__.split(".")[:3]))
__license__ = "MIT"
__author__ = "UAVCAN Consortium"
__copyright__ = "Copyright (c) 2018 UAVCAN Consortium"
__email__ = "consortium@uavcan.org"

# Our unorthodox approach to dependency management requires us to apply certain workarounds.
# Here, the objective is to allow our library to import stuff from its third-party dependency directory,
# but at the same time we don't want to interfere with the application that depends on this library.
# So we modify the import lookup path temporarily while the package initialization is in progress;
# when done, we restore the path back to its original value. One implication is that it won't be possible
# to import stuff dynamically after the initialization is finished (e.g., function-local imports won't be
# able to reach the third-party stuff), but we don't care.
_original_sys_path = _sys.path
_sys.path = [_os.path.join(_os.path.dirname(__file__), "third_party")] + _sys.path

# Never import anything that is not available here - API stability guarantees are only provided for the exposed items.
from ._namespace import read_namespace as read_namespace
from ._namespace import PrintOutputHandler as PrintOutputHandler

# Error model.
from ._error import FrontendError as FrontendError
from ._error import InvalidDefinitionError as InvalidDefinitionError
from ._error import InternalError as InternalError

# Data type model - meta types.
from ._serializable import SerializableType as SerializableType
from ._serializable import PrimitiveType as PrimitiveType
from ._serializable import BooleanType as BooleanType
from ._serializable import ArithmeticType as ArithmeticType
from ._serializable import IntegerType as IntegerType
from ._serializable import SignedIntegerType as SignedIntegerType
from ._serializable import UnsignedIntegerType as UnsignedIntegerType
from ._serializable import FloatType as FloatType
from ._serializable import VoidType as VoidType
from ._serializable import ArrayType as ArrayType
from ._serializable import FixedLengthArrayType as FixedLengthArrayType
from ._serializable import VariableLengthArrayType as VariableLengthArrayType
from ._serializable import CompositeType as CompositeType
from ._serializable import UnionType as UnionType
from ._serializable import StructureType as StructureType
from ._serializable import DelimitedType as DelimitedType
from ._serializable import ServiceType as ServiceType

# Data type model - attributes.
from ._serializable import Attribute as Attribute
from ._serializable import Field as Field
from ._serializable import PaddingField as PaddingField
from ._serializable import Constant as Constant

# Expression model.
from ._expression import Any as Any
from ._expression import Primitive as Primitive
from ._expression import Boolean as Boolean
from ._expression import Rational as Rational
from ._expression import String as String
from ._expression import Container as Container
from ._expression import Set as Set

# Auxiliary.
from ._serializable import ValueRange as ValueRange
from ._serializable import Version as Version
from ._bit_length_set import BitLengthSet as BitLengthSet

_sys.path = _original_sys_path
