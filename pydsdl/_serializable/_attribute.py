# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

from .. import _expression
from ._serializable import SerializableType, TypeParameterError
from ._primitive import UnsignedIntegerType, PrimitiveType, FloatType, ArithmeticType, IntegerType, BooleanType
from ._void import VoidType
from ._name import check_name, InvalidNameError


class InvalidConstantValueError(TypeParameterError):
    pass


class InvalidTypeError(TypeParameterError):
    pass


class Attribute(_expression.Any):
    def __init__(self, data_type: SerializableType, name: str, doc: str = ""):
        self._data_type = data_type
        self._name = str(name)
        self._doc = str(doc)

        if isinstance(data_type, VoidType):
            if self._name:
                raise InvalidNameError("Void-typed fields can be used only for padding and cannot be named")
        else:
            check_name(self._name)

    @property
    def data_type(self) -> SerializableType:
        return self._data_type

    @property
    def name(self) -> str:
        """For padding fields this is an empty string."""
        return self._name

    @property
    def doc(self) -> str:
        """Docs for this attribute without the leading #."""
        return self._doc

    def __hash__(self) -> int:
        return hash((self._data_type, self._name))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Attribute):
            return (self._data_type == other._data_type) and (self._name == other.name)
        return NotImplemented  # pragma: no cover

    def __str__(self) -> str:
        """Returns the normalized DSDL representation of the attribute."""
        return ("%s %s" % (self.data_type, self.name)).strip()

    def __repr__(self) -> str:
        return "%s(data_type=%r, name=%r)" % (self.__class__.__name__, self.data_type, self.name)


class Field(Attribute):
    pass


class PaddingField(Field):
    def __init__(self, data_type: VoidType, doc: str = ""):
        if not isinstance(data_type, VoidType):
            raise TypeParameterError("Padding fields must be of the void type")

        super().__init__(data_type, "", doc)


class Constant(Attribute):
    def __init__(self, data_type: SerializableType, name: str, value: _expression.Any, doc: str = ""):
        super().__init__(data_type, name, doc)

        if not isinstance(value, _expression.Primitive):
            raise InvalidConstantValueError("The constant value must be a primitive expression value")

        self._value = value
        del value

        # Interestingly, both the type of the constant and its value are instances of the same meta-type: expression.
        # BooleanType inherits from expression.Any, same as expression.Boolean.
        if isinstance(data_type, BooleanType):  # Boolean constant
            if not isinstance(self._value, _expression.Boolean):
                raise InvalidConstantValueError("Invalid value for boolean constant: %r" % self._value)

        elif isinstance(data_type, IntegerType):  # Integer constant
            if isinstance(self._value, _expression.Rational):
                if not self._value.is_integer():
                    raise InvalidConstantValueError(
                        "The value of an integer constant must be an integer; got %s" % self._value
                    )
            elif isinstance(self._value, _expression.String):
                as_bytes = self._value.native_value.encode("utf8")
                if len(as_bytes) != 1:
                    raise InvalidConstantValueError("A constant string must be exactly one ASCII character long")

                if not isinstance(data_type, UnsignedIntegerType) or data_type.bit_length != 8:
                    raise InvalidConstantValueError("Constant strings can be used only with uint8")

                self._value = _expression.Rational(ord(as_bytes))  # Replace string with integer
            else:
                raise InvalidConstantValueError("Invalid value type for integer constant: %r" % self._value)

        elif isinstance(data_type, FloatType):  # Floating point constant
            if not isinstance(self._value, _expression.Rational):
                raise InvalidConstantValueError("Invalid value type for float constant: %r" % self._value)

        else:
            raise InvalidTypeError("Invalid constant type: %r" % data_type)

        assert isinstance(self._value, _expression.Any)
        assert isinstance(self._value, _expression.Rational) == isinstance(self.data_type, (FloatType, IntegerType))
        assert isinstance(self._value, _expression.Boolean) == isinstance(self.data_type, BooleanType)

        # Range check
        if isinstance(self._value, _expression.Rational):
            assert isinstance(data_type, ArithmeticType)
            rng = data_type.inclusive_value_range
            if not (rng.min <= self._value.native_value <= rng.max):
                raise InvalidConstantValueError(
                    "Constant value %s exceeds the range of its data type %s" % (self._value, data_type)
                )

    @property
    def value(self) -> _expression.Any:
        """
        The result of evaluating the constant initialization expression.
        The value is guaranteed to be compliant with the constant's own type -- it is checked at the evaluation time.
        The compliance rules are defined in the Specification.
        """
        return self._value

    def __hash__(self) -> int:
        return hash((self._data_type, self._name, self._value))

    def __eq__(self, other: object) -> bool:
        """Constants are equal if their type, name, and value are equal."""
        if isinstance(other, Constant):
            return super().__eq__(other) and (self._value == other._value)
        return NotImplemented  # pragma: no cover

    def __str__(self) -> str:
        """Returns the normalized DSDL representation of the constant and its value."""
        return "%s %s = %s" % (self.data_type, self.name, self.value)

    def __repr__(self) -> str:
        return "Constant(data_type=%r, name=%r, value=%r)" % (self.data_type, self.name, self._value)


def _unittest_attribute() -> None:
    from pytest import raises
    from ._primitive import SignedIntegerType

    assert str(Field(BooleanType(PrimitiveType.CastMode.SATURATED), "flag")) == "saturated bool flag"
    assert (
        repr(Field(BooleanType(PrimitiveType.CastMode.SATURATED), "flag"))
        == "Field(data_type=BooleanType(bit_length=1, cast_mode=<CastMode.SATURATED: 0>), name='flag')"
    )

    assert str(PaddingField(VoidType(32))) == "void32"
    assert repr(PaddingField(VoidType(1))) == "PaddingField(data_type=VoidType(bit_length=1), name='')"

    assert Field(UnsignedIntegerType(1, PrimitiveType.CastMode.SATURATED), "flag") == Field(
        UnsignedIntegerType(1, PrimitiveType.CastMode.SATURATED), "flag"
    )
    assert hash(Field(UnsignedIntegerType(1, PrimitiveType.CastMode.SATURATED), "flag")) == hash(
        Field(UnsignedIntegerType(1, PrimitiveType.CastMode.SATURATED), "flag")
    )

    assert Field(UnsignedIntegerType(1, PrimitiveType.CastMode.TRUNCATED), "flag") != Field(
        UnsignedIntegerType(1, PrimitiveType.CastMode.SATURATED), "flag"
    )
    assert hash(Field(UnsignedIntegerType(1, PrimitiveType.CastMode.TRUNCATED), "flag")) != hash(
        Field(UnsignedIntegerType(1, PrimitiveType.CastMode.SATURATED), "flag")
    )

    with raises(TypeParameterError, match=".*void.*"):
        # noinspection PyTypeChecker
        repr(PaddingField(SignedIntegerType(8, PrimitiveType.CastMode.SATURATED)))  # type: ignore

    data_type = SignedIntegerType(32, PrimitiveType.CastMode.SATURATED)
    const = Constant(data_type, "FOO_CONST", _expression.Rational(-123))
    assert str(const) == "saturated int32 FOO_CONST = -123"
    assert const.data_type is data_type
    assert const.name == "FOO_CONST"
    assert const.value == _expression.Rational(-123)

    assert repr(const) == "Constant(data_type=%r, name='FOO_CONST', value=rational(-123))" % data_type

    assert Constant(data_type, "FOO_CONST", _expression.Rational(-123)) == const
    assert Constant(data_type, "FOO_CONST", _expression.Rational(-124)) != const
    assert hash(Constant(data_type, "FOO_CONST", _expression.Rational(-123))) == hash(const)
    assert hash(Constant(data_type, "FOO_CONST", _expression.Rational(-124))) != hash(const)
