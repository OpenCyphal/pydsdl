#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing


BitLengthRange = typing.NamedTuple('BitLengthRange', [('min', int), ('max', int)])


class DataType:
    @property
    def bit_length_range(self) -> BitLengthRange:
        raise NotImplementedError


class PrimitiveType(DataType):
    pass


class ArrayType(DataType):
    pass


class StaticArrayType(ArrayType):
    pass


class DynamicArrayType(ArrayType):
    pass


class CompoundType(DataType):
    pass


class UnionType(CompoundType):
    pass


class StructureType(CompoundType):
    pass
