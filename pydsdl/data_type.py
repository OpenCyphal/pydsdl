#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import re
import enum
import string
import typing
import itertools
import fractions
from . import expression
from . import error
from . import port_id_ranges


BitLengthRange = typing.NamedTuple('BitLengthRange', [('min', int), ('max', int)])

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


class TypeParameterError(error.InvalidDefinitionError):
    pass


class InvalidBitLengthError(TypeParameterError):
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


class AttributeNameCollision(TypeParameterError):
    pass


class InvalidFixedPortIDError(TypeParameterError):
    pass


class MalformedUnionError(TypeParameterError):
    pass


class DeprecatedDependencyError(TypeParameterError):
    pass


class DataType(expression.Any):
    """
    Invoking __str__() on a data type returns its uniform normalized definition, e.g.:
        - uavcan.node.Heartbeat.1.0[<=36]
        - truncated float16[<=36]
    """

    TYPE_NAME = 'metatype'

    @property
    def bit_length_range(self) -> BitLengthRange:
        # This default implementation uses BLV analysis, so it is very slow.
        # Derived classes can redefine it as appropriate.
        blv = self.compute_bit_length_values()
        return BitLengthRange(min(blv), max(blv))

    def compute_bit_length_values(self) -> typing.Set[int]:     # pragma: no cover
        """
        A set of all possible bit length values for the encoded representation of the data type.
        With complex data types, a full bit length set estimation may lead to a combinatorial explosion.
        This function must never return an empty set.
        The following invariants hold:
        >>> self.bit_length_range.min == min(self.compute_bit_length_values())
        >>> self.bit_length_range.max == max(self.compute_bit_length_values())
        """
        raise NotImplementedError

    def _attribute(self, name: expression.String) -> expression.Any:
        if name.native_value == '_bit_length_':
            return expression.Set(map(expression.Rational, self.compute_bit_length_values()))
        else:
            return super(DataType, self)._attribute(name)  # Hand over up the inheritance chain, this is important

    def __str__(self) -> str:   # pragma: no cover
        raise NotImplementedError

    def __hash__(self) -> int:
        return hash(str(self))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DataType):
            same_type = isinstance(other, type(self)) and isinstance(self, type(other))
            return same_type and str(self) == str(other)
        else:
            return NotImplemented


class PrimitiveType(DataType):
    MAX_BIT_LENGTH = 64

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

    @property
    def bit_length(self) -> int:
        """All primitives are of a fixed bit length, hence just one value is enough."""
        return self._bit_length

    def compute_bit_length_values(self) -> typing.Set[int]:
        return {self._bit_length}

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

    def __str__(self) -> str:   # pragma: no cover
        raise NotImplementedError

    def __repr__(self) -> str:
        return '%s(bit_length=%r, cast_mode=%r)' % (self.__class__.__name__, self.bit_length, self.cast_mode)


class BooleanType(PrimitiveType):
    def __init__(self, cast_mode: PrimitiveType.CastMode):
        super(BooleanType, self).__init__(bit_length=1, cast_mode=cast_mode)

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

        if self._bit_length < 2:
            raise InvalidBitLengthError('Bit length of integer types cannot be less than 2')

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
            self._magnitude = {
                16: fractions.Fraction(65504),
                32: fractions.Fraction('3.40282346638528859812e+38'),
                64: fractions.Fraction('1.79769313486231570815e+308'),
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
    from pytest import raises

    assert str(BooleanType(PrimitiveType.CastMode.SATURATED)) == 'saturated bool'

    assert str(SignedIntegerType(15, PrimitiveType.CastMode.SATURATED)) == 'saturated int15'
    assert SignedIntegerType(64, PrimitiveType.CastMode.SATURATED).bit_length_range == (64, 64)
    assert SignedIntegerType(8, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (-128, 127)

    assert str(UnsignedIntegerType(15, PrimitiveType.CastMode.TRUNCATED)) == 'truncated uint15'
    assert UnsignedIntegerType(53, PrimitiveType.CastMode.SATURATED).bit_length_range == (53, 53)
    assert UnsignedIntegerType(32, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (0, 0xFFFFFFFF)

    assert str(FloatType(64, PrimitiveType.CastMode.SATURATED)) == 'saturated float64'
    assert FloatType(32, PrimitiveType.CastMode.SATURATED).bit_length_range == (32, 32)
    assert FloatType(16, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (-65504, +65504)

    with raises(InvalidBitLengthError):
        FloatType(8, PrimitiveType.CastMode.TRUNCATED)

    with raises(InvalidBitLengthError):
        SignedIntegerType(1, PrimitiveType.CastMode.SATURATED)

    with raises(InvalidBitLengthError):
        SignedIntegerType(0, PrimitiveType.CastMode.SATURATED)

    with raises(InvalidBitLengthError):
        UnsignedIntegerType(1, PrimitiveType.CastMode.SATURATED)

    with raises(InvalidBitLengthError):
        UnsignedIntegerType(65, PrimitiveType.CastMode.TRUNCATED)

    assert repr(SignedIntegerType(24, PrimitiveType.CastMode.TRUNCATED)) == \
        'SignedIntegerType(bit_length=24, cast_mode=<CastMode.TRUNCATED: 1>)'

    a = SignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED)
    b = BooleanType(PrimitiveType.CastMode.SATURATED)
    assert hash(a) != hash(b)
    assert hash(a) == hash(SignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED))
    assert a == SignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED)
    assert b != SignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED)
    assert a != b
    assert b == BooleanType(PrimitiveType.CastMode.SATURATED)
    assert b != BooleanType(PrimitiveType.CastMode.TRUNCATED)
    assert b != 123    # Not implemented


class VoidType(DataType):
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

    def compute_bit_length_values(self) -> typing.Set[int]:
        return {self._bit_length}

    def __str__(self) -> str:
        return 'void%d' % self.bit_length

    def __repr__(self) -> str:
        return 'VoidType(bit_length=%d)' % self.bit_length


def _unittest_void() -> None:
    from pytest import raises

    assert VoidType(1).bit_length_range == (1, 1)
    assert str(VoidType(13)) == 'void13'
    assert repr(VoidType(64)) == 'VoidType(bit_length=64)'
    assert VoidType(22).compute_bit_length_values() == {22}

    with raises(InvalidBitLengthError):
        VoidType(1)
        VoidType(0)

    with raises(InvalidBitLengthError):
        VoidType(64)
        VoidType(65)


class ArrayType(DataType):
    def __init__(self,
                 element_type: DataType,
                 capacity: int):
        super(ArrayType, self).__init__()
        self._element_type = element_type
        self._capacity = int(capacity)
        if self._capacity < 1:
            raise InvalidNumberOfElementsError('Array capacity cannot be less than 1')

    @property
    def element_type(self) -> DataType:
        return self._element_type

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def string_like(self) -> bool:
        """
        Returns True if the array might contain a text string, in which case it is termed to be "string-like".
        A string-like array is a dynamic array of uint8.
        """
        return False

    def compute_bit_length_values(self) -> typing.Set[int]:     # pragma: no cover
        raise NotImplementedError

    def __str__(self) -> str:   # pragma: no cover
        raise NotImplementedError


class FixedLengthArrayType(ArrayType):
    def __init__(self,
                 element_type: DataType,
                 capacity: int):
        super(FixedLengthArrayType, self).__init__(element_type, capacity)

    @property
    def bit_length_range(self) -> BitLengthRange:
        return BitLengthRange(min=self.element_type.bit_length_range.min * self.capacity,
                              max=self.element_type.bit_length_range.max * self.capacity)

    def compute_bit_length_values(self) -> typing.Set[int]:
        # combinations_with_replacement() implements the standard n-combination function.
        combinations = itertools.combinations_with_replacement(self.element_type.compute_bit_length_values(),
                                                               self.capacity)
        # We do not care about permutations because the final bit length is invariant to the order of
        # serialized elements. Having found all combinations, we need to obtain a set of resulting length values.
        return set(map(sum, combinations))

    def __str__(self) -> str:
        return '%s[%d]' % (self.element_type, self.capacity)

    def __repr__(self) -> str:
        return 'FixedLengthArrayType(element_type=%r, capacity=%r)' % (self.element_type, self.capacity)


def _unittest_fixed_array() -> None:
    from pytest import raises

    su8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.SATURATED)
    ti64 = SignedIntegerType(64, cast_mode=PrimitiveType.CastMode.TRUNCATED)

    assert str(FixedLengthArrayType(su8, 4)) == 'saturated uint8[4]'
    assert str(FixedLengthArrayType(ti64, 1)) == 'truncated int64[1]'

    assert not FixedLengthArrayType(su8, 4).string_like
    assert not FixedLengthArrayType(ti64, 1).string_like

    assert FixedLengthArrayType(su8, 4).bit_length_range == (32, 32)
    assert FixedLengthArrayType(su8, 200).capacity == 200
    assert FixedLengthArrayType(ti64, 200).element_type is ti64

    with raises(InvalidNumberOfElementsError):
        FixedLengthArrayType(ti64, 0)

    assert repr(FixedLengthArrayType(ti64, 128)) == \
        'FixedLengthArrayType(element_type=SignedIntegerType(bit_length=64, cast_mode=<CastMode.TRUNCATED: 1>), ' \
        'capacity=128)'

    small = FixedLengthArrayType(su8, 2)
    assert small.compute_bit_length_values() == {16}


class VariableLengthArrayType(ArrayType):
    def __init__(self,
                 element_type: DataType,
                 capacity: int):
        super(VariableLengthArrayType, self).__init__(element_type, capacity)

    @property
    def string_like(self) -> bool:
        et = self.element_type      # Without this temporary MyPy yields a false positive type error
        return isinstance(et, UnsignedIntegerType) and (et.bit_length == 8)

    @property
    def length_prefix_bit_length(self) -> int:
        return self.capacity.bit_length()

    @property
    def bit_length_range(self) -> BitLengthRange:
        return BitLengthRange(
            min=self.length_prefix_bit_length,
            max=self.length_prefix_bit_length + self.element_type.bit_length_range.max * self.capacity
        )

    def compute_bit_length_values(self) -> typing.Set[int]:
        # Please refer to the corresponding implementation for the static array.
        # The idea here is that we treat the dynamic array as a combination of static arrays of different sizes,
        # from zero elements up to the maximum number of elements.
        output = set()           # type: typing.Set[int]
        for capacity in range(self.capacity + 1):
            combinations = itertools.combinations_with_replacement(self.element_type.compute_bit_length_values(),
                                                                   capacity)
            output |= set(map(lambda c: sum(c) + self.length_prefix_bit_length, combinations))

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
    assert VariableLengthArrayType(tu8, 3).bit_length_range == (2, 26)
    assert VariableLengthArrayType(tu8, 1).bit_length_range == (1, 9)
    assert VariableLengthArrayType(tu8, 255).bit_length_range == (8, 2048)
    assert VariableLengthArrayType(tu8, 65535).bit_length_range == (16, 16 + 65535 * 8)

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
    assert small.compute_bit_length_values() == {2, 10, 18}

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
    assert outer.compute_bit_length_values() == {4, 12, 20, 28, 36}


class Attribute:    # TODO: should extend expression.Any to support advanced introspection/reflection.
    def __init__(self, data_type: DataType, name: str):
        self._data_type = data_type
        self._name = str(name)

        if isinstance(data_type, VoidType):
            if self._name:
                raise InvalidNameError('Void-typed fields can be used only for padding and cannot be named')
        else:
            _check_name(self._name)

    @property
    def data_type(self) -> DataType:
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
                 data_type: DataType,
                 name: str,
                 value: expression.Any):
        super(Constant, self).__init__(data_type, name)

        if not isinstance(value, expression.Primitive):
            raise InvalidConstantValueError('The constant value must be a primitive expression value')

        self._value = value
        del value

        # Interestingly, both the type of the constant and its value are instances of the same meta-type: expression.
        # BooleanType inherits from expression.Any, same as expression.Boolean.
        if isinstance(data_type, BooleanType):      # Boolean constant
            if not isinstance(self._value, expression.Boolean):
                raise InvalidConstantValueError('Invalid value for boolean constant: %r' % self._value)

        elif isinstance(data_type, IntegerType):    # Integer constant
            if isinstance(self._value, expression.Rational):
                if not self._value.is_integer():
                    raise InvalidConstantValueError('The value of an integer constant must be an integer; got %s' %
                                                    self._value)
            elif isinstance(self._value, expression.String):
                as_bytes = self._value.native_value.encode('utf8')
                if len(as_bytes) != 1:
                    raise InvalidConstantValueError('A constant string must be exactly one ASCII character long')

                if not isinstance(data_type, UnsignedIntegerType) or data_type.bit_length != 8:
                    raise InvalidConstantValueError('Constant strings can be used only with uint8')

                self._value = expression.Rational(ord(as_bytes))    # Replace string with integer
            else:
                raise InvalidConstantValueError('Invalid value type for integer constant: %r' % self._value)

        elif isinstance(data_type, FloatType):      # Floating point constant
            if not isinstance(self._value, expression.Rational):
                raise InvalidConstantValueError('Invalid value type for float constant: %r' % self._value)

        else:
            raise InvalidTypeError('Invalid constant type: %r' % data_type)

        assert isinstance(self._value, expression.Any)
        assert isinstance(self._value, expression.Rational) == isinstance(self.data_type, (FloatType, IntegerType))
        assert isinstance(self._value, expression.Boolean)  == isinstance(self.data_type, BooleanType)

        # Range check
        if isinstance(self._value, expression.Rational):
            assert isinstance(data_type, ArithmeticType)
            rng = data_type.inclusive_value_range
            if not (rng.min <= self._value.native_value <= rng.max):
                raise InvalidConstantValueError('Constant value %s exceeds the range of its data type %s' %
                                                (self._value, data_type))

    @property
    def value(self) -> expression.Any:
        return self._value

    def __str__(self) -> str:
        return '%s %s = %s' % (self.data_type, self.name, self.value)

    def __repr__(self) -> str:
        return 'Constant(data_type=%r, name=%r, value=%r)' % (self.data_type, self.name, self._value)


def _unittest_attribute() -> None:
    from pytest import raises

    assert str(Field(BooleanType(PrimitiveType.CastMode.TRUNCATED), 'flag')) == 'truncated bool flag'
    assert repr(Field(BooleanType(PrimitiveType.CastMode.TRUNCATED), 'flag')) == \
        'Field(data_type=BooleanType(bit_length=1, cast_mode=<CastMode.TRUNCATED: 1>), name=\'flag\')'

    assert str(PaddingField(VoidType(32))) == 'void32 '     # Mind the space!
    assert repr(PaddingField(VoidType(1))) == 'PaddingField(data_type=VoidType(bit_length=1), name=\'\')'

    with raises(TypeParameterError, match='.*void.*'):
        # noinspection PyTypeChecker
        repr(PaddingField(SignedIntegerType(8, PrimitiveType.CastMode.SATURATED)))   # type: ignore

    data_type = SignedIntegerType(32, PrimitiveType.CastMode.SATURATED)
    const = Constant(data_type, 'FOO_CONST', expression.Rational(-123))
    assert str(const) == 'saturated int32 FOO_CONST = -123'
    assert const.data_type is data_type
    assert const.name == 'FOO_CONST'
    assert const.value == expression.Rational(-123)

    assert repr(const) == 'Constant(data_type=%r, name=\'FOO_CONST\', value=rational(-123))' % data_type


class CompoundType(DataType):
    MAX_NAME_LENGTH = 63
    MAX_VERSION_NUMBER = 255
    NAME_COMPONENT_SEPARATOR = '.'

    def __init__(self,
                 name:          str,
                 version:       Version,
                 attributes:    typing.Iterable[Attribute],
                 deprecated:    bool,
                 fixed_port_id: typing.Optional[int],
                 source_file_path:  str):
        self._name = str(name).strip()
        self._version = version
        self._attributes = list(attributes)
        self._deprecated = bool(deprecated)
        self._fixed_port_id = None if fixed_port_id is None else int(fixed_port_id)
        self._source_file_path = str(source_file_path)

        # Name check
        if not self._name:
            raise InvalidNameError('Compound type name cannot be empty')

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
                raise AttributeNameCollision('Multiple attributes under the same name: %r' % a.name)
            else:
                used_names.add(a.name)

        # Port ID check
        port_id = self._fixed_port_id
        if port_id is not None:
            assert port_id is not None
            if isinstance(self, ServiceType):
                if not (0 <= port_id <= port_id_ranges.MAX_SERVICE_ID):
                    raise InvalidFixedPortIDError('Fixed service ID %r is not valid' % port_id)
            else:
                if not (0 <= port_id <= port_id_ranges.MAX_SUBJECT_ID):
                    raise InvalidFixedPortIDError('Fixed subject ID %r is not valid' % port_id)

        # Consistent deprecation check.
        # A non-deprecated type cannot be dependent on deprecated types.
        # A deprecated type can be dependent on anything.
        if not self.deprecated:
            for a in self._attributes:
                t = a.data_type
                if isinstance(t, CompoundType):
                    if t.deprecated:
                        raise DeprecatedDependencyError('A type cannot depend on deprecated types '
                                                        'unless it is also deprecated.')

    def is_mutually_bit_compatible_with(self, other: 'CompoundType') -> bool:
        """
        Checks for bit compatibility between two data types.
        The current implementation uses a relaxed simplified check that may yield a false-negative,
        but never a false-positive; i.e., it may fail to detect an incompatibility, but it is guaranteed
        to never report two data types as incompatible if they are compatible.
        The implementation may be updated in the future to use a strict check as defined in the specification
        while keeping the same API, so beware.
        """
        return self.compute_bit_length_values() == other.compute_bit_length_values()

    @property
    def full_name(self) -> str:
        """The full name, e.g., uavcan.node.Heartbeat"""
        return self._name

    @property
    def name_components(self) -> typing.List[str]:
        """Components of the full name as a list, e.g., ['uavcan', 'node', 'Heartbeat']"""
        return self._name.split(CompoundType.NAME_COMPONENT_SEPARATOR)

    @property
    def short_name(self) -> str:
        """The last component of the full name, e.g., Heartbeat of uavcan.node.Heartbeat"""
        return self.name_components[-1]

    @property
    def full_namespace(self) -> str:
        """The full name without the short name, e.g., uavcan.node for uavcan.node.Heartbeat"""
        return str(CompoundType.NAME_COMPONENT_SEPARATOR.join(self.name_components[:-1]))

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

    def compute_bit_length_values(self) -> typing.Set[int]:     # pragma: no cover
        raise NotImplementedError

    def _attribute(self, name: expression.String) -> expression.Any:
        """
        This is the handler for DSDL expressions like uavcan.node.Heartbeat.1.0.MODE_OPERATIONAL.
        """
        for c in self.constants:
            if c.name == name.native_value:
                assert isinstance(c.value, expression.Any)
                return c.value

        return super(CompoundType, self)._attribute(name)  # Hand over up the inheritance chain, this is important

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


class UnionType(CompoundType):
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
            raise MalformedUnionError('A tagged union cannot contain less than %d variants' %
                                      self.MIN_NUMBER_OF_VARIANTS)

        for a in attributes:
            if isinstance(a, PaddingField) or not a.name or isinstance(a.data_type, VoidType):
                raise MalformedUnionError('Padding fields not allowed in unions')

    @property
    def number_of_variants(self) -> int:
        return len(self.fields)

    @property
    def tag_bit_length(self) -> int:
        return (self.number_of_variants - 1).bit_length()

    @property
    def bit_length_range(self) -> BitLengthRange:
        blr = [f.data_type.bit_length_range for f in self.fields]
        return BitLengthRange(min=self.tag_bit_length + min([b.min for b in blr]),
                              max=self.tag_bit_length + max([b.max for b in blr]))

    def compute_bit_length_values(self) -> typing.Set[int]:
        return compute_bit_length_values_for_tagged_union(map(lambda f: f.data_type, self.fields))


class StructureType(CompoundType):
    @property
    def bit_length_range(self) -> BitLengthRange:
        blr = [f.data_type.bit_length_range for f in self.fields]
        return BitLengthRange(min=sum([b.min for b in blr]),
                              max=sum([b.max for b in blr]))

    def compute_bit_length_values(self) -> typing.Set[int]:
        return compute_bit_length_values_for_struct(map(lambda f: f.data_type, self.fields))


class ServiceType(CompoundType):
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
                                               source_file_path='')  # type: CompoundType

        response_meta_type = UnionType if response_is_union else StructureType  # type: type
        self._response_type = response_meta_type(name=name + '.Response',
                                                 version=version,
                                                 attributes=response_attributes,
                                                 deprecated=deprecated,
                                                 fixed_port_id=None,
                                                 source_file_path='')  # type: CompoundType

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
    def request_type(self) -> CompoundType:
        return self._request_type

    @property
    def response_type(self) -> CompoundType:
        return self._response_type

    def compute_bit_length_values(self) -> typing.Set[int]:     # pragma: no cover
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


def _unittest_compound_types() -> None:
    from pytest import raises

    def try_name(name: str) -> CompoundType:
        return CompoundType(name=name,
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
                      Field(SignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), 'b'),
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

    def try_union_fields(field_types: typing.List[DataType]) -> UnionType:
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
        SignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
    ]).compute_bit_length_values() == {17}

    # The reference values for the following test are explained in the array tests above
    tu8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    small = VariableLengthArrayType(tu8, 2)
    outer = FixedLengthArrayType(small, 2)   # bit length values: {4, 12, 20, 28, 36}

    # Above plus one bit to each, plus 16-bit for the unsigned integer field
    assert try_union_fields([
        outer,
        SignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
    ]).compute_bit_length_values() == {5, 13, 17, 21, 29, 37}

    def try_struct_fields(field_types: typing.List[DataType]) -> StructureType:
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
        SignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
    ]).compute_bit_length_values() == {32}

    assert try_struct_fields([]).compute_bit_length_values() == {0}   # Empty sets forbidden

    assert try_struct_fields([
        outer,
        SignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
    ]).compute_bit_length_values() == {4 + 16, 12 + 16, 20 + 16, 28 + 16, 36 + 16}

    assert try_struct_fields([outer]).compute_bit_length_values() == {4, 12, 20, 28, 36}


def compute_bit_length_values_for_struct(member_data_types: typing.Iterable['DataType']) -> typing.Set[int]:
    # As far as bit length combinations are concerned, structures are similar to static arrays.
    # Please refer to the bit length computation method for static arrays for reference.
    # The difference here is that the length value sets are not homogeneous across fields, as they
    # can be of different types, which sets structures apart from arrays. So instead of looking for
    # k-combinations, we need to find a Cartesian product of bit length value sets of each field.
    # For large structures with dynamic arrays this can be very computationally expensive.
    blv_sets = [x.compute_bit_length_values() for x in member_data_types]
    combinations = itertools.product(*blv_sets)

    # The interface prohibits empty sets at the output
    out = set(map(sum, combinations)) or {0}

    assert out and all(map(lambda x: isinstance(x, int) and x >= 0, out))
    return out      # type: ignore


def compute_bit_length_values_for_tagged_union(member_data_types: typing.Iterable['DataType']) -> typing.Set[int]:
    ts = list(member_data_types)
    del member_data_types

    if len(ts) < UnionType.MIN_NUMBER_OF_VARIANTS:
        raise MalformedUnionError('Cannot perform bit length analysis on less than {0} members because '
                                  'tagged unions are not defined for less than {0} variants'
                                  .format(UnionType.MIN_NUMBER_OF_VARIANTS))

    tag_bit_length = (len(ts) - 1).bit_length()
    assert tag_bit_length > 0

    # Unions are easy to handle because when serialized, a union is essentially just a single field,
    # prefixed with a fixed-length integer tag. So we just build a full set of combinations and then
    # add the tag length to each element. Easy.
    combinations = set()                                        # type: typing.Set[int]
    for t in ts:
        combinations |= t.compute_bit_length_values()

    out = set(map(lambda c: tag_bit_length + c, combinations))

    assert out and all(map(lambda x: isinstance(x, int) and x > 0, out))
    return out
