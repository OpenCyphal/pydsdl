# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import abc
import math
import typing
from .._bit_length_set import BitLengthSet
from ._serializable import SerializableType, TypeParameterError
from ._primitive import UnsignedIntegerType, PrimitiveType


class InvalidNumberOfElementsError(TypeParameterError):
    pass


class ArrayType(SerializableType):
    def __init__(self, element_type: SerializableType, capacity: int):
        super().__init__()
        self._element_type = element_type
        self._capacity = int(capacity)
        if self._capacity < 1:
            raise InvalidNumberOfElementsError("Array capacity cannot be less than 1")

    @property
    def element_type(self) -> SerializableType:
        return self._element_type

    @property
    def capacity(self) -> int:
        """
        The (maximum) number of elements in the (variable-length) array.
        """
        return self._capacity

    @property
    def string_like(self) -> bool:
        """
        True if the array might contain a text string, in which case it is termed to be "string-like".
        A string-like array is a variable-length array of ``uint8``.
        See https://github.com/UAVCAN/specification/issues/51.
        """
        return False

    @property
    def alignment_requirement(self) -> int:
        """
        The alignment requirement of an array equals that of its element type.
        The length of the serialized representation of any type is a multiple of its alignment requirement;
        therefore, every element is always placed such that its alignment requirement is satisfied.
        """
        return self.element_type.alignment_requirement

    @abc.abstractmethod
    def __str__(self) -> str:  # pragma: no cover
        raise NotImplementedError


class FixedLengthArrayType(ArrayType):
    def __init__(self, element_type: SerializableType, capacity: int):
        super().__init__(element_type, capacity)
        self._bls = self.element_type.bit_length_set.repeat(self.capacity)
        assert self._bls.is_aligned_at(self.alignment_requirement)

    @property
    def bit_length_set(self) -> BitLengthSet:
        return self._bls

    def enumerate_elements_with_offsets(
        self, base_offset: BitLengthSet = BitLengthSet(0)
    ) -> typing.Iterator[typing.Tuple[int, BitLengthSet]]:
        """
        This is a convenience method for code generation.
        Its behavior mimics that of :meth:`pydsdl.StructureType.iterate_fields_with_offsets`,
        except that we iterate over indexes instead of fields.

        :param base_offset: The base offset to add to each element. If not supplied, assumed to be ``{0}``.
            The base offset will be implicitly padded out to :attr:`alignment_requirement`.

        :returns: For an N-element array, an iterator over N elements, where each element is a tuple of the index
            of the array element (zero-based) and its offset as a bit length set.
        """
        base_offset = base_offset.pad_to_alignment(self.alignment_requirement)
        for index in range(self.capacity):
            offset = base_offset + self.element_type.bit_length_set.repeat(index)
            assert offset.is_aligned_at(self.element_type.alignment_requirement)
            yield index, offset

    def __str__(self) -> str:
        return "%s[%d]" % (self.element_type, self.capacity)

    def __repr__(self) -> str:
        return "FixedLengthArrayType(element_type=%r, capacity=%r)" % (self.element_type, self.capacity)


def _unittest_fixed_array() -> None:
    from pytest import raises
    from ._primitive import SignedIntegerType

    su8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    ti64 = SignedIntegerType(64, cast_mode=PrimitiveType.CastMode.SATURATED)

    assert str(FixedLengthArrayType(su8, 4)) == "truncated uint8[4]"
    assert str(FixedLengthArrayType(ti64, 1)) == "saturated int64[1]"

    assert not FixedLengthArrayType(su8, 4).string_like
    assert not FixedLengthArrayType(ti64, 1).string_like

    assert FixedLengthArrayType(su8, 4).bit_length_set == 32
    assert FixedLengthArrayType(su8, 200).capacity == 200
    assert FixedLengthArrayType(ti64, 200).element_type is ti64

    with raises(InvalidNumberOfElementsError):
        FixedLengthArrayType(ti64, 0)

    assert (
        repr(FixedLengthArrayType(ti64, 128))
        == "FixedLengthArrayType(element_type=SignedIntegerType(bit_length=64, cast_mode=<CastMode.SATURATED: 0>), "
        "capacity=128)"
    )

    small = FixedLengthArrayType(su8, 2)
    assert small.bit_length_set == {16}
    assert list(small.enumerate_elements_with_offsets()) == [(0, BitLengthSet(0)), (1, BitLengthSet(8))]


class VariableLengthArrayType(ArrayType):
    def __init__(self, element_type: SerializableType, capacity: int):
        super().__init__(element_type, capacity)

        # Construct the implicit array length prefix type.
        length_field_length = 2 ** math.ceil(math.log2(max(self.BITS_PER_BYTE, self.capacity.bit_length())))

        # If the length field is less than the alignment requirement (which, at the time of writing this,
        # is not possible because the max alignment is 8 and the min length length is also 8),
        # it would break the alignment of the array elements. Hence, we ensure that it is never smaller.
        length_field_length = max(length_field_length, self.alignment_requirement)
        assert length_field_length % self.element_type.alignment_requirement == 0

        self._length_field_type = UnsignedIntegerType(length_field_length, PrimitiveType.CastMode.TRUNCATED)

        self._bls = self.length_field_type.bit_length + self.element_type.bit_length_set.repeat_range(self.capacity)
        assert self._bls.is_aligned_at(self.alignment_requirement)

    @property
    def bit_length_set(self) -> BitLengthSet:
        assert self._bls.is_aligned_at(self.alignment_requirement)
        return self._bls

    @property
    def string_like(self) -> bool:
        """See the base class."""
        et = self.element_type  # Without this temporary MyPy yields a false positive type error
        return isinstance(et, UnsignedIntegerType) and (et.bit_length == self.BITS_PER_BYTE)

    @property
    def length_field_type(self) -> UnsignedIntegerType:
        """
        The unsigned integer type of the implicit array length field.
        Note that the set of valid length values is a subset of that of the returned type.
        """
        assert self._length_field_type.bit_length % self.element_type.alignment_requirement == 0
        return self._length_field_type

    def __str__(self) -> str:
        return "%s[<=%d]" % (self.element_type, self.capacity)

    def __repr__(self) -> str:
        return "VariableLengthArrayType(element_type=%r, capacity=%r)" % (self.element_type, self.capacity)


def _unittest_variable_array() -> None:
    from pytest import raises
    from ._primitive import SignedIntegerType

    tu8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    si64 = SignedIntegerType(64, cast_mode=PrimitiveType.CastMode.SATURATED)

    assert str(VariableLengthArrayType(tu8, 4)) == "truncated uint8[<=4]"
    assert str(VariableLengthArrayType(si64, 255)) == "saturated int64[<=255]"

    assert VariableLengthArrayType(tu8, 4).string_like
    assert not VariableLengthArrayType(si64, 1).string_like

    # Mind the length prefix!
    assert VariableLengthArrayType(tu8, 3).bit_length_set == {8, 16, 24, 32}
    assert VariableLengthArrayType(tu8, 1).bit_length_set == {8, 16}
    assert max(VariableLengthArrayType(tu8, 255).bit_length_set) == 2048

    assert VariableLengthArrayType(tu8, 200).capacity == 200
    assert VariableLengthArrayType(tu8, 200).element_type is tu8

    with raises(InvalidNumberOfElementsError):
        VariableLengthArrayType(si64, 0)

    assert (
        repr(VariableLengthArrayType(si64, 128))
        == "VariableLengthArrayType(element_type=SignedIntegerType(bit_length=64, cast_mode=<CastMode.SATURATED: 0>), "
        "capacity=128)"
    )

    small = VariableLengthArrayType(tu8, 2)
    assert small.bit_length_set == {8, 16, 24}

    outer = FixedLengthArrayType(small, 2)
    assert outer.bit_length_set == {16, 24, 32, 40, 48}

    assert VariableLengthArrayType(tu8, 100).length_field_type.bit_length == 8
    assert VariableLengthArrayType(tu8, 10000).length_field_type.bit_length == 16
    assert VariableLengthArrayType(tu8, 1000000).length_field_type.bit_length == 32
    assert VariableLengthArrayType(tu8, 10000000000).length_field_type.bit_length == 64
