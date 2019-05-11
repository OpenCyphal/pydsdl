#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import re
import enum
import math
import string
import typing
import itertools
import fractions
from . import _expression
from . import _error
from . import _port_id_ranges
from ._bit_length_set import BitLengthSet


ValueRange = typing.NamedTuple('ValueRange', [('min', fractions.Fraction), ('max', fractions.Fraction)])

Version = typing.NamedTuple('Version', [('major', int), ('minor', int)])


_VALID_FIRST_CHARACTERS_OF_NAME = string.ascii_letters + '_'
_VALID_CONTINUATION_CHARACTERS_OF_NAME = _VALID_FIRST_CHARACTERS_OF_NAME + string.digits

# Disallowed name patterns apply to any part of any name, e.g.,
# an attribute name, a namespace component, type name, etc.
# The pattern must produce an exact match to trigger a name error.
# All patterns are case-insensitive.
_DISALLOWED_NAME_PATTERNS = [
    r'truncated',
    r'saturated',
    r'true',
    r'false',
    r'bool',
    r'void\d*',
    r'u?int\d*',
    r'u?q\d+_\d+',
    r'float\d*',
    r'optional',
    r'aligned',
    r'const',
    r'struct',
    r'super',
    r'template',
    r'enum',
    r'self',
    r'and',
    r'or',
    r'not',
    r'auto',
    r'type',
    r'con',
    r'prn',
    r'aux',
    r'nul',
    r'com\d?',
    r'lpt\d?',
    r'_.*_',
]


class TypeParameterError(_error.InvalidDefinitionError):
    pass


class InvalidBitLengthError(TypeParameterError):
    pass


class InvalidCastModeError(TypeParameterError):
    pass


class InvalidNumberOfElementsError(TypeParameterError):
    pass


class InvalidNameError(TypeParameterError):
    pass


class InvalidVersionError(TypeParameterError):
    pass


class InvalidConstantValueError(TypeParameterError):
    pass


class InvalidTypeError(TypeParameterError):
    pass


class AttributeNameCollisionError(TypeParameterError):
    pass


class InvalidFixedPortIDError(TypeParameterError):
    pass


class MalformedUnionError(TypeParameterError):
    pass


class DeprecatedDependencyError(TypeParameterError):
    pass


class SerializableType(_expression.Any):
    """
    Type objects are immutable. Immutability enables lazy evaluation of properties and hashability.
    Invoking __str__() on a data type returns its uniform normalized definition, e.g.:
        - uavcan.node.Heartbeat.1.0[<=36]
        - truncated float16[<=36]
    """

    TYPE_NAME = 'metaserializable'

    def __init__(self) -> None:
        super(SerializableType, self).__init__()
        self._cached_bit_length_set = None  # type: typing.Optional[BitLengthSet]

    @property
    def bit_length_set(self) -> BitLengthSet:
        """
        A set of all possible bit length values of serialized representations of the data type.
        Refer to the specification for the background. This method must never return an empty set.
        This is an expensive operation, so the result is cached in the base class. Derived classes should not
        override this property themselves; they must implement the method _compute_bit_length_set() instead.
        """
        if self._cached_bit_length_set is None:
            self._cached_bit_length_set = self._compute_bit_length_set()
        return self._cached_bit_length_set

    def _attribute(self, name: _expression.String) -> _expression.Any:
        if name.native_value == '_bit_length_':  # Experimental non-standard extension
            try:
                return _expression.Set(map(_expression.Rational, self.bit_length_set))
            except TypeError:
                pass

        return super(SerializableType, self)._attribute(name)  # Hand over up the inheritance chain, important

    def _compute_bit_length_set(self) -> BitLengthSet:
        """
        This is an expensive operation, so the result is cached in the base class. Derived classes should not
        override the bit_length_set property themselves; they must implement this method instead.
        """
        raise NotImplementedError

    def __str__(self) -> str:   # pragma: no cover
        """
        Must return a DSDL spec-compatible textual representation of the type.
        The string representation is used for determining equivalency by the comparison operator __eq__().
        """
        raise NotImplementedError

    def __hash__(self) -> int:
        return hash(str(self))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SerializableType):
            same_type = isinstance(other, type(self)) and isinstance(self, type(other))
            return same_type and str(self) == str(other)
        else:
            return NotImplemented


class PrimitiveType(SerializableType):
    MAX_BIT_LENGTH = 64
    BITS_IN_BYTE = 8  # Defined in the UAVCAN specification

    class CastMode(enum.Enum):
        SATURATED = 0
        TRUNCATED = 1

    def __init__(self,
                 bit_length: int,
                 cast_mode: 'PrimitiveType.CastMode'):
        super(PrimitiveType, self).__init__()
        self._bit_length = int(bit_length)
        self._cast_mode = cast_mode

        if self._bit_length < 1:
            raise InvalidBitLengthError('Bit length must be positive')

        if self._bit_length > self.MAX_BIT_LENGTH:
            raise InvalidBitLengthError('Bit length cannot exceed %r' % self.MAX_BIT_LENGTH)

        self._standard_bit_length = \
            (self._bit_length >= self.BITS_IN_BYTE) and (2 ** round(math.log2(self._bit_length)) == self._bit_length)

    @property
    def bit_length(self) -> int:
        """All primitives are of a fixed bit length, hence just one value is enough."""
        return self._bit_length

    @property
    def standard_bit_length(self) -> bool:
        """
        "Standard length" means that values of such bit length are commonly used in modern computer microarchitectures,
        such as uint8, float64, int32, and so on. Booleans are excluded.
        More precisely, a primitive is said to be "standard length" when the following hold:
            bit_length >= 8
            2**round(log2(bit_length)) == bit_length.
        """
        return self._standard_bit_length

    @property
    def cast_mode(self) -> 'PrimitiveType.CastMode':
        return self._cast_mode

    @property
    def _cast_mode_name(self) -> str:
        """For internal use only."""
        return {
            self.CastMode.SATURATED: 'saturated',
            self.CastMode.TRUNCATED: 'truncated',
        }[self.cast_mode]

    def _compute_bit_length_set(self) -> BitLengthSet:
        return BitLengthSet(self.bit_length)

    def __str__(self) -> str:   # pragma: no cover
        raise NotImplementedError

    def __repr__(self) -> str:
        return '%s(bit_length=%r, cast_mode=%r)' % (self.__class__.__name__, self.bit_length, self.cast_mode)


class BooleanType(PrimitiveType):
    def __init__(self, cast_mode: PrimitiveType.CastMode):
        super(BooleanType, self).__init__(bit_length=1, cast_mode=cast_mode)

        if cast_mode != PrimitiveType.CastMode.SATURATED:
            raise InvalidCastModeError('Invalid cast mode for boolean: %r' % cast_mode)

    def __str__(self) -> str:
        return self._cast_mode_name + ' bool'


class ArithmeticType(PrimitiveType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(ArithmeticType, self).__init__(bit_length, cast_mode)

    @property
    def inclusive_value_range(self) -> ValueRange:   # pragma: no cover
        raise NotImplementedError

    def __str__(self) -> str:   # pragma: no cover
        raise NotImplementedError


class IntegerType(ArithmeticType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(IntegerType, self).__init__(bit_length, cast_mode)

    @property
    def inclusive_value_range(self) -> ValueRange:   # pragma: no cover
        raise NotImplementedError

    def __str__(self) -> str:   # pragma: no cover
        raise NotImplementedError


class SignedIntegerType(IntegerType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(SignedIntegerType, self).__init__(bit_length, cast_mode)

        if self._bit_length < 2:
            raise InvalidBitLengthError('Bit length of signed integer types cannot be less than 2')

        if cast_mode != PrimitiveType.CastMode.SATURATED:
            raise InvalidCastModeError('Invalid cast mode for signed integer: %r' % cast_mode)

    @property
    def inclusive_value_range(self) -> ValueRange:
        uint_max_half = ((1 << self.bit_length) - 1) // 2
        return ValueRange(min=fractions.Fraction(-uint_max_half - 1),
                          max=fractions.Fraction(+uint_max_half))

    def __str__(self) -> str:
        return self._cast_mode_name + ' int' + str(self.bit_length)


class UnsignedIntegerType(IntegerType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(UnsignedIntegerType, self).__init__(bit_length, cast_mode)

    @property
    def inclusive_value_range(self) -> ValueRange:
        return ValueRange(min=fractions.Fraction(0),
                          max=fractions.Fraction((1 << self.bit_length) - 1))

    def __str__(self) -> str:
        return self._cast_mode_name + ' uint' + str(self.bit_length)


class FloatType(ArithmeticType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(FloatType, self).__init__(bit_length, cast_mode)

        try:
            frac = fractions.Fraction
            # The limits are exact
            self._magnitude = {
                16: (2 ** 0x00F) * (2 - frac(2) ** frac(-10)),   # IEEE 754 binary16
                32: (2 ** 0x07F) * (2 - frac(2) ** frac(-23)),   # IEEE 754 binary32
                64: (2 ** 0x3FF) * (2 - frac(2) ** frac(-52)),   # IEEE 754 binary64
            }[self.bit_length]  # type: fractions.Fraction
        except KeyError:
            raise InvalidBitLengthError('Invalid bit length for float type: %d' % bit_length) from None

    @property
    def inclusive_value_range(self) -> ValueRange:
        return ValueRange(min=-self._magnitude,
                          max=+self._magnitude)

    def __str__(self) -> str:
        return self._cast_mode_name + ' float' + str(self.bit_length)


def _unittest_primitive() -> None:
    from pytest import raises, approx

    assert str(BooleanType(PrimitiveType.CastMode.SATURATED)) == 'saturated bool'

    assert str(SignedIntegerType(15, PrimitiveType.CastMode.SATURATED)) == 'saturated int15'
    assert SignedIntegerType(64, PrimitiveType.CastMode.SATURATED).bit_length_set == {64}
    assert SignedIntegerType(8, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (-128, 127)

    assert str(UnsignedIntegerType(15, PrimitiveType.CastMode.TRUNCATED)) == 'truncated uint15'
    assert UnsignedIntegerType(53, PrimitiveType.CastMode.SATURATED).bit_length_set == {53}
    assert UnsignedIntegerType(32, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (0, 0xFFFFFFFF)

    assert str(FloatType(64, PrimitiveType.CastMode.SATURATED)) == 'saturated float64'
    assert FloatType(32, PrimitiveType.CastMode.SATURATED).bit_length_set == 32
    assert FloatType(16, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (-65504, +65504)

    assert FloatType(32, PrimitiveType.CastMode.SATURATED).inclusive_value_range == \
        (approx(-3.4028234664e+38), approx(+3.4028234664e+38))

    assert FloatType(64, PrimitiveType.CastMode.SATURATED).inclusive_value_range == \
        (approx(-1.7976931348623157e+308), approx(+1.7976931348623157e+308))

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

    assert repr(SignedIntegerType(24, PrimitiveType.CastMode.SATURATED)) == \
        'SignedIntegerType(bit_length=24, cast_mode=<CastMode.SATURATED: 0>)'

    a = UnsignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED)
    b = BooleanType(PrimitiveType.CastMode.SATURATED)
    assert hash(a) != hash(b)
    assert hash(a) == hash(UnsignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED))
    assert a == UnsignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED)
    assert b != UnsignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED)
    assert a != b
    assert b == BooleanType(PrimitiveType.CastMode.SATURATED)
    assert b != 123    # Not implemented

    for bl in range(1, PrimitiveType.MAX_BIT_LENGTH + 1):
        if bl > 1:
            t = UnsignedIntegerType(bl, PrimitiveType.CastMode.SATURATED)  # type: PrimitiveType
        else:
            t = BooleanType(PrimitiveType.CastMode.SATURATED)
        assert t.standard_bit_length == (t.bit_length in {8, 16, 32, 64, 128, 256})


class VoidType(SerializableType):
    MAX_BIT_LENGTH = 64

    def __init__(self, bit_length: int):
        super(VoidType, self).__init__()
        self._bit_length = int(bit_length)

        if self._bit_length < 1:
            raise InvalidBitLengthError('Bit length must be positive')

        if self._bit_length > self.MAX_BIT_LENGTH:
            raise InvalidBitLengthError('Bit length cannot exceed %r' % self.MAX_BIT_LENGTH)

    @property
    def bit_length(self) -> int:
        return self._bit_length

    def _compute_bit_length_set(self) -> BitLengthSet:
        return BitLengthSet(self.bit_length)

    def __str__(self) -> str:
        return 'void%d' % self.bit_length

    def __repr__(self) -> str:
        return 'VoidType(bit_length=%d)' % self.bit_length


def _unittest_void() -> None:
    from pytest import raises

    assert VoidType(1).bit_length_set == 1
    assert str(VoidType(13)) == 'void13'
    assert repr(VoidType(64)) == 'VoidType(bit_length=64)'
    assert VoidType(22).bit_length_set == {22}

    with raises(InvalidBitLengthError):
        VoidType(1)
        VoidType(0)

    with raises(InvalidBitLengthError):
        VoidType(64)
        VoidType(65)


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

    def _compute_bit_length_set(self) -> BitLengthSet:     # pragma: no cover
        raise NotImplementedError

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


class Attribute:    # TODO: should extend expression.Any to support advanced introspection/reflection.
    def __init__(self, data_type: SerializableType, name: str):
        self._data_type = data_type
        self._name = str(name)

        if isinstance(data_type, VoidType):
            if self._name:
                raise InvalidNameError('Void-typed fields can be used only for padding and cannot be named')
        else:
            _check_name(self._name)

    @property
    def data_type(self) -> SerializableType:
        return self._data_type

    @property
    def name(self) -> str:
        return self._name

    def __str__(self) -> str:
        return '%s %s' % (self.data_type, self.name)

    def __repr__(self) -> str:
        return '%s(data_type=%r, name=%r)' % (self.__class__.__name__, self.data_type, self.name)


class Field(Attribute):
    pass


class PaddingField(Field):
    def __init__(self, data_type: VoidType):
        if not isinstance(data_type, VoidType):
            raise TypeParameterError('Padding fields must be of the void type')

        super(PaddingField, self).__init__(data_type, '')


class Constant(Attribute):
    def __init__(self,
                 data_type: SerializableType,
                 name: str,
                 value: _expression.Any):
        super(Constant, self).__init__(data_type, name)

        if not isinstance(value, _expression.Primitive):
            raise InvalidConstantValueError('The constant value must be a primitive expression value')

        self._value = value
        del value

        # Interestingly, both the type of the constant and its value are instances of the same meta-type: expression.
        # BooleanType inherits from expression.Any, same as expression.Boolean.
        if isinstance(data_type, BooleanType):      # Boolean constant
            if not isinstance(self._value, _expression.Boolean):
                raise InvalidConstantValueError('Invalid value for boolean constant: %r' % self._value)

        elif isinstance(data_type, IntegerType):    # Integer constant
            if isinstance(self._value, _expression.Rational):
                if not self._value.is_integer():
                    raise InvalidConstantValueError('The value of an integer constant must be an integer; got %s' %
                                                    self._value)
            elif isinstance(self._value, _expression.String):
                as_bytes = self._value.native_value.encode('utf8')
                if len(as_bytes) != 1:
                    raise InvalidConstantValueError('A constant string must be exactly one ASCII character long')

                if not isinstance(data_type, UnsignedIntegerType) or data_type.bit_length != 8:
                    raise InvalidConstantValueError('Constant strings can be used only with uint8')

                self._value = _expression.Rational(ord(as_bytes))    # Replace string with integer
            else:
                raise InvalidConstantValueError('Invalid value type for integer constant: %r' % self._value)

        elif isinstance(data_type, FloatType):      # Floating point constant
            if not isinstance(self._value, _expression.Rational):
                raise InvalidConstantValueError('Invalid value type for float constant: %r' % self._value)

        else:
            raise InvalidTypeError('Invalid constant type: %r' % data_type)

        assert isinstance(self._value, _expression.Any)
        assert isinstance(self._value, _expression.Rational) == isinstance(self.data_type, (FloatType, IntegerType))
        assert isinstance(self._value, _expression.Boolean) == isinstance(self.data_type, BooleanType)

        # Range check
        if isinstance(self._value, _expression.Rational):
            assert isinstance(data_type, ArithmeticType)
            rng = data_type.inclusive_value_range
            if not (rng.min <= self._value.native_value <= rng.max):
                raise InvalidConstantValueError('Constant value %s exceeds the range of its data type %s' %
                                                (self._value, data_type))

    @property
    def value(self) -> _expression.Any:
        return self._value

    def __str__(self) -> str:
        return '%s %s = %s' % (self.data_type, self.name, self.value)

    def __repr__(self) -> str:
        return 'Constant(data_type=%r, name=%r, value=%r)' % (self.data_type, self.name, self._value)


def _unittest_attribute() -> None:
    from pytest import raises

    assert str(Field(BooleanType(PrimitiveType.CastMode.SATURATED), 'flag')) == 'saturated bool flag'
    assert repr(Field(BooleanType(PrimitiveType.CastMode.SATURATED), 'flag')) == \
        'Field(data_type=BooleanType(bit_length=1, cast_mode=<CastMode.SATURATED: 0>), name=\'flag\')'

    assert str(PaddingField(VoidType(32))) == 'void32 '     # Mind the space!
    assert repr(PaddingField(VoidType(1))) == 'PaddingField(data_type=VoidType(bit_length=1), name=\'\')'

    with raises(TypeParameterError, match='.*void.*'):
        # noinspection PyTypeChecker
        repr(PaddingField(SignedIntegerType(8, PrimitiveType.CastMode.SATURATED)))   # type: ignore

    data_type = SignedIntegerType(32, PrimitiveType.CastMode.SATURATED)
    const = Constant(data_type, 'FOO_CONST', _expression.Rational(-123))
    assert str(const) == 'saturated int32 FOO_CONST = -123'
    assert const.data_type is data_type
    assert const.name == 'FOO_CONST'
    assert const.value == _expression.Rational(-123)

    assert repr(const) == 'Constant(data_type=%r, name=\'FOO_CONST\', value=rational(-123))' % data_type


class CompositeType(SerializableType):
    MAX_NAME_LENGTH = 50
    MAX_VERSION_NUMBER = 255
    NAME_COMPONENT_SEPARATOR = '.'

    def __init__(self,
                 name:          str,
                 version:       Version,
                 attributes:    typing.Iterable[Attribute],
                 deprecated:    bool,
                 fixed_port_id: typing.Optional[int],
                 source_file_path:  str):
        super(CompositeType, self).__init__()

        self._name = str(name).strip()
        self._version = version
        self._attributes = list(attributes)
        self._attributes_by_name = {a.name: a for a in self._attributes}  # Ordering not preserved in older Pythons
        self._deprecated = bool(deprecated)
        self._fixed_port_id = None if fixed_port_id is None else int(fixed_port_id)
        self._source_file_path = str(source_file_path)

        # Name check
        if not self._name:
            raise InvalidNameError('Composite type name cannot be empty')

        if self.NAME_COMPONENT_SEPARATOR not in self._name:
            raise InvalidNameError('Root namespace is not specified')

        if len(self._name) > self.MAX_NAME_LENGTH:
            raise InvalidNameError('Name is too long: %r is longer than %d characters' %
                                   (self._name, self.MAX_NAME_LENGTH))

        for component in self._name.split(self.NAME_COMPONENT_SEPARATOR):
            _check_name(component)

        # Version check
        version_valid = (0 <= self._version.major <= self.MAX_VERSION_NUMBER) and\
                        (0 <= self._version.minor <= self.MAX_VERSION_NUMBER) and\
                        ((self._version.major + self._version.minor) > 0)

        if not version_valid:
            raise InvalidVersionError('Invalid version numbers: %s.%s' % (self._version.major, self._version.minor))

        # Attribute check
        used_names = set()      # type: typing.Set[str]
        for a in self._attributes:
            if a.name and a.name in used_names:
                raise AttributeNameCollisionError('Multiple attributes under the same name: %r' % a.name)
            else:
                used_names.add(a.name)
        assert len(self._attributes) == len(self._attributes_by_name)

        # Port ID check
        port_id = self._fixed_port_id
        if port_id is not None:
            assert port_id is not None
            if isinstance(self, ServiceType):
                if not (0 <= port_id <= _port_id_ranges.MAX_SERVICE_ID):
                    raise InvalidFixedPortIDError('Fixed service ID %r is not valid' % port_id)
            else:
                if not (0 <= port_id <= _port_id_ranges.MAX_SUBJECT_ID):
                    raise InvalidFixedPortIDError('Fixed subject ID %r is not valid' % port_id)

        # Consistent deprecation check.
        # A non-deprecated type cannot be dependent on deprecated types.
        # A deprecated type can be dependent on anything.
        if not self.deprecated:
            for a in self._attributes:
                t = a.data_type
                if isinstance(t, CompositeType):
                    if t.deprecated:
                        raise DeprecatedDependencyError('A type cannot depend on deprecated types '
                                                        'unless it is also deprecated.')

    def is_mutually_bit_compatible_with(self, other: 'CompositeType') -> bool:
        """
        Checks for bit compatibility between two data types.
        The current implementation uses a relaxed simplified check that may yield a false-negative,
        but never a false-positive; i.e., it may fail to detect an incompatibility, but it is guaranteed
        to never report two data types as incompatible if they are compatible.
        The implementation may be updated in the future to use a strict check as defined in the specification
        while keeping the same API, so beware.
        """
        return self.bit_length_set == other.bit_length_set

    @property
    def full_name(self) -> str:
        """The full name, e.g., uavcan.node.Heartbeat"""
        return self._name

    @property
    def name_components(self) -> typing.List[str]:
        """Components of the full name as a list, e.g., ['uavcan', 'node', 'Heartbeat']"""
        return self._name.split(CompositeType.NAME_COMPONENT_SEPARATOR)

    @property
    def short_name(self) -> str:
        """The last component of the full name, e.g., Heartbeat of uavcan.node.Heartbeat"""
        return self.name_components[-1]

    @property
    def full_namespace(self) -> str:
        """The full name without the short name, e.g., uavcan.node for uavcan.node.Heartbeat"""
        return str(CompositeType.NAME_COMPONENT_SEPARATOR.join(self.name_components[:-1]))

    @property
    def root_namespace(self) -> str:
        """The first component of the full name, e.g., uavcan of uavcan.node.Heartbeat"""
        return self.name_components[0]

    @property
    def version(self) -> Version:
        return self._version

    @property
    def deprecated(self) -> bool:
        return self._deprecated

    @property
    def attributes(self) -> typing.List[Attribute]:
        return self._attributes[:]  # Return copy to prevent mutation

    @property
    def fields(self) -> typing.List[Field]:
        return [a for a in self.attributes if isinstance(a, Field)]

    @property
    def constants(self) -> typing.List[Constant]:
        return [a for a in self.attributes if isinstance(a, Constant)]

    @property
    def fixed_port_id(self) -> typing.Optional[int]:
        return self._fixed_port_id

    @property
    def has_fixed_port_id(self) -> bool:
        return self.fixed_port_id is not None

    @property
    def source_file_path(self) -> str:
        """Empty if this is a synthesized type, e.g. a service request or response section."""
        return self._source_file_path

    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """
        This method is intended for code generators. It iterates over every field (not attribute, i.e.,
        constants are excluded) of the data type, yielding it together with its offset, where the offset is
        represented as BitLengthSet. The offset of each field is added to the base offset, which may be specified
        by the caller; if not specified, the base offset is assumed to be zero.

        The objective of this method is to allow code generators to easily implement fully unrolled serialization and
        deserialization routines, where "unrolled" means that upon encountering another (nested) composite type, the
        serialization routine would not delegate its serialization to the serialization routine of the encountered type,
        but instead would serialize it in-place, as if the field of that type was replaced with its own fields in-place.
        The lack of delegation has very important performance implications: when the serialization routine does
        not delegate serialization of the nested types, it can perform infinitely deep field alignment analysis,
        thus being able to reliably statically determine whether each field of the type, including nested types
        at arbitrarily deep levels of nesting, is aligned relative to the origin of the serialized representation
        of the outermost type. As a result, the code generator will be able to avoid unnecessary reliance on slow
        bit-level copy routines replacing them instead with much faster byte-level copy (like memcpy()) or even
        plain memory aliasing, since it will be able to determine and prove the alignment of each field statically.

        When invoked on a tagged union type, the method yields the same offset for every field (since that's how
        tagged unions are serialized), where the offset equals the bit length of the implicit union tag (plus the
        base offset, of course, if provided).

        Please refer to the usage examples to see how this feature can be used.

        :param base_offset: Assume the specified base offset; assume zero offset if the parameter is not provided.
                            This parameter should be used when serializing nested composite data types.

        :return: A generator of (Field, BitLengthSet). Each instance of BitLengthSet yielded by the generator is
                 a dedicated copy, meaning that the consumer can mutate the returned instances arbitrarily without
                 affecting future values. It is guaranteed that each yielded instance of BitLengthSet is non-empty.
        """
        raise NotImplementedError

    def _attribute(self, name: _expression.String) -> _expression.Any:
        """
        This is the handler for DSDL expressions like uavcan.node.Heartbeat.1.0.MODE_OPERATIONAL.
        """
        for c in self.constants:
            if c.name == name.native_value:
                assert isinstance(c.value, _expression.Any)
                return c.value

        return super(CompositeType, self)._attribute(name)  # Hand over up the inheritance chain, this is important

    def _compute_bit_length_set(self) -> BitLengthSet:
        raise NotImplementedError

    def __getitem__(self, attribute_name: str) -> Attribute:
        """
        Allows the caller to retrieve an attribute by name.
        Raises KeyError if there is no such attribute.
        """
        return self._attributes_by_name[attribute_name]

    def __str__(self) -> str:
        return '%s.%d.%d' % (self.full_name, self.version.major, self.version.minor)

    def __repr__(self) -> str:
        return '%s(name=%r, version=%r, fields=%r, constants=%r, deprecated=%r, fixed_port_id=%r)' % \
            (self.__class__.__name__,
             self.full_name,
             self.version,
             self.fields,
             self.constants,
             self.deprecated,
             self.fixed_port_id)


class UnionType(CompositeType):
    MIN_NUMBER_OF_VARIANTS = 2

    def __init__(self,
                 name:             str,
                 version:          Version,
                 attributes:       typing.Iterable[Attribute],
                 deprecated:       bool,
                 fixed_port_id:    typing.Optional[int],
                 source_file_path: str):
        # Proxy all parameters directly to the base type - I wish we could do that
        # with kwargs while preserving the type information
        super(UnionType, self).__init__(name=name,
                                        version=version,
                                        attributes=attributes,
                                        deprecated=deprecated,
                                        fixed_port_id=fixed_port_id,
                                        source_file_path=source_file_path)

        if self.number_of_variants < self.MIN_NUMBER_OF_VARIANTS:
            raise MalformedUnionError('A tagged union cannot contain fewer than %d variants' %
                                      self.MIN_NUMBER_OF_VARIANTS)

        for a in attributes:
            if isinstance(a, PaddingField) or not a.name or isinstance(a.data_type, VoidType):
                raise MalformedUnionError('Padding fields not allowed in unions')

        # Construct once to allow reference equality checks
        assert (self.number_of_variants - 1) > 0
        tag_bit_length = (self.number_of_variants - 1).bit_length()
        self._tag_field_type = UnsignedIntegerType(tag_bit_length, PrimitiveType.CastMode.TRUNCATED)

    @property
    def number_of_variants(self) -> int:
        return len(self.fields)

    @property
    def tag_field_type(self) -> UnsignedIntegerType:
        """
        Returns the best-matching unsigned integer type of the implicit union tag field.
        This is convenient for code generation.
        """
        return self._tag_field_type

    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        base_offset = BitLengthSet(base_offset or {0})
        base_offset.increment(self.tag_field_type.bit_length)
        for f in self.fields:  # Same offset for every field, because it's a tagged union, not a struct
            yield f, BitLengthSet(base_offset)      # We yield a copy of the offset to prevent mutation

    def _compute_bit_length_set(self) -> BitLengthSet:
        return BitLengthSet.for_tagged_union(map(lambda f: f.data_type.bit_length_set, self.fields))


class StructureType(CompositeType):
    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        base_offset = BitLengthSet(base_offset or 0)

        # The following variables do not serve the business logic, they are needed only for runtime cross-checking
        _self_test_original_offset = BitLengthSet(0)
        _self_test_field_bls_collection = []  # type: typing.List[BitLengthSet]

        for f in self.fields:
            yield f, BitLengthSet(base_offset)      # We yield a copy of the offset to prevent mutation
            base_offset.increment(f.data_type.bit_length_set)

            # This is only for ensuring that the logic is functioning as intended.
            # Combinatorial transformations are easy to mess up, so we have to employ defensive programming.
            _self_test_original_offset.increment(f.data_type.bit_length_set)
            _self_test_field_bls_collection.append(f.data_type.bit_length_set)
            assert BitLengthSet.for_struct(_self_test_field_bls_collection) == _self_test_original_offset

    def _compute_bit_length_set(self) -> BitLengthSet:
        return BitLengthSet.for_struct(map(lambda f: f.data_type.bit_length_set, self.fields))


class ServiceType(CompositeType):
    def __init__(self,
                 name:                str,
                 version:             Version,
                 request_attributes:  typing.Iterable[Attribute],
                 response_attributes: typing.Iterable[Attribute],
                 request_is_union:    bool,
                 response_is_union:   bool,
                 deprecated:          bool,
                 fixed_port_id:       typing.Optional[int],
                 source_file_path:    str):
        request_meta_type = UnionType if request_is_union else StructureType  # type: type
        self._request_type = request_meta_type(name=name + '.Request',
                                               version=version,
                                               attributes=request_attributes,
                                               deprecated=deprecated,
                                               fixed_port_id=None,
                                               source_file_path='')  # type: CompositeType

        response_meta_type = UnionType if response_is_union else StructureType  # type: type
        self._response_type = response_meta_type(name=name + '.Response',
                                                 version=version,
                                                 attributes=response_attributes,
                                                 deprecated=deprecated,
                                                 fixed_port_id=None,
                                                 source_file_path='')  # type: CompositeType

        container_attributes = [
            Field(data_type=self._request_type,  name='request'),
            Field(data_type=self._response_type, name='response'),
        ]

        super(ServiceType, self).__init__(name=name,
                                          version=version,
                                          attributes=container_attributes,
                                          deprecated=deprecated,
                                          fixed_port_id=fixed_port_id,
                                          source_file_path=source_file_path)

    @property
    def request_type(self) -> CompositeType:
        return self._request_type

    @property
    def response_type(self) -> CompositeType:
        return self._response_type

    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        raise TypeError('Service types do not have serializable fields. Use either request or response.')

    def _compute_bit_length_set(self) -> BitLengthSet:     # pragma: no cover
        raise TypeError('Service types are not directly serializable. Use either request or response.')


def _check_name(name: str) -> None:
    if not name:
        raise InvalidNameError('Name or namespace component cannot be empty')

    if name[0] not in _VALID_FIRST_CHARACTERS_OF_NAME:
        raise InvalidNameError('Name or namespace component cannot start with %r' % name[0])

    for char in name:
        if char not in _VALID_CONTINUATION_CHARACTERS_OF_NAME:
            raise InvalidNameError('Name or namespace component cannot contain %r' % char)

    for pat in _DISALLOWED_NAME_PATTERNS:
        if re.match(pat + '$', name, flags=re.IGNORECASE):
            raise InvalidNameError('Disallowed name: %r matches the following pattern: %s' % (name, pat))


def _unittest_composite_types() -> None:
    from pytest import raises

    def try_name(name: str) -> CompositeType:
        return CompositeType(name=name,
                             version=Version(0, 1),
                             attributes=[],
                             deprecated=False,
                             fixed_port_id=None,
                             source_file_path='')

    with raises(InvalidNameError, match='(?i).*empty.*'):
        try_name('')

    with raises(InvalidNameError, match='(?i).*root namespace.*'):
        try_name('T')

    with raises(InvalidNameError, match='(?i).*long.*'):
        try_name('namespace.another.deeper.' * 10 + 'LongTypeName')

    with raises(InvalidNameError, match='(?i).*component.*empty.*'):
        try_name('namespace.ns..T')

    with raises(InvalidNameError, match='(?i).*component.*empty.*'):
        try_name('.namespace.ns.T')

    with raises(InvalidNameError, match='(?i).*cannot start with.*'):
        try_name('namespace.0ns.T')

    with raises(InvalidNameError, match='(?i).*cannot start with.*'):
        try_name('namespace.ns.0T')

    with raises(InvalidNameError, match='(?i).*cannot contain.*'):
        try_name('namespace.n-s.T')

    assert try_name('root.nested.T').full_name == 'root.nested.T'
    assert try_name('root.nested.T').full_namespace == 'root.nested'
    assert try_name('root.nested.T').root_namespace == 'root'
    assert try_name('root.nested.T').short_name == 'T'

    with raises(MalformedUnionError, match='.*variants.*'):
        UnionType(name='a.A',
                  version=Version(0, 1),
                  attributes=[],
                  deprecated=False,
                  fixed_port_id=None,
                  source_file_path='')

    with raises(MalformedUnionError, match='(?i).*padding.*'):
        UnionType(name='a.A',
                  version=Version(0, 1),
                  attributes=[
                      Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), 'a'),
                      Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), 'b'),
                      PaddingField(VoidType(16)),
                  ],
                  deprecated=False,
                  fixed_port_id=None,
                  source_file_path='')

    _check_name('abc')
    _check_name('_abc')
    _check_name('abc_')
    _check_name('abc0')

    with raises(InvalidNameError):
        _check_name('0abc')

    with raises(InvalidNameError):
        _check_name('_abc_')

    with raises(InvalidNameError):
        _check_name('a-bc')

    with raises(InvalidNameError):
        _check_name('')

    with raises(InvalidNameError):
        _check_name('truncated')

    with raises(InvalidNameError):
        _check_name('COM1')

    with raises(InvalidNameError):
        _check_name('Aux')

    with raises(InvalidNameError):
        _check_name('float128')

    with raises(InvalidNameError):
        _check_name('q16_8')

    with raises(InvalidNameError):
        _check_name('uq1_32')

    u = UnionType(name='a.A',
                  version=Version(0, 1),
                  attributes=[
                      Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), 'a'),
                      Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), 'b'),
                      Constant(FloatType(32, PrimitiveType.CastMode.SATURATED), 'A', _expression.Rational(123)),
                  ],
                  deprecated=False,
                  fixed_port_id=None,
                  source_file_path='')
    assert u['a'].name == 'a'
    assert u['b'].name == 'b'
    assert u['A'].name == 'A'
    with raises(KeyError):
        assert u['c']

    def try_union_fields(field_types: typing.List[SerializableType]) -> UnionType:
        atr = []
        for i, t in enumerate(field_types):
            atr.append(Field(t, '_%d' % i))

        return UnionType(name='a.A',
                         version=Version(0, 1),
                         attributes=atr,
                         deprecated=False,
                         fixed_port_id=None,
                         source_file_path='')

    assert try_union_fields([
        UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ]).bit_length_set == {17}

    # The reference values for the following test are explained in the array tests above
    tu8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    small = VariableLengthArrayType(tu8, 2)
    outer = FixedLengthArrayType(small, 2)   # bit length values: {4, 12, 20, 28, 36}

    # Above plus one bit to each, plus 16-bit for the unsigned integer field
    assert try_union_fields([
        outer,
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ]).bit_length_set == {5, 13, 17, 21, 29, 37}

    def try_struct_fields(field_types: typing.List[SerializableType]) -> StructureType:
        atr = []
        for i, t in enumerate(field_types):
            atr.append(Field(t, '_%d' % i))

        return StructureType(name='a.A',
                             version=Version(0, 1),
                             attributes=atr,
                             deprecated=False,
                             fixed_port_id=None,
                             source_file_path='')

    assert try_struct_fields([
        UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ]).bit_length_set == {32}

    assert try_struct_fields([]).bit_length_set == {0}   # Empty sets forbidden

    assert try_struct_fields([
        outer,
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ]).bit_length_set == {4 + 16, 12 + 16, 20 + 16, 28 + 16, 36 + 16}

    assert try_struct_fields([outer]).bit_length_set == {4, 12, 20, 28, 36}


def _unittest_field_iterators() -> None:
    from pytest import raises

    saturated = PrimitiveType.CastMode.SATURATED
    _seq_no = 0

    def make_type(meta: typing.Type[CompositeType], attributes: typing.Iterable[Attribute]) -> CompositeType:
        nonlocal _seq_no
        _seq_no += 1
        return meta('ns.Type' + str(_seq_no),
                    version=Version(1, 0),
                    attributes=attributes,
                    deprecated=False,
                    fixed_port_id=None,
                    source_file_path='')

    def validate_iterator(t: CompositeType,
                          reference: typing.Iterable[typing.Tuple[str, typing.Set[int]]],
                          base_offset: typing.Optional[BitLengthSet] = None) -> None:
        for (name, ref_set), (field, real_set) in itertools.zip_longest(reference,
                                                                        t.iterate_fields_with_offsets(base_offset)):
            assert field.name == name
            assert real_set == ref_set, field.name + ': ' + str(real_set)

    a = make_type(StructureType, [
        Field(UnsignedIntegerType(10, saturated), 'a'),
        Field(BooleanType(saturated), 'b'),
        Field(VariableLengthArrayType(FloatType(32, saturated), 2), 'c'),
        Field(FixedLengthArrayType(FloatType(32, saturated), 7), 'd'),
        PaddingField(VoidType(3)),
    ])

    validate_iterator(a, [
        ('a', {0}),
        ('b', {10}),
        ('c', {11}),
        ('d', {
            11 + 2 + 32 * 0,
            11 + 2 + 32 * 1,
            11 + 2 + 32 * 2,
        }),
        ('', {
            11 + 2 + 32 * 0 + 32 * 7,
            11 + 2 + 32 * 1 + 32 * 7,
            11 + 2 + 32 * 2 + 32 * 7,
        }),
    ])

    a_bls_options = [
        11 + 2 + 32 * 0 + 32 * 7 + 3,
        11 + 2 + 32 * 1 + 32 * 7 + 3,
        11 + 2 + 32 * 2 + 32 * 7 + 3,
    ]
    assert a.bit_length_set == BitLengthSet(a_bls_options)

    # Testing "a" again, this time with non-zero base offset
    validate_iterator(a, [
        ('a', {1, 16}),
        ('b', {1 + 10, 16 + 10}),
        ('c', {1 + 11, 16 + 11}),
        ('d', {
            1 + 11 + 2 + 32 * 0,
            1 + 11 + 2 + 32 * 1,
            1 + 11 + 2 + 32 * 2,
            16 + 11 + 2 + 32 * 0,
            16 + 11 + 2 + 32 * 1,
            16 + 11 + 2 + 32 * 2,
        }),
        ('', {
            1 + 11 + 2 + 32 * 0 + 32 * 7,
            1 + 11 + 2 + 32 * 1 + 32 * 7,
            1 + 11 + 2 + 32 * 2 + 32 * 7,
            16 + 11 + 2 + 32 * 0 + 32 * 7,
            16 + 11 + 2 + 32 * 1 + 32 * 7,
            16 + 11 + 2 + 32 * 2 + 32 * 7,
        }),
    ], BitLengthSet({1, 16}))

    b = make_type(StructureType, [
        Field(a, 'z'),
        Field(VariableLengthArrayType(a, 2), 'y'),
        Field(UnsignedIntegerType(6, saturated), 'x'),
    ])

    validate_iterator(b, [
        ('z', {0}),
        ('y', {
            a_bls_options[0],
            a_bls_options[1],
            a_bls_options[2],
        }),
        ('x', {  # The lone "+2" is for the variable-length array's implicit length field
            # First length option of z
            a_bls_options[0] + 2 + a_bls_options[0] * 0,  # suka
            a_bls_options[0] + 2 + a_bls_options[1] * 0,
            a_bls_options[0] + 2 + a_bls_options[2] * 0,
            a_bls_options[0] + 2 + a_bls_options[0] * 1,
            a_bls_options[0] + 2 + a_bls_options[1] * 1,
            a_bls_options[0] + 2 + a_bls_options[2] * 1,
            a_bls_options[0] + 2 + a_bls_options[0] * 2,
            a_bls_options[0] + 2 + a_bls_options[1] * 2,
            a_bls_options[0] + 2 + a_bls_options[2] * 2,
            # Second length option of z
            a_bls_options[1] + 2 + a_bls_options[0] * 0,
            a_bls_options[1] + 2 + a_bls_options[1] * 0,
            a_bls_options[1] + 2 + a_bls_options[2] * 0,
            a_bls_options[1] + 2 + a_bls_options[0] * 1,
            a_bls_options[1] + 2 + a_bls_options[1] * 1,
            a_bls_options[1] + 2 + a_bls_options[2] * 1,
            a_bls_options[1] + 2 + a_bls_options[0] * 2,
            a_bls_options[1] + 2 + a_bls_options[1] * 2,
            a_bls_options[1] + 2 + a_bls_options[2] * 2,
            # Third length option of z
            a_bls_options[2] + 2 + a_bls_options[0] * 0,
            a_bls_options[2] + 2 + a_bls_options[1] * 0,
            a_bls_options[2] + 2 + a_bls_options[2] * 0,
            a_bls_options[2] + 2 + a_bls_options[0] * 1,
            a_bls_options[2] + 2 + a_bls_options[1] * 1,
            a_bls_options[2] + 2 + a_bls_options[2] * 1,
            a_bls_options[2] + 2 + a_bls_options[0] * 2,
            a_bls_options[2] + 2 + a_bls_options[1] * 2,
            a_bls_options[2] + 2 + a_bls_options[2] * 2,
        }),
    ])

    # Ensuring the equivalency between bit length and bit offset
    b_offset = BitLengthSet()
    for f in b.fields:
        b_offset.increment(f.data_type.bit_length_set)
    print('b_offset:', b_offset)
    assert b_offset == b.bit_length_set
    assert b_offset.is_aligned_at_byte()
    assert not b_offset.is_aligned_at(32)

    c = make_type(UnionType, [
        Field(a, 'foo'),
        Field(b, 'bar'),
    ])

    validate_iterator(c, [
        ('foo', {1}),       # The offset is the same because it's a union
        ('bar', {1}),
    ])

    validate_iterator(c, [
        ('foo', {8 + 1}),
        ('bar', {8 + 1}),
    ], BitLengthSet(8))

    validate_iterator(c, [
        ('foo', {0 + 1, 4 + 1, 8 + 1}),
        ('bar', {0 + 1, 4 + 1, 8 + 1}),
    ], BitLengthSet({0, 4, 8}))

    with raises(TypeError, match='.*request or response.*'):
        ServiceType(name='ns.S',
                    version=Version(1, 0),
                    request_attributes=[],
                    response_attributes=[],
                    request_is_union=False,
                    response_is_union=False,
                    deprecated=False,
                    fixed_port_id=None,
                    source_file_path='').iterate_fields_with_offsets()
