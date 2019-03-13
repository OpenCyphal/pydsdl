#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import operator
from fractions import Fraction

from .exceptions import InvalidOperandError


_TypeList = typing.Union[type, typing.Tuple[type, ...]]


class OperatorNotImplementedError(InvalidOperandError):
    pass


class OperandTypeNotSupportedError(OperatorNotImplementedError):
    pass


#
# Operator wrappers.
# These wrappers serve two purposes:
#   - Late binding, as explained here: https://stackoverflow.com/questions/55148139/referring-to-a-pure-virtual-method
#   - Automatic left-right operand swapping when necessary (for some polyadic operators).
#
def op1_logical_not(left: 'Boolean') -> 'Boolean':
    return left.op1_logical_not()


def op1_inversion_positive(left: 'Any') -> 'Any':
    return left.op1_inversion_positive()


def op1_inversion_negative(left: 'Any') -> 'Any':
    return left.op1_inversion_negative()


def op2_logical_or(left: 'Boolean', right: 'Boolean') -> 'Boolean':
    return left.op2_logical_or(right)


def op2_logical_and(left: 'Boolean', right: 'Boolean') -> 'Boolean':
    return left.op2_logical_and(right)


def op2_comparison_equal(left: 'Any', right: 'Any') -> 'Boolean':
    return left.op2_comparison_equal(right)


def op2_comparison_not_equal(left: 'Any', right: 'Any') -> 'Boolean':
    return left.op2_comparison_not_equal(right)


def op2_comparison_less_or_equal(left: 'Any', right: 'Any') -> 'Boolean':
    return left.op2_comparison_less_or_equal(right)


def op2_comparison_greater_or_equal(left: 'Any', right: 'Any') -> 'Boolean':
    return left.op2_comparison_greater_or_equal(right)


def op2_comparison_less(left: 'Any', right: 'Any') -> 'Boolean':
    return left.op2_comparison_less(right)


def op2_comparison_greater(left: 'Any', right: 'Any') -> 'Boolean':
    return left.op2_comparison_greater(right)


def op2_bitwise_or(left: 'Any', right: 'Any') -> 'Any':
    return left.op2_bitwise_or(right)


def op2_bitwise_xor(left: 'Any', right: 'Any') -> 'Any':
    return left.op2_bitwise_xor(right)


def op2_bitwise_and(left: 'Any', right: 'Any') -> 'Any':
    return left.op2_bitwise_and(right)


def op2_additive_add(left: 'Any', right: 'Any') -> 'Any':
    try:
        return left.op2_additive_add(right)
    except OperatorNotImplementedError:
        return right.swapped_op2_additive_add(left)


def op2_additive_subtract(left: 'Any', right: 'Any') -> 'Any':
    try:
        return left.op2_additive_subtract(right)
    except OperatorNotImplementedError:
        return right.swapped_op2_additive_subtract(left)


def op2_multiplicative_multiply(left: 'Any', right: 'Any') -> 'Any':
    try:
        return left.op2_multiplicative_multiply(right)
    except OperatorNotImplementedError:
        return right.swapped_op2_multiplicative_multiply(left)


def op2_multiplicative_floor_division(left: 'Any', right: 'Any') -> 'Any':
    try:
        return left.op2_multiplicative_floor_division(right)
    except OperatorNotImplementedError:
        return right.swapped_op2_multiplicative_floor_division(left)


def op2_multiplicative_true_division(left: 'Any', right: 'Any') -> 'Any':
    try:
        return left.op2_multiplicative_true_division(right)
    except OperatorNotImplementedError:
        return right.swapped_op2_multiplicative_true_division(left)


def op2_multiplicative_modulo(left: 'Any', right: 'Any') -> 'Any':
    try:
        return left.op2_multiplicative_modulo(right)
    except OperatorNotImplementedError:
        return right.swapped_op2_multiplicative_modulo(left)


def op2_exponential_power(left: 'Any', right: 'Any') -> 'Any':
    try:
        return left.op2_exponential_power(right)
    except OperatorNotImplementedError:
        return right.swapped_op2_exponential_power(left)

# TODO: a decorator that swaps the arguments automatically; also a set of module-internal swapped wrappers.


#
# Expression type implementations.
#
class Any:
    # This attribute must be specified in the derived classes.
    # It contains the name of the data type implemented by the class.
    TYPE_NAME = None    # type: str

    def __hash__(self) -> int:
        raise NotImplementedError

    def __eq__(self, other: object) -> bool:
        raise NotImplementedError

    def __str__(self) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        return self.TYPE_NAME + '(' + str(self) + ')'

    #
    # Unary operators.
    #
    def op1_logical_not(self) -> 'Boolean':
        raise OperatorNotImplementedError

    def op1_inversion_positive(self) -> 'Any':
        raise OperatorNotImplementedError

    def op1_inversion_negative(self) -> 'Any':
        raise OperatorNotImplementedError

    #
    # Binary operators.
    # The types of the operators defined here must match the specification.
    # Make sure to use least generic types in the derived classes - Python allows covariant return types.
    #
    def op2_logical_or(self, right: 'Boolean') -> 'Boolean':
        raise OperatorNotImplementedError

    def op2_logical_and(self, right: 'Boolean') -> 'Boolean':
        raise OperatorNotImplementedError

    def op2_comparison_equal(self, right: 'Any') -> 'Boolean':
        raise OperatorNotImplementedError

    def op2_comparison_not_equal(self, right: 'Any') -> 'Boolean':
        return self.op2_comparison_equal(right).op1_logical_not()       # Default implementation

    def op2_comparison_less_or_equal(self, right: 'Any') -> 'Boolean':
        raise OperatorNotImplementedError

    def op2_comparison_greater_or_equal(self, right: 'Any') -> 'Boolean':
        raise OperatorNotImplementedError

    def op2_comparison_less(self, right: 'Any') -> 'Boolean':
        raise OperatorNotImplementedError

    def op2_comparison_greater(self, right: 'Any') -> 'Boolean':
        raise OperatorNotImplementedError

    def op2_bitwise_or(self, right: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def op2_bitwise_xor(self, right: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def op2_bitwise_and(self, right: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def op2_additive_add(self, right: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def op2_additive_subtract(self, right: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def op2_multiplicative_multiply(self, right: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def op2_multiplicative_floor_division(self, right: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def op2_multiplicative_true_division(self, right: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def op2_multiplicative_modulo(self, right: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def op2_exponential_power(self, right: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    #
    # Binary operators with swapped arguments are invoked when the corresponding non-swapped version
    # throws an OperatorNotImplementedError (including derived exceptions). This is like the Python's
    # built-in methods __radd__(), __rmul__(), etc.
    #
    def swapped_op2_additive_add(self, left: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def swapped_op2_additive_subtract(self, left: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def swapped_op2_multiplicative_multiply(self, left: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def swapped_op2_multiplicative_floor_division(self, left: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def swapped_op2_multiplicative_true_division(self, left: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def swapped_op2_multiplicative_modulo(self, left: 'Any') -> 'Any':
        raise OperatorNotImplementedError

    def swapped_op2_exponential_power(self, left: 'Any') -> 'Any':
        raise OperatorNotImplementedError


# noinspection PyAbstractClass
class Primitive(Any):
    @property
    def native_value(self) -> typing.Any:
        raise NotImplementedError


class Boolean(Primitive):
    TYPE_NAME = 'bool'

    def __init__(self, value: bool = False):
        _enforce_initializer_type(value, bool)
        self._value = value  # type: bool

    @property
    def native_value(self) -> bool:
        return self._value

    def __hash__(self) -> int:
        return int(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Boolean):
            return self._value == other._value
        else:
            raise NotImplementedError

    def __str__(self) -> str:
        return 'true' if self._value else 'false'

    def op1_logical_not(self) -> 'Boolean':
        return Boolean(not self._value)

    def op2_logical_and(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Boolean):
            return Boolean(self._value and right._value)
        else:
            raise OperandTypeNotSupportedError

    def op2_logical_or(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Boolean):
            return Boolean(self._value or right._value)
        else:
            raise OperandTypeNotSupportedError

    def op2_comparison_equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Boolean):
            return Boolean(self._value == right._value)
        else:
            raise OperandTypeNotSupportedError


class Rational(Primitive):
    TYPE_NAME = 'rational'

    def __init__(self, value: typing.Union[int, Fraction]):
        _enforce_initializer_type(value, (int, Fraction))
        self._value = Fraction(value)  # type: Fraction

    @property
    def native_value(self) -> Fraction:
        return self._value

    def as_integer(self) -> int:
        """
        Returns the inferior as a native integer,
        unless it cannot be represented as such without the loss of precision; i.e., if denominator != 1.
        """
        if self._value.denominator == 1:
            return self._value.numerator
        else:
            raise InvalidOperandError('Rational %s is not an integer' % self._value)

    def __hash__(self) -> int:
        return hash(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Rational):
            return self._value == other._value
        else:
            raise NotImplementedError

    def __str__(self) -> str:
        return str(self._value)

    #
    # Unary operators.
    #
    def op1_inversion_positive(self) -> 'Rational':
        return Rational(+self._value)

    def op1_inversion_negative(self) -> 'Rational':
        return Rational(-self._value)

    #
    # Binary comparison operators.
    #
    def _op2_generic_compare(self,
                             right: 'Any',
                             impl: typing.Callable[[typing.Any, typing.Any], bool]) -> Boolean:
        if isinstance(right, Rational):
            return Boolean(impl(self._value, right._value))
        else:
            raise OperandTypeNotSupportedError

    def op2_comparison_equal(self, right: 'Any') -> 'Boolean':
        return self._op2_generic_compare(right, operator.eq)

    def op2_comparison_less_or_equal(self, right: 'Any') -> 'Boolean':
        return self._op2_generic_compare(right, operator.le)

    def op2_comparison_greater_or_equal(self, right: 'Any') -> 'Boolean':
        return self._op2_generic_compare(right, operator.ge)

    def op2_comparison_less(self, right: 'Any') -> 'Boolean':
        return self._op2_generic_compare(right, operator.lt)

    def op2_comparison_greater(self, right: 'Any') -> 'Boolean':
        return self._op2_generic_compare(right, operator.gt)

    #
    # Binary bitwise operators.
    #
    def _op2_generic_bitwise(self,
                             right: 'Any',
                             impl: typing.Callable[[typing.Any, typing.Any], typing.Any]) -> 'Rational':
        if isinstance(right, Rational):
            return Rational(impl(self.as_integer(), right.as_integer()))    # Throws if not an integer.
        else:
            raise OperandTypeNotSupportedError

    def op2_bitwise_or(self, right: 'Any') -> 'Rational':
        return self._op2_generic_bitwise(right, operator.or_)

    def op2_bitwise_xor(self, right: 'Any') -> 'Rational':
        return self._op2_generic_bitwise(right, operator.xor)

    def op2_bitwise_and(self, right: 'Any') -> 'Rational':
        return self._op2_generic_bitwise(right, operator.and_)

    #
    # Binary arithmetic operators.
    #
    def _op2_generic_arithmetic(self,
                                right: 'Any',
                                impl: typing.Callable[[typing.Any, typing.Any], typing.Any]) -> 'Rational':
        if isinstance(right, Rational):
            try:
                result = impl(self._value, right._value)
            except ZeroDivisionError:
                raise InvalidOperandError('Cannot divide %s by zero' % self._value)
            else:
                return Rational(result)
        else:
            raise OperandTypeNotSupportedError

    def op2_additive_add(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.add)

    def op2_additive_subtract(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.sub)

    def op2_multiplicative_multiply(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.mul)

    def op2_multiplicative_floor_division(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.floordiv)

    def op2_multiplicative_true_division(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.truediv)

    def op2_multiplicative_modulo(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.mod)

    def op2_exponential_power(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.pow)


class String(Primitive):
    TYPE_NAME = 'string'

    def __init__(self, value: str):
        _enforce_initializer_type(value, str)
        self._value = value  # type: str

    @property
    def native_value(self) -> str:
        return self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, String):
            return self._value == other._value
        else:
            raise NotImplementedError

    def __str__(self) -> str:
        return self._value

    def op2_additive_add(self, right: 'Any') -> 'String':
        if isinstance(right, String):
            return String(self._value + right._value)
        else:
            raise OperandTypeNotSupportedError

    def op2_comparison_equal(self, right: 'Any') -> Boolean:
        if isinstance(right, String):
            return Boolean(self._value == right._value)
        else:
            raise OperandTypeNotSupportedError


# noinspection PyAbstractClass
class Container(Any):
    @property
    def element_type(self) -> typing.Type[Any]:
        raise NotImplementedError

    def __iter__(self) -> typing.Iterator[typing.Any]:
        raise NotImplementedError


class Set(Container):
    TYPE_NAME = 'set'

    # noinspection PyProtectedMember
    class _Decorator:
        ReturnType = typing.TypeVar('ReturnType')

        @staticmethod
        def homotypic_binary_operator(inferior: typing.Callable[['Set', 'Set'], ReturnType]) \
                -> typing.Callable[['Set', 'Set'], ReturnType]:
            def wrapper(self: 'Set', other: 'Set') -> 'Set._Decorator.ReturnType':
                assert isinstance(self, Set) and isinstance(other, Set)
                if self.element_type == other.element_type:
                    return inferior(self, other)
                else:
                    raise InvalidOperandError('The requested binary operator is defined only for sets '
                                              'that share the same element type. The different types are: %r, %r' %
                                              (self.element_type.TYPE_NAME, other.element_type.TYPE_NAME))
            return wrapper

    def __init__(self, elements: typing.Iterable[Any]):
        list_of_elements = list(elements)   # type: typing.List[Any]
        del elements
        if len(list_of_elements) < 1:
            raise OperandTypeNotSupportedError('Zero-length sets are currently not permitted because '
                                               'of associated type deduction issues. This may change later.')

        element_types = set(map(type, list_of_elements))
        if len(element_types) != 1:
            # This also weeds out covariant sets, although our barbie-size type system is unaware of that.
            raise InvalidOperandError('Heterogeneous sets are not permitted')

        self._element_type = list(element_types)[1]  # type: typing.Type[Any]
        self._value = frozenset(list_of_elements)    # type: typing.FrozenSet[Any]

        if not issubclass(self._element_type, Any):
            raise ValueError('Invalid element type: %r' % self._element_type)

    def __iter__(self) -> typing.Iterator[typing.Any]:
        return iter(self._value)

    @property
    def element_type(self) -> typing.Type[Any]:
        return self._element_type

    def __hash__(self) -> int:
        return hash(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Set):
            return self._value == other._value
        else:
            raise NotImplementedError

    def __str__(self) -> str:
        return '{%s}' % ', '.join(map(str, self._value))    # This is recursive.

    #
    # Set algebra implementation.
    #
    @_Decorator.homotypic_binary_operator
    def _is_equal_to(self, right: 'Set') -> bool:
        return self._value == right._value

    @_Decorator.homotypic_binary_operator
    def _is_superset_of(self, right: 'Set') -> bool:
        return self._value.issuperset(right._value)

    @_Decorator.homotypic_binary_operator
    def _is_subset_of(self, right: 'Set') -> bool:
        return self._value.issubset(right._value)

    @_Decorator.homotypic_binary_operator
    def _is_proper_superset_of(self, right: 'Set') -> bool:
        return self._is_superset_of(right) and not self._is_equal_to(right)

    @_Decorator.homotypic_binary_operator
    def _is_proper_subset_of(self, right: 'Set') -> bool:
        return self._is_subset_of(right) and not self._is_equal_to(right)

    @_Decorator.homotypic_binary_operator
    def _create_union_with(self, right: 'Set') -> 'Set':
        return Set(self._value.union(right._value))

    @_Decorator.homotypic_binary_operator
    def _create_intersection_with(self, right: 'Set') -> 'Set':
        return Set(self._value.intersection(right._value))

    @_Decorator.homotypic_binary_operator
    def _create_disjunctive_union_with(self, right: 'Set') -> 'Set':
        return Set(self._value.symmetric_difference(right._value))

    #
    # Set comparison.
    #
    def op2_comparison_equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_equal_to(right))
        else:
            raise OperandTypeNotSupportedError

    def op2_comparison_less_or_equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_subset_of(right))
        else:
            raise OperandTypeNotSupportedError

    def op2_comparison_greater_or_equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_superset_of(right))
        else:
            raise OperandTypeNotSupportedError

    def op2_comparison_less(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_proper_subset_of(right))
        else:
            raise OperandTypeNotSupportedError

    def op2_comparison_greater(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_proper_superset_of(right))
        else:
            raise OperandTypeNotSupportedError

    #
    # Set algebra operators that yield a new set.
    #
    def op2_bitwise_or(self, right: 'Any') -> 'Set':
        if isinstance(right, Set):
            return self._create_union_with(right)
        else:
            raise OperandTypeNotSupportedError

    def op2_bitwise_xor(self, right: 'Any') -> 'Set':
        if isinstance(right, Set):
            return self._create_disjunctive_union_with(right)
        else:
            raise OperandTypeNotSupportedError

    def op2_bitwise_and(self, right: 'Any') -> 'Set':
        if isinstance(right, Set):
            return self._create_intersection_with(right)
        else:
            raise OperandTypeNotSupportedError

    #
    # Elementwise application.
    # https://stackoverflow.com/questions/55148139/referring-to-a-pure-virtual-method
    #
    def _op2_elementwise(self, impl: typing.Callable[['Any', 'Any'], 'Any'], right: 'Any') -> 'Set':
        if isinstance(right, Primitive):
            return Set(impl(x, right) for x in self)
        else:
            raise OperandTypeNotSupportedError

    def op2_additive_add(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_additive_add, right)

    def op2_additive_subtract(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_additive_subtract, right)

    def op2_multiplicative_multiply(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_multiplicative_multiply, right)

    def op2_multiplicative_floor_division(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_multiplicative_floor_division, right)

    def op2_multiplicative_true_division(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_multiplicative_true_division, right)

    def op2_multiplicative_modulo(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_multiplicative_modulo, right)

    def op2_exponential_power(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_exponential_power, right)


def _enforce_initializer_type(value: typing.Any, expected_type: _TypeList) -> None:
    if not isinstance(value, expected_type):
        raise ValueError('Expected type %r, found %r' % (expected_type, type(value)))
