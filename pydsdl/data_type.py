#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import enum


BitLengthRange = typing.NamedTuple('BitLengthRange', [('min', int), ('max', int)])

IntegerValueRange = typing.NamedTuple('IntegerValueRange', [('min', int), ('max', int)])

FloatValueRange = typing.NamedTuple('RealValueRange', [('min', float), ('max', float)])

Version = typing.NamedTuple('Version', [('minor', int), ('major', int)])


class InvalidBitLengthException(ValueError):
    pass


class DataType:
    """
    Invoking __str__() on a data type returns its uniform normalized definition, e.g.:
        - uavcan.node.Heartbeat.1.0[<=36]
        - truncated float16[<=36]
    """

    @property
    def bit_length_range(self) -> BitLengthRange:
        raise NotImplementedError

    def __str__(self):
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
            raise InvalidBitLengthException('Bit length must be positive')

        if self._bit_length > self.MAX_BIT_LENGTH:
            raise InvalidBitLengthException('Bit length cannot exceed %r' % self.MAX_BIT_LENGTH)

    @property
    def bit_length(self) -> int:
        """All primitives are of a fixed bit length, hence just one value is enough."""
        return self._bit_length

    @property
    def bit_length_range(self) -> BitLengthRange:
        """All primitives are of a fixed bit length, hence just one value is enough."""
        return BitLengthRange(self.bit_length, self.bit_length)

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

    def __str__(self):
        raise NotImplementedError

    def __repr__(self):
        return '%s(bit_length=%r, cast_mode=%r)' % (self.__class__.__name__, self.bit_length, self.cast_mode)


class BooleanType(PrimitiveType):
    def __init__(self, cast_mode: PrimitiveType.CastMode):
        super(BooleanType, self).__init__(bit_length=1, cast_mode=cast_mode)

    def __str__(self):
        return self._cast_mode_name + ' bool'


class ArithmeticType(PrimitiveType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(ArithmeticType, self).__init__(bit_length, cast_mode)

    def __str__(self):
        raise NotImplementedError


class IntegerType(ArithmeticType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(IntegerType, self).__init__(bit_length, cast_mode)

    @property
    def inclusive_value_range(self) -> IntegerValueRange:
        raise NotImplementedError

    def __str__(self):
        raise NotImplementedError


class SignedIntegerType(IntegerType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(SignedIntegerType, self).__init__(bit_length, cast_mode)

        if self._bit_length < 2:
            raise InvalidBitLengthException('Bit length of signed integer types cannot be less than 2')

    @property
    def inclusive_value_range(self) -> IntegerValueRange:
        uint_max_half = ((1 << self.bit_length) - 1) // 2
        return IntegerValueRange(min=-uint_max_half - 1,
                                 max=+uint_max_half)

    def __str__(self):
        return self._cast_mode_name + ' int' + str(self.bit_length)


class UnsignedIntegerType(IntegerType):
    def __init__(self,
                 bit_length: int,
                 cast_mode: PrimitiveType.CastMode):
        super(UnsignedIntegerType, self).__init__(bit_length, cast_mode)

    @property
    def inclusive_value_range(self) -> IntegerValueRange:
        return IntegerValueRange(min=0, max=(1 << self.bit_length) - 1)

    def __str__(self):
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
            raise InvalidBitLengthException('Invalid bit length for float type: %d' % bit_length) from None

    @property
    def inclusive_value_range(self) -> FloatValueRange:
        return FloatValueRange(min=-self._magnitude,
                               max=+self._magnitude)

    def __str__(self):
        return self._cast_mode_name + ' float' + str(self.bit_length)


class VoidType(DataType):
    MAX_BIT_LENGTH = 64

    def __init__(self, bit_length: int):
        super(VoidType, self).__init__()
        self._bit_length = int(bit_length)

        if self._bit_length < 1:
            raise InvalidBitLengthException('Bit length must be positive')

        if self._bit_length > self.MAX_BIT_LENGTH:
            raise InvalidBitLengthException('Bit length cannot exceed %r' % self.MAX_BIT_LENGTH)

    @property
    def bit_length(self) -> int:
        """All primitives are of a fixed bit length, hence just one value is enough."""
        return self._bit_length

    @property
    def bit_length_range(self) -> BitLengthRange:
        return BitLengthRange(self.bit_length, self.bit_length)

    def __str__(self):
        return 'void%d' % self.bit_length

    def __repr__(self):
        return 'VoidType(bit_length=%d)' % self.bit_length


class ArrayType(DataType):
    def __init__(self, element_type: DataType):
        super(ArrayType, self).__init__()
        self._element_type = element_type

    @property
    def element_type(self) -> DataType:
        return self._element_type

    @property
    def bit_length_range(self) -> BitLengthRange:
        raise NotImplementedError

    def __str__(self):
        raise NotImplementedError


class StaticArrayType(ArrayType):
    def __init__(self,
                 element_type: DataType,
                 size: int):
        super(StaticArrayType, self).__init__(element_type)
        self._size = int(size)

        if self._size < 1:
            raise ValueError('Size cannot be less than 1')

    @property
    def size(self) -> int:
        return self._size

    @property
    def bit_length_range(self) -> BitLengthRange:
        return BitLengthRange(min=self.element_type.bit_length_range.min * self.size,
                              max=self.element_type.bit_length_range.max * self.size)

    def __str__(self):
        return '%s[%d]' % (self.element_type, self.size)

    def __repr__(self):
        return 'StaticArrayType(element_type=%r, size=%r)' % (self.element_type, self.size)


class DynamicArrayType(ArrayType):
    def __init__(self,
                 element_type: DataType,
                 max_size: int):
        super(DynamicArrayType, self).__init__(element_type)
        self._max_size = int(max_size)

        if self._max_size < 1:
            raise ValueError('Max size cannot be less than 1')

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def bit_length_range(self) -> BitLengthRange:
        length_prefix_bit_length = self.max_size.bit_length()
        return BitLengthRange(min=length_prefix_bit_length,
                              max=length_prefix_bit_length + self.element_type.bit_length_range.max * self.max_size)

    def __str__(self):
        return '%s[<=%d]' % (self.element_type, self.max_size)

    def __repr__(self):
        return 'DynamicArrayType(element_type=%r, max_size=%r)' % (self.element_type, self.max_size)


class Attribute:
    def __init__(self,
                 data_type: DataType,
                 name: str):
        self._data_type = data_type
        self._name = str(name)

    @property
    def data_type(self) -> DataType:
        return self._data_type

    @property
    def name(self) -> str:
        return self._name

    def __str__(self):
        return '%s %s' % (self.data_type, self.name)

    def __repr__(self):
        return '%s(data_type=%r, name=%r)' % (self.__class__.__name__, self.data_type, self.name)


class Field(Attribute):
    pass


class PaddingField(Field):
    def __init__(self, data_type: DataType):
        super(PaddingField, self).__init__(data_type, '')


class Constant(Attribute):
    Value = typing.Union[float, int, str]

    def __init__(self,
                 data_type: DataType,
                 name: str,
                 value: 'Constant.Value',
                 initialization_expression: str):
        super(Constant, self).__init__(data_type, name)
        self._value = value
        self._initialization_expression = str(initialization_expression)

    @property
    def value(self) -> 'Constant.Value':
        return self._value

    @property
    def initialization_expression(self) -> str:
        return self._initialization_expression

    def __str__(self):
        return '%s %s = %s' % (self.data_type, self.name, self.value)

    def __repr__(self):
        return 'Constant(data_type=%r, name=%r, value=%r, initialization_expression=%r)' % \
            (self.data_type, self.name, self.value, self.initialization_expression)


class CompoundType(DataType):
    MAX_NAME_LENGTH = 63

    MAX_VERSION_NUMBER = 255

    def __init__(self,
                 name:             str,
                 version:          Version,
                 attributes:       typing.Iterable[Attribute],
                 deprecated:       bool,
                 static_port_id:   typing.Optional[int]):
        self._name = str(name).strip()
        self._version = version
        self._attributes = list(attributes)
        self._deprecated = bool(deprecated)
        self._static_port_id = None if static_port_id is None else int(static_port_id)

        if not self._name:
            raise ValueError('Name cannot be empty')

        if len(self._name) > self.MAX_NAME_LENGTH:
            raise ValueError('Name is too long: %r is longer than %d characters' %
                             (self._name, self.MAX_NAME_LENGTH))

        version_valid = (0 <= self._version.major <= self.MAX_VERSION_NUMBER) and\
                        (0 <= self._version.minor <= self.MAX_VERSION_NUMBER) and\
                        ((self._version.major + self._version.minor) > 0)

        if not version_valid:
            raise ValueError('Invalid version numbers: %r', self._version)

    @property
    def name(self) -> str:
        return self._name

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
    def static_port_id(self) -> typing.Optional[int]:
        return self._static_port_id

    @property
    def bit_length_range(self) -> BitLengthRange:
        raise NotImplementedError

    def __str__(self):
        return '%s.%d.%d' % (self.name, self.version.major, self.version.minor)

    def __repr__(self):
        return '%s(name=%r, version=%r, fields=%r, constants=%r, deprecated=%r, static_port_id=%r)' % \
           (self.__class__.__name__,
            self.name,
            self.version,
            self.fields,
            self.constants,
            self.deprecated,
            self.static_port_id)


class UnionType(CompoundType):
    @property
    def number_of_variants(self) -> int:
        return len(self.fields)

    @property
    def bit_length_range(self) -> BitLengthRange:
        blr = [f.data_type.bit_length_range for f in self.fields]
        tag_bit_length = self.number_of_variants.bit_length()
        return BitLengthRange(min=tag_bit_length + min([b.min for b in blr]),
                              max=tag_bit_length + max([b.max for b in blr]))


class StructureType(CompoundType):
    @property
    def bit_length_range(self) -> BitLengthRange:
        blr = [f.data_type.bit_length_range for f in self.fields]
        return BitLengthRange(min=sum([b.min for b in blr]),
                              max=sum([b.max for b in blr]))


class ServiceType(CompoundType):
    def __init__(self,
                 name:                str,
                 version:             Version,
                 request_attributes:  typing.Iterable[Attribute],
                 response_attributes: typing.Iterable[Attribute],
                 request_is_union:    bool,
                 response_is_union:   bool,
                 deprecated:          bool,
                 static_port_id:      typing.Optional[int]):
        request_meta_type = UnionType if request_is_union else StructureType
        self._request_type = request_meta_type(name=name + '.Request',
                                               version=version,
                                               attributes=request_attributes,
                                               deprecated=deprecated,
                                               static_port_id=None)

        response_meta_type = UnionType if response_is_union else StructureType
        self._response_type = response_meta_type(name=name + '.Response',
                                                 version=version,
                                                 attributes=response_attributes,
                                                 deprecated=deprecated,
                                                 static_port_id=None)

        container_attributes = [
            Field(data_type=self._request_type,  name='request'),
            Field(data_type=self._response_type, name='response'),
        ]

        super(ServiceType, self).__init__(name=name,
                                          version=version,
                                          attributes=container_attributes,
                                          deprecated=deprecated,
                                          static_port_id=static_port_id)

    @property
    def request_type(self) -> CompoundType:
        return self._request_type

    @property
    def response_type(self) -> CompoundType:
        return self._response_type

    @property
    def bit_length_range(self) -> BitLengthRange:
        """This data type is not directly serializable, so we always return zero."""
        return BitLengthRange(0, 0)
