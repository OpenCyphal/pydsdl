#
# Copyright (C) 2018-2020  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os as _os
import sys as _sys

__version__ = '1.9.4'
__version_info__ = tuple(map(int, __version__.split('.')))
__license__ = 'MIT'
__author__ = 'UAVCAN Development Team'

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
from ._namespace import read_namespace as read_namespace                            # noqa
from ._namespace import PrintOutputHandler as PrintOutputHandler                    # noqa

# Error model.
from ._error import FrontendError as FrontendError                                  # noqa
from ._error import InvalidDefinitionError as InvalidDefinitionError                # noqa
from ._error import InternalError as InternalError                                  # noqa

# Data type model - meta types.
from ._serializable import SerializableType as SerializableType                     # noqa
from ._serializable import PrimitiveType as PrimitiveType                           # noqa
from ._serializable import BooleanType as BooleanType                               # noqa
from ._serializable import ArithmeticType as ArithmeticType                         # noqa
from ._serializable import IntegerType as IntegerType                               # noqa
from ._serializable import SignedIntegerType as SignedIntegerType                   # noqa
from ._serializable import UnsignedIntegerType as UnsignedIntegerType               # noqa
from ._serializable import FloatType as FloatType                                   # noqa
from ._serializable import VoidType as VoidType                                     # noqa
from ._serializable import ArrayType as ArrayType                                   # noqa
from ._serializable import FixedLengthArrayType as FixedLengthArrayType             # noqa
from ._serializable import VariableLengthArrayType as VariableLengthArrayType       # noqa
from ._serializable import CompositeType as CompositeType                           # noqa
from ._serializable import UnionType as UnionType                                   # noqa
from ._serializable import StructureType as StructureType                           # noqa
from ._serializable import DelimitedType as DelimitedType                           # noqa
from ._serializable import ServiceType as ServiceType                               # noqa

# Data type model - attributes.
from ._serializable import Attribute as Attribute                                   # noqa
from ._serializable import Field as Field                                           # noqa
from ._serializable import PaddingField as PaddingField                             # noqa
from ._serializable import Constant as Constant                                     # noqa

# Expression model.
from ._expression import Any as Any                                                 # noqa
from ._expression import Primitive as Primitive                                     # noqa
from ._expression import Boolean as Boolean                                         # noqa
from ._expression import Rational as Rational                                       # noqa
from ._expression import String as String                                           # noqa
from ._expression import Container as Container                                     # noqa
from ._expression import Set as Set                                                 # noqa

# Auxiliary.
from ._serializable import ValueRange as ValueRange                                 # noqa
from ._serializable import Version as Version                                       # noqa
from ._bit_length_set import BitLengthSet as BitLengthSet                           # noqa

_sys.path = _original_sys_path
