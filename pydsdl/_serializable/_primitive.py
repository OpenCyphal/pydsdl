# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

# mypy: warn_unused_ignores=False

import abc
import enum
import math
import typing
import fractions
from .._bit_length_set import BitLengthSet
from ._serializable import SerializableType, TypeParameterError, AggregationFailure


ValueRange = typing.NamedTuple("ValueRange", [("min", fractions.Fraction), ("max", fractions.Fraction)])


class InvalidBitLengthError(TypeParameterError):
    pass


class InvalidCastModeError(TypeParameterError):
    pass


class PrimitiveType(SerializableType):
    MAX_BIT_LENGTH = 64
    BITS_IN_BYTE = 8  # Defined in the Cyphal specification

    class CastMode(enum.Enum):
        SATURATED = 0
        TRUNCATED = 1

    def __init__(self, bit_length: int, cast_mode: "PrimitiveType.CastMode"):
        super().__init__()
        self._bit_length = int(bit_length)
        self._cast_mode = cast_mode

        if self._bit_length < 1:
            raise InvalidBitLengthError("Bit length must be positive")

        if self._bit_length > self.MAX_BIT_LENGTH:
            raise InvalidBitLengthError("Bit length cannot exceed %r" % self.MAX_BIT_LENGTH)

        self._standard_bit_length = (self._bit_length >= self.BITS_IN_BYTE) and (
            2 ** round(math.log2(self._bit_length)) == self._bit_length
        )

    @property
    def bit_length_set(self) -> BitLengthSet:
        return BitLengthSet(self.bit_length)

    @property
    def deprecated(self) -> bool:
        """Primitive types cannot be deprecated."""
        return False

    def _check_aggregation(self, aggregate: "SerializableType") -> typing.Optional[AggregationFailure]:
        return super()._check_aggregation(aggregate)

    @property
    def bit_length(self) -> int:
        """
        This is a shortcut for ``next(iter(x.bit_length_set))``, because the bit length set of a primitive type
        always contains exactly one element (i.e., primitive types are fixed-length).
        """
        return self._bit_length

    @property
    def standard_bit_length(self) -> bool:
        """
        The term "standard length" here means that values of such bit length are commonly used in modern computer
        microarchitectures, such as ``uint8``, ``float64``, ``int32``, and so on. Booleans are excluded.
        More precisely, a primitive is said to be "standard length" when the following hold::

            bit_length >= 8
            2**ceil(log2(bit_length)) == bit_length.
        """
        return self._standard_bit_length

    @property
    def cast_mode(self) -> "PrimitiveType.CastMode":
        return self._cast_mode

    @property
    def alignment_requirement(self) -> int:
        return 1

    @property
    def _cast_mode_name(self) -> str:
        """For internal use only."""
        return {
            self.CastMode.SATURATED: "saturated",
            self.CastMode.TRUNCATED: "truncated",
        }[self.cast_mode]

    @abc.abstractmethod
    def __str__(self) -> str:  # pragma: no cover
        raise NotImplementedError

    def __repr__(self) -> str:
        return "%s(bit_length=%r, cast_mode=%r)" % (self.__class__.__name__, self.bit_length, self.cast_mode)


class BooleanType(PrimitiveType):
    def __init__(self) -> None:
        super().__init__(bit_length=1, cast_mode=PrimitiveType.CastMode.SATURATED)

    def __str__(self) -> str:
        return "bool"


class ArithmeticType(PrimitiveType):
    def __init__(self, bit_length: int, cast_mode: PrimitiveType.CastMode):
        super().__init__(bit_length, cast_mode)

    @property
    @abc.abstractmethod
    def inclusive_value_range(self) -> ValueRange:  # pragma: no cover
        raise NotImplementedError

    @abc.abstractmethod
    def __str__(self) -> str:  # pragma: no cover
        raise NotImplementedError


class IntegerType(ArithmeticType):
    def __init__(self, bit_length: int, cast_mode: PrimitiveType.CastMode):
        super().__init__(bit_length, cast_mode)

    @property
    @abc.abstractmethod
    def inclusive_value_range(self) -> ValueRange:  # pragma: no cover
        raise NotImplementedError

    @abc.abstractmethod
    def __str__(self) -> str:  # pragma: no cover
        raise NotImplementedError


class SignedIntegerType(IntegerType):
    def __init__(self, bit_length: int, cast_mode: PrimitiveType.CastMode):
        super().__init__(bit_length, cast_mode)

        if self._bit_length < 2:
            raise InvalidBitLengthError("Bit length of signed integer types cannot be less than 2")

        if cast_mode != PrimitiveType.CastMode.SATURATED:
            raise InvalidCastModeError("Invalid cast mode for signed integer: %r" % cast_mode)

    @property
    def inclusive_value_range(self) -> ValueRange:
        uint_max_half = ((1 << self.bit_length) - 1) // 2
        return ValueRange(min=fractions.Fraction(-uint_max_half - 1), max=fractions.Fraction(+uint_max_half))

    def __str__(self) -> str:
        return self._cast_mode_name + " int" + str(self.bit_length)


class UnsignedIntegerType(IntegerType):
    def __init__(self, bit_length: int, cast_mode: PrimitiveType.CastMode):
        super().__init__(bit_length, cast_mode)

    @property
    def inclusive_value_range(self) -> ValueRange:
        return ValueRange(min=fractions.Fraction(0), max=fractions.Fraction((1 << self.bit_length) - 1))

    def __str__(self) -> str:
        return self._cast_mode_name + " uint" + str(self.bit_length)


class ByteType(UnsignedIntegerType):
    """
    This type is used as the array element type for byte strings.
    """

    def __init__(self) -> None:
        super().__init__(bit_length=PrimitiveType.BITS_IN_BYTE, cast_mode=PrimitiveType.CastMode.TRUNCATED)

    def _check_aggregation(self, aggregate: "SerializableType") -> typing.Optional[AggregationFailure]:
        from ._array import ArrayType

        if not isinstance(aggregate, ArrayType):
            return AggregationFailure(self, aggregate, "The byte type can only be used as an array element type")
        return super()._check_aggregation(aggregate)

    def __str__(self) -> str:
        return "byte"


class UTF8Type(UnsignedIntegerType):
    """
    This type is used as the array element type for UTF-8 strings.
    """

    def __init__(self) -> None:
        super().__init__(bit_length=8, cast_mode=PrimitiveType.CastMode.TRUNCATED)

    def _check_aggregation(self, aggregate: "SerializableType") -> typing.Optional[AggregationFailure]:
        from ._array import VariableLengthArrayType

        if not isinstance(aggregate, VariableLengthArrayType):
            return AggregationFailure(
                self, aggregate, "The utf8 type can only be used as a variable-length array element type"
            )
        return super()._check_aggregation(aggregate)

    def __str__(self) -> str:
        return "utf8"


class FloatType(ArithmeticType):
    def __init__(self, bit_length: int, cast_mode: PrimitiveType.CastMode):
        super().__init__(bit_length, cast_mode)

        try:
            frac = fractions.Fraction
            # The limits are exact
            self._magnitude = fractions.Fraction(
                {
                    16: (2**0x00F) * (2 - frac(2) ** frac(-10)),  # IEEE 754 binary16
                    32: (2**0x07F) * (2 - frac(2) ** frac(-23)),  # IEEE 754 binary32
                    64: (2**0x3FF) * (2 - frac(2) ** frac(-52)),  # IEEE 754 binary64
                }[self.bit_length]
            )
        except KeyError:
            raise InvalidBitLengthError("Invalid bit length for float type: %d" % bit_length) from None

    @property
    def inclusive_value_range(self) -> ValueRange:
        return ValueRange(min=-self._magnitude, max=+self._magnitude)

    def __str__(self) -> str:
        return self._cast_mode_name + " float" + str(self.bit_length)


def _unittest_primitive() -> None:
    from pytest import raises, approx

    assert str(BooleanType()) == "bool"

    assert str(ByteType()) == "byte"
    assert ByteType().bit_length_set == {8}
    assert ByteType().inclusive_value_range == (0, 255)  # type: ignore
    assert ByteType().cast_mode == PrimitiveType.CastMode.TRUNCATED

    assert str(UTF8Type()) == "utf8"
    assert UTF8Type().bit_length_set == {8}
    assert UTF8Type().inclusive_value_range == (0, 255)  # type: ignore
    assert UTF8Type().cast_mode == PrimitiveType.CastMode.TRUNCATED

    assert str(SignedIntegerType(15, PrimitiveType.CastMode.SATURATED)) == "saturated int15"
    assert SignedIntegerType(64, PrimitiveType.CastMode.SATURATED).bit_length_set == {64}
    assert SignedIntegerType(8, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (-128, 127)  # type: ignore

    assert str(UnsignedIntegerType(15, PrimitiveType.CastMode.TRUNCATED)) == "truncated uint15"
    assert UnsignedIntegerType(53, PrimitiveType.CastMode.SATURATED).bit_length_set == {53}
    assert UnsignedIntegerType(32, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (  # type: ignore
        0,
        0xFFFFFFFF,
    )

    assert str(FloatType(64, PrimitiveType.CastMode.SATURATED)) == "saturated float64"
    assert FloatType(32, PrimitiveType.CastMode.SATURATED).bit_length_set == 32
    assert FloatType(16, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (-65504, +65504)  # type: ignore

    rng = approx(-3.4028234664e38), approx(+3.4028234664e38)
    assert FloatType(32, PrimitiveType.CastMode.SATURATED).inclusive_value_range == rng  # type: ignore

    rng = approx(-1.7976931348623157e308), approx(+1.7976931348623157e308)
    assert FloatType(64, PrimitiveType.CastMode.SATURATED).inclusive_value_range == rng  # type: ignore

    with raises(InvalidBitLengthError):
        FloatType(8, PrimitiveType.CastMode.TRUNCATED)

    with raises(InvalidBitLengthError):
        SignedIntegerType(1, PrimitiveType.CastMode.SATURATED)

    with raises(InvalidBitLengthError):
        SignedIntegerType(0, PrimitiveType.CastMode.SATURATED)

    with raises(InvalidBitLengthError):
        UnsignedIntegerType(0, PrimitiveType.CastMode.SATURATED)

    with raises(InvalidBitLengthError):
        UnsignedIntegerType(65, PrimitiveType.CastMode.TRUNCATED)

    assert (
        repr(SignedIntegerType(24, PrimitiveType.CastMode.SATURATED))
        == "SignedIntegerType(bit_length=24, cast_mode=<CastMode.SATURATED: 0>)"
    )

    a = UnsignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED)
    b = BooleanType()
    assert hash(a) != hash(b)
    assert hash(a) == hash(UnsignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED))
    assert a == UnsignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED)
    assert b != UnsignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED)
    assert a != b
    assert b == BooleanType()
    assert b != 123  # Not implemented

    for bl in range(1, PrimitiveType.MAX_BIT_LENGTH + 1):
        if bl > 1:
            t = UnsignedIntegerType(bl, PrimitiveType.CastMode.SATURATED)  # type: PrimitiveType
        else:
            t = BooleanType()
        assert t.standard_bit_length == (t.bit_length in {8, 16, 32, 64, 128, 256})
