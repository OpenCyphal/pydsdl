#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import abc
import typing
from .._bit_length_set import BitLengthSet
from ._serializable import SerializableType, TypeParameterError
from ._primitive import UnsignedIntegerType, PrimitiveType


class InvalidNumberOfElementsError(TypeParameterError):
    pass


class ArrayType(SerializableType):
    def __init__(self,
                 element_type: SerializableType,
                 capacity: int):
        super(ArrayType, self).__init__()
        self._element_type = element_type
        self._capacity = int(capacity)
        if self._capacity < 1:
            raise InvalidNumberOfElementsError('Array capacity cannot be less than 1')

    @property
    def element_type(self) -> SerializableType:
        return self._element_type

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def string_like(self) -> bool:
        """
        Returns True if the array might contain a text string, in which case it is termed to be "string-like".
        A string-like array is a variable-length array of uint8.
        """
        return False

    @abc.abstractmethod
    def _compute_bit_length_set(self) -> BitLengthSet:     # pragma: no cover
        raise NotImplementedError

    @abc.abstractmethod
    def __str__(self) -> str:   # pragma: no cover
        raise NotImplementedError


class FixedLengthArrayType(ArrayType):
    def __init__(self,
                 element_type: SerializableType,
                 capacity: int):
        super(FixedLengthArrayType, self).__init__(element_type, capacity)

    def enumerate_elements_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[int, BitLengthSet]]:
        """
        This is a convenience method for code generation. Its behavior mimics that of iterate_fields_with_offsets()
        for structure types, except that we iterate indexes instead of fields since we don't have fields in arrays.
        For each element in the fixed array we return its index and the offset represented as a bit length set
        counting from the supplied base. If the base is not supplied, it is assumed to equal {0}.
        """
        base_offset = BitLengthSet(base_offset or 0)
        _self_test_base_offset = BitLengthSet(0)
        for index in range(self.capacity):
            yield index, BitLengthSet(base_offset)      # We yield a copy of the offset to prevent mutation
            base_offset.increment(self.element_type.bit_length_set)

            # This is only for ensuring that the logic is functioning as intended.
            # Combinatorial transformations are easy to mess up, so we have to employ defensive programming.
            assert self.element_type.bit_length_set.elementwise_sum_k_multicombinations(index) == _self_test_base_offset
            _self_test_base_offset.increment(self.element_type.bit_length_set)

    def _compute_bit_length_set(self) -> BitLengthSet:
        # This can be further generalized as a Cartesian product of the element type's bit length set taken N times,
        # where N is the capacity of the array. However, we avoid such generalization because it leads to a mild
        # combinatorial explosion even with small arrays, resorting to this special case instead. The difference in
        # performance measured on the standard data type set was about tenfold.
        return self.element_type.bit_length_set.elementwise_sum_k_multicombinations(self.capacity)

    def __str__(self) -> str:
        return '%s[%d]' % (self.element_type, self.capacity)

    def __repr__(self) -> str:
        return 'FixedLengthArrayType(element_type=%r, capacity=%r)' % (self.element_type, self.capacity)


def _unittest_fixed_array() -> None:
    from pytest import raises
    from ._primitive import SignedIntegerType

    su8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    ti64 = SignedIntegerType(64, cast_mode=PrimitiveType.CastMode.SATURATED)

    assert str(FixedLengthArrayType(su8, 4)) == 'truncated uint8[4]'
    assert str(FixedLengthArrayType(ti64, 1)) == 'saturated int64[1]'

    assert not FixedLengthArrayType(su8, 4).string_like
    assert not FixedLengthArrayType(ti64, 1).string_like

    assert FixedLengthArrayType(su8, 4).bit_length_set == 32
    assert FixedLengthArrayType(su8, 200).capacity == 200
    assert FixedLengthArrayType(ti64, 200).element_type is ti64

    with raises(InvalidNumberOfElementsError):
        FixedLengthArrayType(ti64, 0)

    assert repr(FixedLengthArrayType(ti64, 128)) == \
        'FixedLengthArrayType(element_type=SignedIntegerType(bit_length=64, cast_mode=<CastMode.SATURATED: 0>), ' \
        'capacity=128)'

    small = FixedLengthArrayType(su8, 2)
    assert small.bit_length_set == {16}
    assert list(small.enumerate_elements_with_offsets()) == [(0, BitLengthSet(0)), (1, BitLengthSet(8))]


class VariableLengthArrayType(ArrayType):
    def __init__(self,
                 element_type: SerializableType,
                 capacity: int):
        super(VariableLengthArrayType, self).__init__(element_type, capacity)
        # Construct once to allow reference equality checks
        self._length_field_type = UnsignedIntegerType(self.capacity.bit_length(), PrimitiveType.CastMode.TRUNCATED)

    @property
    def string_like(self) -> bool:
        et = self.element_type      # Without this temporary MyPy yields a false positive type error
        return isinstance(et, UnsignedIntegerType) and (et.bit_length == 8)

    @property
    def length_field_type(self) -> UnsignedIntegerType:
        """
        Returns the best-matching unsigned integer type of the implicit array length field.
        This is convenient for code generation.
        WARNING: the set of valid length values is a subset of that of the returned type.
        """
        return self._length_field_type

    def _compute_bit_length_set(self) -> BitLengthSet:
        # Please refer to the corresponding implementation for the fixed-length array.
        # The idea here is that we treat the variable-length array as a combination of fixed-length arrays of
        # different sizes, from zero elements up to the maximum number of elements.
        output = BitLengthSet()
        for capacity in range(self.capacity + 1):
            case = self.element_type.bit_length_set.elementwise_sum_k_multicombinations(capacity)
            output.unite_with(case)
        # Add the bit length of the implicit array length field.
        output.increment(self.length_field_type.bit_length)
        return output

    def __str__(self) -> str:
        return '%s[<=%d]' % (self.element_type, self.capacity)

    def __repr__(self) -> str:
        return 'VariableLengthArrayType(element_type=%r, capacity=%r)' % (self.element_type, self.capacity)


def _unittest_variable_array() -> None:
    from pytest import raises
    from ._primitive import SignedIntegerType

    tu8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    si64 = SignedIntegerType(64, cast_mode=PrimitiveType.CastMode.SATURATED)

    assert str(VariableLengthArrayType(tu8, 4)) == 'truncated uint8[<=4]'
    assert str(VariableLengthArrayType(si64, 255)) == 'saturated int64[<=255]'

    assert VariableLengthArrayType(tu8, 4).string_like
    assert not VariableLengthArrayType(si64, 1).string_like

    # Mind the length prefix!
    assert VariableLengthArrayType(tu8, 3).bit_length_set == {2, 10, 18, 26}
    assert VariableLengthArrayType(tu8, 1).bit_length_set == {1, 9}
    assert max(VariableLengthArrayType(tu8, 255).bit_length_set) == 2048

    assert VariableLengthArrayType(tu8, 200).capacity == 200
    assert VariableLengthArrayType(tu8, 200).element_type is tu8

    with raises(InvalidNumberOfElementsError):
        VariableLengthArrayType(si64, 0)

    assert repr(VariableLengthArrayType(si64, 128)) == \
        'VariableLengthArrayType(element_type=SignedIntegerType(bit_length=64, cast_mode=<CastMode.SATURATED: 0>), ' \
        'capacity=128)'

    # The following was computed manually; it is easy to validate:
    # we have zero, one, or two elements of 8 bits each; plus 2 bit wide tag; therefore:
    # {2 + 0, 2 + 8, 2 + 16}
    small = VariableLengthArrayType(tu8, 2)
    assert small.bit_length_set == {2, 10, 18}

    # This one gets a little tricky, so pull out a piece of paper an a pencil.
    # So the nested type, as defined above, has the following set: {2, 10, 18}.
    # We can have up to two elements of that type, so what we get can be expressed graphically as follows:
    #    A   B | +
    # ---------+------
    #    2   2 |  4
    #   10   2 | 12
    #   18   2 | 20
    #    2  10 | 12
    #   10  10 | 20
    #   18  10 | 28
    #    2  18 | 20
    #   10  18 | 28
    #   18  18 | 36
    #
    # If we were to remove duplicates, we end up with: {4, 12, 20, 28, 36}
    outer = FixedLengthArrayType(small, 2)
    assert outer.bit_length_set == {4, 12, 20, 28, 36}
