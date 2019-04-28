#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
from . import _error
from . import _serializable
from . import _bit_length_set


class BitLengthAnalysisError(_error.InvalidDefinitionError):
    pass


class DataSchemaBuilder:
    def __init__(self) -> None:
        self._fields = []       # type: typing.List[_serializable.Field]
        self._constants = []    # type: typing.List[_serializable.Constant]
        self._is_union = False
        self._bit_length_computed_at_least_once = False

    def add_field(self, field: _serializable.Field) -> None:
        if self.union and self._bit_length_computed_at_least_once:
            # Refer to the DSDL specification for the background information.
            raise BitLengthAnalysisError('Inter-field offset is not defined for unions; '
                                         'previously performed bit length analysis is invalid')
        assert isinstance(field, _serializable.Field)
        self._fields.append(field)

    def add_constant(self, constant: _serializable.Constant) -> None:
        assert isinstance(constant, _serializable.Constant)
        self._constants.append(constant)

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
    def empty(self) -> bool:
        return not self._fields and not self._constants

    @property
    def union(self) -> bool:
        return self._is_union

    def make_union(self) -> None:
        assert not self.union, 'This operation is not idempotent'
        self._is_union = True

    @property
    def bit_length_set(self) -> _bit_length_set.BitLengthSet:     # oh mypy, why are you so stupid
        # We set this flag in order to detect invalid reliance on the bit length estimates for unions:
        # we process definitions sequentially, statement-by-statement, so we can't know if there are going to be
        # extra fields added after the bit length values are computed. If we are building a regular structure,
        # this is fine, because in that case each computed value refers to the offset of the next field (if there
        # is one) or the total length of the structure (if we're past the last field). With unions, however,
        # there is no concept of inter-field offset because a union holds exactly one field at any moment;
        # only the total offset (i.e., total size) is defined.
        self._bit_length_computed_at_least_once = True

        field_bls_gen = map(lambda f: f.data_type.bit_length_set, self.fields)
        if self.union:
            out = _bit_length_set.BitLengthSet.for_tagged_union(field_bls_gen)
        else:
            out = _bit_length_set.BitLengthSet.for_struct(field_bls_gen)

        assert isinstance(out, _bit_length_set.BitLengthSet) and len(out) > 0
        return out
