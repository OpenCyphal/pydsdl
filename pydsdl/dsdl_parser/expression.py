#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import operator
import functools
from fractions import Fraction

from .exceptions import InvalidOperandError


_TypeList = typing.Union[type, typing.Tuple[type, ...]]

_OperatorReturnType = typing.TypeVar('_OperatorReturnType')


class OperatorNotImplementedError(InvalidOperandError):
    """Thrown when there is no matching operator for the supplied arguments."""
    def __init__(self):
        super(OperatorNotImplementedError, self).__init__(
            'The requested operator is not defined for the provided arguments')


#
# Operator wrappers. These wrappers serve two purposes:
#   - Late binding, as explained here: https://stackoverflow.com/questions/55148139/referring-to-a-pure-virtual-method
#   - Automatic left-right operand swapping when necessary (for some polyadic operators).
# The operators are prefixed with "op" followed by a number representing the arity of the operator.
#
def _binary_operator(direct_operator: typing.Callable[['Any', 'Any'], _OperatorReturnType]) \
        -> typing.Callable[['Any', 'Any'], _OperatorReturnType]:
    swapped_method_name = '_%s_swapped' % direct_operator.__name__

    @functools.wraps(direct_operator)
    def wrapper(left: 'Any', right: 'Any') -> 'Any':
        if not isinstance(left, Any) or not isinstance(right, Any):
            raise ValueError('Operators are only defined for implementations of Any; found this: %r, %r' %
                             (type(left), type(right)))
        try:
            result = direct_operator(left, right)
        except OperatorNotImplementedError:
            if type(left) != type(right) and hasattr(right, swapped_method_name):  # Right and Left are swapped.
                result = getattr(right, swapped_method_name)(left)
            else:
                raise

        assert isinstance(result, Any)
        return result

    return wrapper


def op1_logical_not(left: 'Any') -> 'Boolean':                          # noinspection PyProtectedMember
    return left._op1_logical_not()


def op1_positive(left: 'Any') -> 'Any':                                 # noinspection PyProtectedMember
    return left._op1_positive()


def op1_negative(left: 'Any') -> 'Any':                                 # noinspection PyProtectedMember
    return left._op1_negative()


@_binary_operator
def op2_logical_or(left: 'Any', right: 'Any') -> 'Boolean':             # noinspection PyProtectedMember
    return left._op2_logical_or(right)


@_binary_operator
def op2_logical_and(left: 'Any', right: 'Any') -> 'Boolean':            # noinspection PyProtectedMember
    return left._op2_logical_and(right)


@_binary_operator
def op2_equal(left: 'Any', right: 'Any') -> 'Boolean':                  # noinspection PyProtectedMember
    return left._op2_equal(right)


@_binary_operator
def op2_not_equal(left: 'Any', right: 'Any') -> 'Boolean':              # noinspection PyProtectedMember
    return left._op2_not_equal(right)


@_binary_operator
def op2_less_or_equal(left: 'Any', right: 'Any') -> 'Boolean':          # noinspection PyProtectedMember
    return left._op2_less_or_equal(right)


@_binary_operator
def op2_greater_or_equal(left: 'Any', right: 'Any') -> 'Boolean':       # noinspection PyProtectedMember
    return left._op2_greater_or_equal(right)


@_binary_operator
def op2_less(left: 'Any', right: 'Any') -> 'Boolean':                   # noinspection PyProtectedMember
    return left._op2_less(right)


@_binary_operator
def op2_greater(left: 'Any', right: 'Any') -> 'Boolean':                # noinspection PyProtectedMember
    return left._op2_greater(right)


@_binary_operator
def op2_bitwise_or(left: 'Any', right: 'Any') -> 'Any':                 # noinspection PyProtectedMember
    return left._op2_bitwise_or(right)


@_binary_operator
def op2_bitwise_xor(left: 'Any', right: 'Any') -> 'Any':                # noinspection PyProtectedMember
    return left._op2_bitwise_xor(right)


@_binary_operator
def op2_bitwise_and(left: 'Any', right: 'Any') -> 'Any':                # noinspection PyProtectedMember
    return left._op2_bitwise_and(right)


@_binary_operator
def op2_add(left: 'Any', right: 'Any') -> 'Any':                        # noinspection PyProtectedMember
    return left._op2_add(right)


@_binary_operator
def op2_subtract(left: 'Any', right: 'Any') -> 'Any':                   # noinspection PyProtectedMember
    return left._op2_subtract(right)


@_binary_operator
def op2_multiply(left: 'Any', right: 'Any') -> 'Any':                   # noinspection PyProtectedMember
    return left._op2_multiply(right)


@_binary_operator
def op2_floor_divide(left: 'Any', right: 'Any') -> 'Any':             # noinspection PyProtectedMember
    return left._op2_floor_divide(right)


@_binary_operator
def op2_divide(left: 'Any', right: 'Any') -> 'Any':                   # noinspection PyProtectedMember
    return left._op2_divide(right)


@_binary_operator
def op2_modulo(left: 'Any', right: 'Any') -> 'Any':                     # noinspection PyProtectedMember
    return left._op2_modulo(right)


@_binary_operator
def op2_power(left: 'Any', right: 'Any') -> 'Any':                      # noinspection PyProtectedMember
    return left._op2_power(right)


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
    def _op1_logical_not(self) -> 'Boolean': raise OperatorNotImplementedError

    def _op1_positive(self) -> 'Any': raise OperatorNotImplementedError

    def _op1_negative(self) -> 'Any': raise OperatorNotImplementedError

    #
    # Binary operators.
    # The types of the operators defined here must match the specification.
    # Make sure to use least generic types in the derived classes - Python allows covariant return types.
    #
    def _op2_logical_or(self, right: 'Any') -> 'Boolean': raise OperatorNotImplementedError

    def _op2_logical_and(self, right: 'Any') -> 'Boolean': raise OperatorNotImplementedError

    def _op2_equal(self, right: 'Any') -> 'Boolean': raise OperatorNotImplementedError

    def _op2_not_equal(self, right: 'Any') -> 'Boolean':  # noinspection PyProtectedMember
        return self._op2_equal(right)._op1_logical_not()  # default implementation

    def _op2_less_or_equal(self, right: 'Any') -> 'Boolean': raise OperatorNotImplementedError

    def _op2_greater_or_equal(self, right: 'Any') -> 'Boolean': raise OperatorNotImplementedError

    def _op2_less(self, right: 'Any') -> 'Boolean': raise OperatorNotImplementedError

    def _op2_greater(self, right: 'Any') -> 'Boolean': raise OperatorNotImplementedError

    def _op2_bitwise_or(self, right: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_bitwise_xor(self, right: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_bitwise_and(self, right: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_add(self, right: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_add_swapped(self, left: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_subtract(self, right: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_subtract_swapped(self, left: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_multiply(self, right: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_multiply_swapped(self, left: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_floor_divide(self, right: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_floor_divide_swapped(self, left: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_divide(self, right: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_divide_swapped(self, left: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_modulo(self, right: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_modulo_swapped(self, left: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_power(self, right: 'Any') -> 'Any': raise OperatorNotImplementedError

    def _op2_power_swapped(self, left: 'Any') -> 'Any': raise OperatorNotImplementedError


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

    def _op1_logical_not(self) -> 'Boolean':
        return Boolean(not self._value)

    def _op2_logical_and(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Boolean):
            return Boolean(self._value and right._value)
        else:
            raise OperatorNotImplementedError

    def _op2_logical_or(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Boolean):
            return Boolean(self._value or right._value)
        else:
            raise OperatorNotImplementedError

    def _op2_equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Boolean):
            return Boolean(self._value == right._value)
        else:
            raise OperatorNotImplementedError


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
    def _op1_positive(self) -> 'Rational':
        return Rational(+self._value)

    def _op1_negative(self) -> 'Rational':
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
            raise OperatorNotImplementedError

    def _op2_equal(self, right: 'Any') -> 'Boolean':
        return self._op2_generic_compare(right, operator.eq)

    def _op2_less_or_equal(self, right: 'Any') -> 'Boolean':
        return self._op2_generic_compare(right, operator.le)

    def _op2_greater_or_equal(self, right: 'Any') -> 'Boolean':
        return self._op2_generic_compare(right, operator.ge)

    def _op2_less(self, right: 'Any') -> 'Boolean':
        return self._op2_generic_compare(right, operator.lt)

    def _op2_greater(self, right: 'Any') -> 'Boolean':
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
            raise OperatorNotImplementedError

    def _op2_bitwise_or(self, right: 'Any') -> 'Rational':
        return self._op2_generic_bitwise(right, operator.or_)

    def _op2_bitwise_xor(self, right: 'Any') -> 'Rational':
        return self._op2_generic_bitwise(right, operator.xor)

    def _op2_bitwise_and(self, right: 'Any') -> 'Rational':
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
            raise OperatorNotImplementedError

    def _op2_add(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.add)

    def _op2_subtract(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.sub)

    def _op2_multiply(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.mul)

    def _op2_floor_divide(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.floordiv)

    def _op2_divide(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.truediv)

    def _op2_modulo(self, right: 'Any') -> 'Rational':
        return self._op2_generic_arithmetic(right, operator.mod)

    def _op2_power(self, right: 'Any') -> 'Rational':
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

    def _op2_add(self, right: 'Any') -> 'String':
        if isinstance(right, String):
            return String(self._value + right._value)
        else:
            raise OperatorNotImplementedError

    def _op2_equal(self, right: 'Any') -> Boolean:
        if isinstance(right, String):
            return Boolean(self._value == right._value)
        else:
            raise OperatorNotImplementedError


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
            raise InvalidOperandError('Zero-length sets are currently not permitted because '
                                      'of associated type deduction issues. This may change later.')

        element_types = set(map(type, list_of_elements))
        if len(element_types) != 1:
            # This also weeds out covariant sets, although our barbie-size type system is unaware of that.
            raise InvalidOperandError('Heterogeneous sets are not permitted')

        self._element_type = list(element_types)[0]  # type: typing.Type[Any]
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
    def _op2_equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_equal_to(right))
        else:
            raise OperatorNotImplementedError

    def _op2_less_or_equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_subset_of(right))
        else:
            raise OperatorNotImplementedError

    def _op2_greater_or_equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_superset_of(right))
        else:
            raise OperatorNotImplementedError

    def _op2_less(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_proper_subset_of(right))
        else:
            raise OperatorNotImplementedError

    def _op2_greater(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_proper_superset_of(right))
        else:
            raise OperatorNotImplementedError

    #
    # Set algebra operators that yield a new set.
    #
    def _op2_bitwise_or(self, right: 'Any') -> 'Set':
        if isinstance(right, Set):
            return self._create_union_with(right)
        else:
            raise OperatorNotImplementedError

    def _op2_bitwise_xor(self, right: 'Any') -> 'Set':
        if isinstance(right, Set):
            return self._create_disjunctive_union_with(right)
        else:
            raise OperatorNotImplementedError

    def _op2_bitwise_and(self, right: 'Any') -> 'Set':
        if isinstance(right, Set):
            return self._create_intersection_with(right)
        else:
            raise OperatorNotImplementedError

    #
    # Elementwise application.
    # https://stackoverflow.com/questions/55148139/referring-to-a-pure-virtual-method
    #
    def _op2_elementwise(self,
                         impl: typing.Callable[['Any', 'Any'], 'Any'],
                         other: 'Any',
                         swap: bool = False) -> 'Set':
        if isinstance(other, Primitive):
            return Set((impl(other, x) if swap else impl(x, other)) for x in self)
        else:
            raise OperatorNotImplementedError

    def _op2_add(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_add, right)

    def _op2_add_swapped(self, left: 'Any') -> 'Set':
        return self._op2_elementwise(op2_add, left, swap=True)

    def _op2_subtract(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_subtract, right)

    def _op2_subtract_swapped(self, left: 'Any') -> 'Set':
        return self._op2_elementwise(op2_subtract, left, swap=True)

    def _op2_multiply(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_multiply, right)

    def _op2_multiply_swapped(self, left: 'Any') -> 'Set':
        return self._op2_elementwise(op2_multiply, left, swap=True)

    def _op2_floor_divide(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_floor_divide, right)

    def _op2_floor_divide_swapped(self, left: 'Any') -> 'Set':
        return self._op2_elementwise(op2_floor_divide, left, swap=True)

    def _op2_divide(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_divide, right)

    def _op2_divide_swapped(self, left: 'Any') -> 'Set':
        return self._op2_elementwise(op2_divide, left, swap=True)

    def _op2_modulo(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_modulo, right)

    def _op2_modulo_swapped(self, left: 'Any') -> 'Set':
        return self._op2_elementwise(op2_modulo, left, swap=True)

    def _op2_power(self, right: 'Any') -> 'Set':
        return self._op2_elementwise(op2_power, right)

    def _op2_power_swapped(self, left: 'Any') -> 'Set':
        return self._op2_elementwise(op2_power, left, swap=True)


def _enforce_initializer_type(value: typing.Any, expected_type: _TypeList) -> None:
    if not isinstance(value, expected_type):
        raise ValueError('Expected type %r, found %r' % (expected_type, type(value)))


# noinspection PyUnresolvedReferences,PyTypeChecker
def _unittest_expressions() -> None:
    r = Rational
    s = String

    for a in (True, False):
        for b in (True, False):
            assert Boolean(a).native_value == a
            assert op1_logical_not(Boolean(a)).native_value == (not a)
            assert op2_logical_and(Boolean(a), Boolean(b)).native_value == (a and b)
            assert op2_logical_or(Boolean(a), Boolean(b)).native_value == (a or b)

    assert \
        op2_equal(
            op2_divide(
                op2_multiply(
                    op2_add(r(2), r(2)),
                    r(3)
                ),
                r(5)
            ),
            r(Fraction(12, 5))
        ).native_value

    assert op2_add(s('123'), s('abc')).native_value == '123abc'  # type: ignore

    new_set = op2_add(Set([s('123'), s('456')]),
                      s('abc'))
    assert set(new_set) == {s('123abc'), s('456abc')}  # type: ignore

    new_set = op2_add(s('abc'),
                      Set([s('123'), s('456')]))
    assert set(new_set) == {s('abc123'), s('abc456')}  # type: ignore

    new_set = op2_add(s('abc'),
                      Set([Set([s('123'), s('456')]),
                           Set([s('789'), s('987')])]))
    assert new_set == Set([Set([s('abc123'), s('abc456')]),
                           Set([s('abc789'), s('abc987')])])
