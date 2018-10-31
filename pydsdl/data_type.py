#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import re
import enum
import string
import typing
import itertools
from .port_id_ranges import is_valid_regulated_subject_id, is_valid_regulated_service_id


BitLengthRange = typing.NamedTuple('BitLengthRange', [('min', int), ('max', int)])

IntegerValueRange = typing.NamedTuple('IntegerValueRange', [('min', int), ('max', int)])

FloatValueRange = typing.NamedTuple('RealValueRange', [('min', float), ('max', float)])

Version = typing.NamedTuple('Version', [('major', int), ('minor', int)])


_VALID_FIRST_CHARACTERS_OF_NAME = string.ascii_letters + '_'
_VALID_CONTINUATION_CHARACTERS_OF_NAME = _VALID_FIRST_CHARACTERS_OF_NAME + string.digits

# Disallowed name patterns apply to any part of any name, e.g.,
# an attribute name, a namespace component, type name, etc.
_DISALLOWED_NAME_PATTERNS = [
    r'(?i)(bool|uint|int|void|float)\d*$',          # Data type like names
    r'(?i)(saturated|truncated)$',                  # Keywords
    r'(?i)(con|prn|aux|nul|com\d?|lpt\d?)$',        # Reserved by the specification (MS Windows compatibility)
]


class TypeParameterError(ValueError):
    """This exception is not related to parsing errors, so it does not inherit from the same root."""
    pass


class InvalidBitLengthError(TypeParameterError):
    pass


class InvalidNumberOfElementsError(TypeParameterError):
    pass


class InvalidNameError(TypeParameterError):
    pass


class InvalidVersionError(TypeParameterError):
    pass


class ConstantTypeMismatchError(TypeParameterError):
    pass


class InvalidConstantValueError(TypeParameterError):
    pass


class InvalidTypeError(TypeParameterError):
    pass


class AttributeNameCollision(TypeParameterError):
    pass


class InvalidRegulatedPortIDError(TypeParameterError):
    pass


class MalformedUnionError(TypeParameterError):
    pass


class DataType:
    """
    Invoking __str__() on a data type returns its uniform normalized definition, e.g.:
        - uavcan.node.Heartbeat.1.0[<=36]
        - truncated float16[<=36]
    """

    @property
    def bit_length_range(self) -> BitLengthRange:       # pragma: no cover
        raise NotImplementedError

    @property
    def bit_length_values(self) -> typing.Set[int]:     # pragma: no cover
        """
        A set of all possible bit length values for the encoded representation of the data type.
        With complex data types, a full bit length set estimation may lead to a combinatorial explosion.
        This property must never return an empty set.
        The following invariants hold:
        >>> self.bit_length_range.min == min(self.bit_length_values)
        >>> self.bit_length_range.max == max(self.bit_length_values)
        """
        raise NotImplementedError

    def __str__(self) -> str:   # pragma: no cover
        raise NotImplementedError


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

    @property
    def bit_length_range(self) -> BitLengthRange:
        """All primitives are of a fixed bit length, hence just one value is enough."""
        return BitLengthRange(self.bit_length, self.bit_length)

    @property
    def bit_length_values(self) -> typing.Set[int]:
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
    def inclusive_value_range(self) -> IntegerValueRange:   # pragma: no cover
        raise NotImplementedError

    def __str__(self) -> str:   # pragma: no cover
        raise NotImplementedError


class SignedIntegerType(IntegerType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(SignedIntegerType, self).__init__(bit_length, cast_mode)

    @property
    def inclusive_value_range(self) -> IntegerValueRange:
        uint_max_half = ((1 << self.bit_length) - 1) // 2
        return IntegerValueRange(min=-uint_max_half - 1,
                                 max=+uint_max_half)

    def __str__(self) -> str:
        return self._cast_mode_name + ' int' + str(self.bit_length)


class UnsignedIntegerType(IntegerType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(UnsignedIntegerType, self).__init__(bit_length, cast_mode)

    @property
    def inclusive_value_range(self) -> IntegerValueRange:
        return IntegerValueRange(min=0, max=(1 << self.bit_length) - 1)

    def __str__(self) -> str:
        return self._cast_mode_name + ' uint' + str(self.bit_length)


class FloatType(ArithmeticType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(FloatType, self).__init__(bit_length, cast_mode)

        try:
            self._magnitude = {
                16: 65504.0,
                32: 3.40282346638528859812e+38,
                64: 1.79769313486231570815e+308,
            }[self.bit_length]
        except KeyError:
            raise InvalidBitLengthError('Invalid bit length for float type: %d' % bit_length) from None

    @property
    def inclusive_value_range(self) -> FloatValueRange:
        return FloatValueRange(min=-self._magnitude,
                               max=+self._magnitude)

    def __str__(self) -> str:
        return self._cast_mode_name + ' float' + str(self.bit_length)


def _unittest_primitive() -> None:
    from pytest import raises, approx

    assert str(BooleanType(PrimitiveType.CastMode.SATURATED)) == 'saturated bool'

    assert str(SignedIntegerType(15, PrimitiveType.CastMode.SATURATED)) == 'saturated int15'
    assert SignedIntegerType(64, PrimitiveType.CastMode.SATURATED).bit_length_range == (64, 64)
    assert SignedIntegerType(8, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (-128, 127)

    assert str(UnsignedIntegerType(15, PrimitiveType.CastMode.TRUNCATED)) == 'truncated uint15'
    assert UnsignedIntegerType(53, PrimitiveType.CastMode.SATURATED).bit_length_range == (53, 53)
    assert UnsignedIntegerType(32, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (0, 0xFFFFFFFF)

    assert str(FloatType(64, PrimitiveType.CastMode.SATURATED)) == 'saturated float64'
    assert FloatType(32, PrimitiveType.CastMode.SATURATED).bit_length_range == (32, 32)
    assert FloatType(16, PrimitiveType.CastMode.SATURATED).inclusive_value_range == (approx(-65504), approx(65504))

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
        """All primitives are of a fixed bit length, hence just one value is enough."""
        return self._bit_length

    @property
    def bit_length_values(self) -> typing.Set[int]:
        return {self._bit_length}

    @property
    def bit_length_range(self) -> BitLengthRange:
        return BitLengthRange(self.bit_length, self.bit_length)

    def __str__(self) -> str:
        return 'void%d' % self.bit_length

    def __repr__(self) -> str:
        return 'VoidType(bit_length=%d)' % self.bit_length


def _unittest_void() -> None:
    from pytest import raises

    assert VoidType(1).bit_length_range == (1, 1)
    assert str(VoidType(13)) == 'void13'
    assert repr(VoidType(64)) == 'VoidType(bit_length=64)'
    assert VoidType(22).bit_length_values == {22}

    with raises(InvalidBitLengthError):
        VoidType(1)
        VoidType(0)

    with raises(InvalidBitLengthError):
        VoidType(64)
        VoidType(65)


class ArrayType(DataType):
    def __init__(self, element_type: DataType):
        super(ArrayType, self).__init__()
        self._element_type = element_type

    @property
    def element_type(self) -> DataType:
        return self._element_type

    @property
    def bit_length_range(self) -> BitLengthRange:       # pragma: no cover
        raise NotImplementedError

    @property
    def bit_length_values(self) -> typing.Set[int]:     # pragma: no cover
        raise NotImplementedError

    def __str__(self) -> str:   # pragma: no cover
        raise NotImplementedError


class StaticArrayType(ArrayType):
    def __init__(self,
                 element_type: DataType,
                 size: int):
        super(StaticArrayType, self).__init__(element_type)
        self._size = int(size)

        if self._size < 1:
            raise InvalidNumberOfElementsError('Array size cannot be less than 1')

    @property
    def size(self) -> int:
        return self._size

    @property
    def bit_length_range(self) -> BitLengthRange:
        return BitLengthRange(min=self.element_type.bit_length_range.min * self.size,
                              max=self.element_type.bit_length_range.max * self.size)

    @property
    def bit_length_values(self) -> typing.Set[int]:
        # Combinatorics is tricky.
        # The cornerstone concept here is the standard library function "combinations_with_replacement()",
        # which implements the standard n-combination function.
        combinations = itertools.combinations_with_replacement(self.element_type.bit_length_values, self.size)
        # We do not care about permutations because the final bit length is invariant to the order of
        # serialized elements. Having found all combinations, we need to obtain a set of resulting length values.
        return set(map(sum, combinations))

    def __str__(self) -> str:
        return '%s[%d]' % (self.element_type, self.size)

    def __repr__(self) -> str:
        return 'StaticArrayType(element_type=%r, size=%r)' % (self.element_type, self.size)


def _unittest_static_array() -> None:
    from pytest import raises

    su8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.SATURATED)
    ti64 = SignedIntegerType(64, cast_mode=PrimitiveType.CastMode.TRUNCATED)

    assert str(StaticArrayType(su8, 4)) == 'saturated uint8[4]'
    assert str(StaticArrayType(ti64, 1)) == 'truncated int64[1]'

    assert StaticArrayType(su8, 4).bit_length_range == (32, 32)
    assert StaticArrayType(su8, 200).size == 200
    assert StaticArrayType(ti64, 200).element_type is ti64

    with raises(InvalidNumberOfElementsError):
        StaticArrayType(ti64, 0)

    assert repr(StaticArrayType(ti64, 128)) == \
        'StaticArrayType(element_type=SignedIntegerType(bit_length=64, cast_mode=<CastMode.TRUNCATED: 1>), size=128)'

    small = StaticArrayType(su8, 2)
    assert small.bit_length_values == {16}


class DynamicArrayType(ArrayType):
    def __init__(self,
                 element_type: DataType,
                 max_size: int):
        super(DynamicArrayType, self).__init__(element_type)
        self._max_size = int(max_size)

        if self._max_size < 1:
            raise InvalidNumberOfElementsError('Max array size cannot be less than 1')

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def length_prefix_bit_length(self) -> int:
        return self.max_size.bit_length()

    @property
    def bit_length_range(self) -> BitLengthRange:
        return BitLengthRange(
            min=self.length_prefix_bit_length,
            max=self.length_prefix_bit_length + self.element_type.bit_length_range.max * self.max_size
        )

    @property
    def bit_length_values(self) -> typing.Set[int]:
        # Please refer to the corresponding implementation for the static array.
        # The idea here is that we treat the dynamic array as a combination of static arrays of different sizes,
        # from zero elements up to the maximum number of elements.
        output = set()           # type: typing.Set[int]
        for size in range(self.max_size + 1):
            combinations = itertools.combinations_with_replacement(self.element_type.bit_length_values, size)
            output |= set(map(lambda c: sum(c) + self.length_prefix_bit_length, combinations))

        return output

    def __str__(self) -> str:
        return '%s[<=%d]' % (self.element_type, self.max_size)

    def __repr__(self) -> str:
        return 'DynamicArrayType(element_type=%r, max_size=%r)' % (self.element_type, self.max_size)


def _unittest_dynamic_array() -> None:
    from pytest import raises

    tu8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    si64 = SignedIntegerType(64, cast_mode=PrimitiveType.CastMode.SATURATED)

    assert str(DynamicArrayType(tu8, 4))    == 'truncated uint8[<=4]'
    assert str(DynamicArrayType(si64, 255)) == 'saturated int64[<=255]'

    # Mind the length prefix!
    assert DynamicArrayType(tu8, 3).bit_length_range == (2, 26)
    assert DynamicArrayType(tu8, 1).bit_length_range == (1, 9)
    assert DynamicArrayType(tu8, 255).bit_length_range == (8, 2048)
    assert DynamicArrayType(tu8, 65535).bit_length_range == (16, 16 + 65535 * 8)

    assert DynamicArrayType(tu8, 200).max_size == 200
    assert DynamicArrayType(tu8, 200).element_type is tu8

    with raises(InvalidNumberOfElementsError):
        DynamicArrayType(si64, 0)

    assert repr(DynamicArrayType(si64, 128)) == \
        'DynamicArrayType(element_type=SignedIntegerType(bit_length=64, cast_mode=<CastMode.SATURATED: 0>), ' \
        'max_size=128)'

    # The following was computed manually; it is easy to validate:
    # we have zero, one, or two elements of 8 bits each; plus 2 bit wide tag; therefore:
    # {2 + 0, 2 + 8, 2 + 16}
    small = DynamicArrayType(tu8, 2)
    assert small.bit_length_values == {2, 10, 18}

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
    outer = StaticArrayType(small, 2)
    assert outer.bit_length_values == {4, 12, 20, 28, 36}


class Attribute:
    def __init__(self,
                 data_type: DataType,
                 name: str,
                 skip_name_check: bool=False):
        self._data_type = data_type
        self._name = str(name)

        if not skip_name_check:
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
    def __init__(self, data_type: DataType):
        super(PaddingField, self).__init__(data_type, '', skip_name_check=True)


class Constant(Attribute):
    def __init__(self,
                 data_type: DataType,
                 name: str,
                 value: typing.Any,
                 initialization_expression: str):
        super(Constant, self).__init__(data_type, name)
        self._initialization_expression = str(initialization_expression)

        # Type check
        if isinstance(data_type, BooleanType):
            if isinstance(value, bool):
                self._value = bool(value)  # type: typing.Union[float, int, bool]
            else:
                raise InvalidConstantValueError('Invalid value for boolean constant: %r' % value)

        elif isinstance(data_type, IntegerType):
            if isinstance(value, int):
                self._value = int(value)
            elif isinstance(value, str):
                if len(value.encode('utf8')) != 1:
                    raise InvalidConstantValueError('A constant string must be exactly one ASCII character long')

                if not isinstance(data_type, UnsignedIntegerType) or data_type.bit_length != 8:
                    raise InvalidConstantValueError('Constant strings can be used only with uint8')

                self._value = ord(value.encode('utf8'))
            else:
                raise InvalidConstantValueError('Invalid value type for integer constant: %r' % value)

        elif isinstance(data_type, FloatType):
            # Remember, bool is a subtype of int
            if isinstance(value, (int, float)) and not isinstance(value, bool):  # Implicit conversion
                self._value = float(value)
            else:
                raise InvalidConstantValueError('Invalid value type for float constant: %r' % value)

        else:
            raise InvalidTypeError('Invalid constant type: %r' % data_type)

        del value
        assert isinstance(self._value, (bool, int, float))
        assert isinstance(self.data_type, FloatType)   == isinstance(self._value, float)
        assert isinstance(self.data_type, BooleanType) == isinstance(self._value, bool)
        # Note that bool is a subclass of int, so we don't check against IntegerType

        # Range check
        if not isinstance(data_type, BooleanType):
            assert isinstance(data_type, (IntegerType, FloatType))
            rng = data_type.inclusive_value_range
            if not (rng.min <= self._value <= rng.max):
                raise InvalidConstantValueError('Constant value %r exceeds the range of its data type %r' %
                                                (self._value, data_type))

    @property
    def value(self) -> typing.Union[float, int, bool]:
        return self._value

    @property
    def initialization_expression(self) -> str:
        return self._initialization_expression

    def __str__(self) -> str:
        return '%s %s = %s' % (self.data_type, self.name, self.value)

    def __repr__(self) -> str:
        return 'Constant(data_type=%r, name=%r, value=%r, initialization_expression=%r)' % \
            (self.data_type, self.name, self._value, self._initialization_expression)


def _unittest_attribute() -> None:
    assert str(Field(BooleanType(PrimitiveType.CastMode.TRUNCATED), 'flag')) == 'truncated bool flag'
    assert repr(Field(BooleanType(PrimitiveType.CastMode.TRUNCATED), 'flag')) == \
        'Field(data_type=BooleanType(bit_length=1, cast_mode=<CastMode.TRUNCATED: 1>), name=\'flag\')'

    assert str(PaddingField(VoidType(32))) == 'void32 '     # Mind the space!
    assert repr(PaddingField(VoidType(1))) == 'PaddingField(data_type=VoidType(bit_length=1), name=\'\')'

    data_type = SignedIntegerType(32, PrimitiveType.CastMode.SATURATED)
    const = Constant(data_type, 'FOO_CONST', -123, '-0x7B')
    assert str(const) == 'saturated int32 FOO_CONST = -123'
    assert const.data_type is data_type
    assert const.name == 'FOO_CONST'
    assert const.value == -123
    assert const.initialization_expression == '-0x7B'

    assert repr(const) == \
        'Constant(data_type=%r, name=\'FOO_CONST\', value=-123, initialization_expression=\'-0x7B\')' % data_type


class CompoundType(DataType):
    MAX_NAME_LENGTH = 63
    MAX_VERSION_NUMBER = 255
    NAME_COMPONENT_SEPARATOR = '.'

    def __init__(self,
                 name:              str,
                 version:           Version,
                 attributes:        typing.Iterable[Attribute],
                 deprecated:        bool,
                 regulated_port_id: typing.Optional[int],
                 source_file_path:  str):
        self._name = str(name).strip()
        self._version = version
        self._attributes = list(attributes)
        self._deprecated = bool(deprecated)
        self._regulated_port_id = None if regulated_port_id is None else int(regulated_port_id)
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
            raise InvalidVersionError('Invalid version numbers: %r', self._version)

        # Attribute check
        used_names = set()      # type: typing.Set[str]
        for a in self._attributes:
            if a.name and a.name in used_names:
                raise AttributeNameCollision('Multiple attributes under the same name: %r' % a.name)
            else:
                used_names.add(a.name)

        # Port ID check
        port_id = self._regulated_port_id
        if port_id is not None:
            assert port_id is not None
            if isinstance(self, ServiceType):
                if not is_valid_regulated_service_id(port_id, self.root_namespace):
                    raise InvalidRegulatedPortIDError('Regulated service ID %r is not valid' % port_id)
            else:
                if not is_valid_regulated_subject_id(port_id, self.root_namespace):
                    raise InvalidRegulatedPortIDError('Regulated subject ID %r is not valid' % port_id)

    def is_bit_compatible_with(self, other: 'CompoundType') -> bool:
        """
        Checks for bit compatibility between two data types.
        The current implementation uses a relaxed simplified check that may yield a false-negative,
        but never a false-positive; i.e., it may fail to detect an incompatibility, but it is guaranteed
        to never report two data types as incompatible if they are compatible.
        The implementation may be updated in the future to use a strict check as defined in the specification
        while keeping the same API, so beware.
        """
        return self.bit_length_values == other.bit_length_values

    @property
    def name(self) -> str:
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
    def namespace(self) -> str:
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
    def regulated_port_id(self) -> typing.Optional[int]:
        return self._regulated_port_id

    @property
    def has_regulated_port_id(self) -> bool:
        return self.regulated_port_id is not None

    @property
    def source_file_path(self) -> str:
        """Empty if this is a synthesized type, e.g. a service request or response section."""
        return self._source_file_path

    @property
    def bit_length_range(self) -> BitLengthRange:       # pragma: no cover
        raise NotImplementedError

    @property
    def bit_length_values(self) -> typing.Set[int]:     # pragma: no cover
        raise NotImplementedError

    def __str__(self) -> str:
        return '%s.%d.%d' % (self.name, self.version.major, self.version.minor)

    def __repr__(self) -> str:
        return '%s(name=%r, version=%r, fields=%r, constants=%r, deprecated=%r, regulated_port_id=%r)' % \
           (self.__class__.__name__,
            self.name,
            self.version,
            self.fields,
            self.constants,
            self.deprecated,
            self.regulated_port_id)


class UnionType(CompoundType):
    MIN_NUMBER_OF_VARIANTS = 2

    def __init__(self,
                 name:              str,
                 version:           Version,
                 attributes:        typing.Iterable[Attribute],
                 deprecated:        bool,
                 regulated_port_id: typing.Optional[int],
                 source_file_path:  str):
        # Proxy all parameters directly to the base type - I wish we could do that
        # with kwargs while preserving the type information
        super(UnionType, self).__init__(name=name,
                                        version=version,
                                        attributes=attributes,
                                        deprecated=deprecated,
                                        regulated_port_id=regulated_port_id,
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

    @property
    def bit_length_values(self) -> typing.Set[int]:
        # Unions are easy to handle because when serialized, a union is essentially just a single field,
        # prefixed with a fixed-length integer tag. So we just build a full set of combinations and then
        # add the tag length to each element. Easy.
        combinations = set()     # type: typing.Set[int]
        for f in self.fields:
            combinations |= f.data_type.bit_length_values

        return set(map(lambda c: self.tag_bit_length + c, combinations))


class StructureType(CompoundType):
    @property
    def bit_length_range(self) -> BitLengthRange:
        blr = [f.data_type.bit_length_range for f in self.fields]
        return BitLengthRange(min=sum([b.min for b in blr]),
                              max=sum([b.max for b in blr]))

    @property
    def bit_length_values(self) -> typing.Set[int]:
        return self.get_field_offset_values(field_index=len(self.fields))

    def get_field_offset_values(self, field_index: int) -> typing.Set[int]:
        """
        This function is mostly useful for field alignment and offset checks.
        :param field_index: Limits the output set as if the structure were to end before the
                            specified field index. If set to len(self.fields), makes the function
                            behave as the bit_length_values property.
        """
        if not (0 <= field_index <= len(self.fields)):      # pragma: no cover
            raise ValueError('Invalid field index: %d' % field_index)

        # As far as bit length combinations are concerned, structures are similar to static arrays.
        # Please refer to the bit length computation method for static arrays for reference.
        # The difference here is that the length value sets are not homogeneous across fields, as they
        # can be of different types, which sets structures apart from arrays. So instead of looking for
        # k-combinations, we need to find a Cartesian product of bit length value sets of each field.
        # For large structures with dynamic arrays this can be very computationally expensive.
        blv_sets = [x.data_type.bit_length_values for x in self.fields[:field_index]]
        combinations = itertools.product(*blv_sets)

        # The property protocol prohibits empty sets at the output
        return set(map(sum, combinations)) or {0}


class ServiceType(CompoundType):
    def __init__(self,
                 name:                str,
                 version:             Version,
                 request_attributes:  typing.Iterable[Attribute],
                 response_attributes: typing.Iterable[Attribute],
                 request_is_union:    bool,
                 response_is_union:   bool,
                 deprecated:          bool,
                 regulated_port_id:   typing.Optional[int],
                 source_file_path:    str):
        request_meta_type = UnionType if request_is_union else StructureType
        self._request_type = request_meta_type(name=name + '.Request',
                                               version=version,
                                               attributes=request_attributes,
                                               deprecated=deprecated,
                                               regulated_port_id=None,
                                               source_file_path='')

        response_meta_type = UnionType if response_is_union else StructureType
        self._response_type = response_meta_type(name=name + '.Response',
                                                 version=version,
                                                 attributes=response_attributes,
                                                 deprecated=deprecated,
                                                 regulated_port_id=None,
                                                 source_file_path='')

        container_attributes = [
            Field(data_type=self._request_type,  name='request'),
            Field(data_type=self._response_type, name='response'),
        ]

        super(ServiceType, self).__init__(name=name,
                                          version=version,
                                          attributes=container_attributes,
                                          deprecated=deprecated,
                                          regulated_port_id=regulated_port_id,
                                          source_file_path=source_file_path)

    @property
    def request_type(self) -> CompoundType:
        return self._request_type

    @property
    def response_type(self) -> CompoundType:
        return self._response_type

    @property
    def bit_length_range(self) -> BitLengthRange:       # pragma: no cover
        raise NotImplementedError('Service types are not directly serializable. Use either request or response.')

    @property
    def bit_length_values(self) -> typing.Set[int]:     # pragma: no cover
        raise NotImplementedError('Service types are not directly serializable. Use either request or response.')


def _check_name(name: str) -> None:
    if not name:
        raise InvalidNameError('Name or namespace component cannot be empty')

    if name[0] not in _VALID_FIRST_CHARACTERS_OF_NAME:
        raise InvalidNameError('Name or namespace component cannot start with %r' % name[0])

    for char in name:
        if char not in _VALID_CONTINUATION_CHARACTERS_OF_NAME:
            raise InvalidNameError('Name or namespace component cannot contain %r' % char)

    for pat in _DISALLOWED_NAME_PATTERNS:
        if re.match(pat, name):
            raise InvalidNameError('Disallowed name: %r matches the following pattern: %s' % (name, pat))


def _unittest_compound_types() -> None:
    from pytest import raises

    def try_name(name: str) -> CompoundType:
        return CompoundType(name=name,
                            version=Version(0, 1),
                            attributes=[],
                            deprecated=False,
                            regulated_port_id=None,
                            source_file_path='')

    with raises(InvalidNameError, match='(?i).*empty.*'):
        try_name('')

    with raises(InvalidNameError, match='(?i).*root namespace.*'):
        try_name('Type')

    with raises(InvalidNameError, match='(?i).*long.*'):
        try_name('namespace.another.deeper.' * 10 + 'LongTypeName')

    with raises(InvalidNameError, match='(?i).*component.*empty.*'):
        try_name('namespace.ns..Type')

    with raises(InvalidNameError, match='(?i).*component.*empty.*'):
        try_name('.namespace.ns.Type')

    with raises(InvalidNameError, match='(?i).*cannot start with.*'):
        try_name('namespace.0ns.Type')

    with raises(InvalidNameError, match='(?i).*cannot start with.*'):
        try_name('namespace.ns.0Type')

    with raises(InvalidNameError, match='(?i).*cannot contain.*'):
        try_name('namespace.n-s.Type')

    assert try_name('root.nested.Type').name == 'root.nested.Type'
    assert try_name('root.nested.Type').namespace == 'root.nested'
    assert try_name('root.nested.Type').root_namespace == 'root'
    assert try_name('root.nested.Type').short_name == 'Type'

    with raises(MalformedUnionError, match='.*variants.*'):
        UnionType(name='a.A',
                  version=Version(0, 1),
                  attributes=[],
                  deprecated=False,
                  regulated_port_id=None,
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
                  regulated_port_id=None,
                  source_file_path='')

    _check_name('abc')
    _check_name('_abc')
    _check_name('abc0')

    with raises(InvalidNameError):
        _check_name('0abc')

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

    def try_union_fields(field_types: typing.List[DataType]) -> UnionType:
        atr = []
        for i, t in enumerate(field_types):
            atr.append(Field(t, '_%d' % i))

        return UnionType(name='a.A',
                         version=Version(0, 1),
                         attributes=atr,
                         deprecated=False,
                         regulated_port_id=None,
                         source_file_path='')

    assert try_union_fields([
        UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
        SignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
    ]).bit_length_values == {17}

    # The reference values for the following test are explained in the array tests above
    tu8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    small = DynamicArrayType(tu8, 2)
    outer = StaticArrayType(small, 2)   # bit length values: {4, 12, 20, 28, 36}

    # Above plus one bit to each, plus 16-bit for the unsigned integer field
    assert try_union_fields([
        outer,
        SignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
    ]).bit_length_values == {5, 13, 17, 21, 29, 37}

    def try_struct_fields(field_types: typing.List[DataType]) -> StructureType:
        atr = []
        for i, t in enumerate(field_types):
            atr.append(Field(t, '_%d' % i))

        return StructureType(name='a.A',
                             version=Version(0, 1),
                             attributes=atr,
                             deprecated=False,
                             regulated_port_id=None,
                             source_file_path='')

    assert try_struct_fields([
        UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
        SignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
    ]).bit_length_values == {32}

    assert try_struct_fields([]).bit_length_values == {0}   # Empty sets forbidden

    assert try_struct_fields([
        outer,
        SignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
    ]).bit_length_values == {4 + 16, 12 + 16, 20 + 16, 28 + 16, 36 + 16}

    assert try_struct_fields([outer]).bit_length_values == {4, 12, 20, 28, 36}
