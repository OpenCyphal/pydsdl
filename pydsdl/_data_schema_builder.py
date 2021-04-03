# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import typing
from . import _error
from . import _serializable
from . import _bit_length_set


class BitLengthAnalysisError(_error.InvalidDefinitionError):
    pass


class SerializationMode:
    """Serialization mode: either delimited (with extent) or sealed."""

    def __str__(self) -> str:
        raise NotImplementedError


class DelimitedSerializationMode(SerializationMode):
    def __init__(self, extent: int):
        self.extent = int(extent)

    def __str__(self) -> str:
        return "delimited (extent %d bits)" % self.extent


class SealedSerializationMode(SerializationMode):
    def __str__(self) -> str:
        return "sealed"


class DataSchemaBuilder:
    def __init__(self) -> None:
        self._fields = []  # type: typing.List[_serializable.Field]
        self._constants = []  # type: typing.List[_serializable.Constant]
        self._serialization_mode = None  # type: typing.Optional[SerializationMode]
        self._is_union = False
        self._bit_length_computed_at_least_once = False
        self._doc = ""

    @property
    def fields(self) -> typing.List[_serializable.Field]:
        assert all(map(lambda x: isinstance(x, _serializable.Field), self._fields))
        return self._fields

    @property
    def constants(self) -> typing.List[_serializable.Constant]:
        assert all(map(lambda x: isinstance(x, _serializable.Constant), self._constants))
        return self._constants

    @property
    def attributes(self) -> typing.List[_serializable.Attribute]:  # noinspection PyTypeChecker
        out = []  # type: typing.List[_serializable.Attribute]
        out += self.fields
        out += self.constants
        return out

    @property
    def doc(self) -> str:
        return self._doc

    @property
    def serialization_mode(self) -> typing.Optional[SerializationMode]:
        return self._serialization_mode

    @property
    def union(self) -> bool:
        return self._is_union

    @property
    def offset(self) -> _bit_length_set.BitLengthSet:
        # We set this flag in order to detect invalid reliance on the bit length estimates for unions:
        # we process definitions sequentially, statement-by-statement, so we can't know if there are going to be
        # extra fields added after the bit length values are computed. If we are building a regular structure,
        # this is fine, because in that case each computed value refers to the offset of the next field (if there
        # is one) or the total length of the structure (if we're past the last field). With unions, however,
        # there is no concept of inter-field offset because a union holds exactly one field at any moment;
        # only the total offset (i.e., total size) is defined.
        self._bit_length_computed_at_least_once = True
        ty = _serializable.UnionType if self.union else _serializable.StructureType
        out = ty.aggregate_bit_length_sets([f.data_type for f in self.fields])  # type: ignore
        assert isinstance(out, _bit_length_set.BitLengthSet) and len(out) > 0
        return out

    def set_comment(self, comment: str) -> None:
        self._doc = comment

    def add_field(self, field: _serializable.Field) -> None:
        if self.union and self._bit_length_computed_at_least_once:
            # Refer to the DSDL specification for the background information.
            raise BitLengthAnalysisError(
                "Inter-field offset is not defined for unions; " "previously performed bit length analysis is invalid"
            )
        assert isinstance(field, _serializable.Field)
        self._fields.append(field)

    def add_constant(self, constant: _serializable.Constant) -> None:
        assert isinstance(constant, _serializable.Constant)
        self._constants.append(constant)

    def set_serialization_mode(self, mode: SerializationMode) -> None:
        assert self._serialization_mode is None
        self._serialization_mode = mode

    def make_union(self) -> None:
        assert not self.union
        self._is_union = True
