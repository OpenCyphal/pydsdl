# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

# pylint: disable=protected-access

import abc
import typing
import operator
import fractions
import unicodedata
from . import _any


# noinspection PyAbstractClass
class Primitive(_any.Any):
    @property
    @abc.abstractmethod
    def native_value(self) -> typing.Any:
        """
        Yields an appropriate Python-native representation of the contained value,
        like :class:`fractions.Fraction`, :class:`str`, etc.
        Specializations define covariant return types.
        """
        raise NotImplementedError  # pragma: no cover


class Boolean(Primitive):
    TYPE_NAME = "bool"

    def __init__(self, value: bool = False):
        if not isinstance(value, bool):
            raise ValueError("Cannot construct a Boolean instance from " + type(value).__name__)

        self._value = value  # type: bool

    @property
    def native_value(self) -> bool:
        return self._value

    def __hash__(self) -> int:
        return int(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Boolean):
            return self._value == other._value
        return NotImplemented  # pragma: no cover

    def __str__(self) -> str:
        return "true" if self._value else "false"

    def __bool__(self) -> bool:  # For use in expressions without accessing "native_value"
        return self._value

    def _logical_not(self) -> "Boolean":
        return Boolean(not self._value)

    def _logical_and(self, right: _any.Any) -> "Boolean":
        if isinstance(right, Boolean):
            return Boolean(self._value and right._value)
        raise _any.UndefinedOperatorError

    def _logical_or(self, right: _any.Any) -> "Boolean":
        if isinstance(right, Boolean):
            return Boolean(self._value or right._value)
        raise _any.UndefinedOperatorError

    def _equal(self, right: _any.Any) -> "Boolean":
        if isinstance(right, Boolean):
            return Boolean(self._value == right._value)
        raise _any.UndefinedOperatorError


class Rational(Primitive):
    TYPE_NAME = "rational"

    def __init__(self, value: typing.Union[int, fractions.Fraction]):
        # We must support float as well, because some operators on Fraction sometimes yield float, e.g. power.
        if not isinstance(value, (int, float, fractions.Fraction)):
            raise ValueError("Cannot construct a Rational instance from " + type(value).__name__)
        self._value = fractions.Fraction(value)  # type: fractions.Fraction

    @property
    def native_value(self) -> fractions.Fraction:
        return self._value

    def as_native_integer(self) -> int:
        """
        Returns the inferior as a native integer,
        unless it cannot be represented as such without the loss of precision; i.e., if denominator != 1,
        in which case an invalid operand exception is thrown.
        """
        if self.is_integer():
            return self._value.numerator
        raise _any.InvalidOperandError("Rational %s is not an integer" % self._value)

    def is_integer(self) -> bool:
        """Whether the demonimator equals one."""
        return self._value.denominator == 1

    def __hash__(self) -> int:
        return hash(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Rational):
            return self._value == other._value
        return NotImplemented  # pragma: no cover

    def __str__(self) -> str:
        return str(self._value)

    #
    # Unary operators.
    #
    def _positive(self) -> "Rational":
        return Rational(+self._value)

    def _negative(self) -> "Rational":
        return Rational(-self._value)

    #
    # Binary comparison operators.
    #
    def _generic_compare(self, right: _any.Any, impl: typing.Callable[[typing.Any, typing.Any], bool]) -> Boolean:
        if isinstance(right, Rational):
            return Boolean(impl(self._value, right._value))
        raise _any.UndefinedOperatorError

    def _equal(self, right: _any.Any) -> "Boolean":
        return self._generic_compare(right, operator.eq)

    def _less_or_equal(self, right: _any.Any) -> "Boolean":
        return self._generic_compare(right, operator.le)

    def _greater_or_equal(self, right: _any.Any) -> "Boolean":
        return self._generic_compare(right, operator.ge)

    def _less(self, right: _any.Any) -> "Boolean":
        return self._generic_compare(right, operator.lt)

    def _greater(self, right: _any.Any) -> "Boolean":
        return self._generic_compare(right, operator.gt)

    #
    # Binary bitwise operators.
    #
    def _generic_bitwise(
        self, right: _any.Any, impl: typing.Callable[[typing.Any, typing.Any], typing.Any]
    ) -> "Rational":
        if isinstance(right, Rational):
            return Rational(impl(self.as_native_integer(), right.as_native_integer()))  # Throws if not an integer.
        raise _any.UndefinedOperatorError

    def _bitwise_or(self, right: _any.Any) -> "Rational":
        return self._generic_bitwise(right, operator.or_)

    def _bitwise_xor(self, right: _any.Any) -> "Rational":
        return self._generic_bitwise(right, operator.xor)

    def _bitwise_and(self, right: _any.Any) -> "Rational":
        return self._generic_bitwise(right, operator.and_)

    #
    # Binary arithmetic operators.
    #
    def _generic_arithmetic(
        self, right: _any.Any, impl: typing.Callable[[typing.Any, typing.Any], typing.Any]
    ) -> "Rational":
        if isinstance(right, Rational):
            try:
                result = impl(self._value, right._value)
            except ZeroDivisionError:
                raise _any.InvalidOperandError("Cannot divide %s by zero" % self._value) from None
            else:
                return Rational(result)
        else:
            raise _any.UndefinedOperatorError

    def _add(self, right: _any.Any) -> "Rational":
        return self._generic_arithmetic(right, operator.add)

    def _subtract(self, right: _any.Any) -> "Rational":
        return self._generic_arithmetic(right, operator.sub)

    def _multiply(self, right: _any.Any) -> "Rational":
        return self._generic_arithmetic(right, operator.mul)

    def _divide(self, right: _any.Any) -> "Rational":
        return self._generic_arithmetic(right, operator.truediv)

    def _modulo(self, right: _any.Any) -> "Rational":
        return self._generic_arithmetic(right, operator.mod)

    def _power(self, right: _any.Any) -> "Rational":
        return self._generic_arithmetic(right, operator.pow)


class String(Primitive):
    TYPE_NAME = "string"

    def __init__(self, value: str):
        if not isinstance(value, str):
            raise ValueError("Cannot construct a String instance from " + type(value).__name__)
        self._value = value  # type: str

    @property
    def native_value(self) -> str:
        return self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, String):
            return self._value == other._value
        return NotImplemented  # pragma: no cover

    def __str__(self) -> str:
        return repr(self._value)

    def _add(self, right: _any.Any) -> "String":
        if isinstance(right, String):
            return String(self._value + right._value)
        raise _any.UndefinedOperatorError

    def _equal(self, right: _any.Any) -> Boolean:
        if isinstance(right, String):

            def normalized(s: str) -> str:
                return unicodedata.normalize("NFC", s)

            return Boolean(normalized(self._value) == normalized(right._value))

        raise _any.UndefinedOperatorError
