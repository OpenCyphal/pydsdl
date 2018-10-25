#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
from .dsdl_definition import DSDLDefinition
from .data_type import BooleanType, SignedIntegerType, UnsignedIntegerType, FloatType, VoidType
from .data_type import StaticArrayType, DynamicArrayType, CompoundType, UnionType, StructureType, ServiceType
from .port_id_ranges import is_valid_regulated_service_id, is_valid_regulated_subject_id


def parse_definition(definition: DSDLDefinition,
                     lookup_definitions: typing.List[DSDLDefinition]) -> CompoundType:
    pass
