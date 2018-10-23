#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
from .dsdl_definition import DSDLDefinition
from .data_type import BooleanType, SignedIntegerType, UnsignedIntegerType, FloatType, VoidType
from .data_type import StaticArrayType, DynamicArrayType, CompoundType, UnionType, StructureType, ServiceType


def parse_definition(definition: DSDLDefinition,
                     lookup_definitions: typing.List[DSDLDefinition]) -> CompoundType:
    pass
