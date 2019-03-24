#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import operator
import functools
import fractions
from . import error


OperatorOutput    = typing.TypeVar('OperatorOutput')
UnaryOperator     = typing.Callable[['Any'], OperatorOutput]
BinaryOperator    = typing.Callable[['Any', 'Any'], OperatorOutput]
AttributeOperator = typing.Callable[['Any', typing.Union['String', str]], OperatorOutput]


class InvalidOperandError(error.InvalidDefinitionError):
    pass


class UndefinedOperatorError(InvalidOperandError):
    """Thrown when there is no matching operator for the supplied arguments."""
    def __init__(self) -> None:
        super(UndefinedOperatorError, self).__init__('The requested operator is not defined for the provided arguments')


class UndefinedAttributeError(InvalidOperandError):
    """Thrown when the requested attribute does not exist."""
    def __init__(self) -> None:
        super(UndefinedAttributeError, self).__init__('Invalid attribute name')


class Any:
    """
    This abstract class represents an arbitrary intrinsic DSDL expression value.
    """
    # This attribute must be specified in the derived classes.
    # It contains the name of the data type implemented by the class.
    TYPE_NAME = None    # type: str

    def __hash__(self) -> int:
        raise NotImplementedError  # pragma: no cover

    def __eq__(self, other: object) -> bool:
        raise NotImplementedError  # pragma: no cover

    def __str__(self) -> str:
        """Must return a DSDL spec-compatible textual representation of the contained value suitable for printing."""
        raise NotImplementedError  # pragma: no cover

    def __repr__(self) -> str:
        return self.TYPE_NAME + '(' + str(self) + ')'

    #
    # Unary operators.
    #
    def _logical_not(self) -> 'Boolean': raise UndefinedOperatorError

    def _positive(self) -> 'Any': raise UndefinedOperatorError

    def _negative(self) -> 'Any': raise UndefinedOperatorError

    #
    # Binary operators.
    # The types of the operators defined here must match the specification.
    # Make sure to use least generic types in the derived classes - Python allows covariant return types.
    #
    def _logical_or(self, right: 'Any')  -> 'Boolean': raise UndefinedOperatorError
    def _logical_and(self, right: 'Any') -> 'Boolean': raise UndefinedOperatorError

    def _equal(self, right: 'Any')            -> 'Boolean': raise UndefinedOperatorError  # pragma: no branch
    def _less_or_equal(self, right: 'Any')    -> 'Boolean': raise UndefinedOperatorError
    def _greater_or_equal(self, right: 'Any') -> 'Boolean': raise UndefinedOperatorError
    def _less(self, right: 'Any')             -> 'Boolean': raise UndefinedOperatorError
    def _greater(self, right: 'Any')          -> 'Boolean': raise UndefinedOperatorError

    def _bitwise_or(self, right: 'Any')      -> 'Any': raise UndefinedOperatorError
    def _bitwise_or_right(self, left: 'Any') -> 'Any': raise UndefinedOperatorError

    def _bitwise_xor(self, right: 'Any')      -> 'Any': raise UndefinedOperatorError
    def _bitwise_xor_right(self, left: 'Any') -> 'Any': raise UndefinedOperatorError

    def _bitwise_and(self, right: 'Any')      -> 'Any': raise UndefinedOperatorError
    def _bitwise_and_right(self, left: 'Any') -> 'Any': raise UndefinedOperatorError

    def _add(self, right: 'Any')      -> 'Any': raise UndefinedOperatorError
    def _add_right(self, left: 'Any') -> 'Any': raise UndefinedOperatorError

    def _subtract(self, right: 'Any')      -> 'Any': raise UndefinedOperatorError
    def _subtract_right(self, left: 'Any') -> 'Any': raise UndefinedOperatorError

    def _multiply(self, right: 'Any')      -> 'Any': raise UndefinedOperatorError
    def _multiply_right(self, left: 'Any') -> 'Any': raise UndefinedOperatorError

    def _divide(self, right: 'Any')      -> 'Any': raise UndefinedOperatorError
    def _divide_right(self, left: 'Any') -> 'Any': raise UndefinedOperatorError

    def _modulo(self, right: 'Any')      -> 'Any': raise UndefinedOperatorError
    def _modulo_right(self, left: 'Any') -> 'Any': raise UndefinedOperatorError

    def _power(self, right: 'Any')      -> 'Any': raise UndefinedOperatorError
    def _power_right(self, left: 'Any') -> 'Any': raise UndefinedOperatorError

    #
    # Attribute access operator. It is a binary operator as well, but its semantics is slightly different.
    # Implementations must invoke super()._attribute() when they encounter an unknown attribute, to allow
    # the parent classes to handle the requested attribute as a fallback option.
    #
    def _attribute(self, name: 'String') -> 'Any': raise UndefinedAttributeError


# noinspection PyAbstractClass
class Primitive(Any):
    @property
    def native_value(self) -> typing.Any:
        raise NotImplementedError  # pragma: no cover


class Boolean(Primitive):
    TYPE_NAME = 'bool'

    def __init__(self, value: bool = False):
        if not isinstance(value, bool):
            raise ValueError('Cannot construct a Boolean instance from ' + type(value).__name__)

        self._value = value  # type: bool

    @property
    def native_value(self) -> bool:
        return self._value

    def __hash__(self) -> int:
        return int(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Boolean):
            return self._value == other._value
        else:  # pragma: no cover
            return NotImplemented

    def __str__(self) -> str:
        return 'true' if self._value else 'false'

    def __bool__(self) -> bool:     # For use in expressions without accessing "native_value"
        return self._value

    def _logical_not(self) -> 'Boolean':
        return Boolean(not self._value)

    def _logical_and(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Boolean):
            return Boolean(self._value and right._value)
        else:
            raise UndefinedOperatorError

    def _logical_or(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Boolean):
            return Boolean(self._value or right._value)
        else:
            raise UndefinedOperatorError

    def _equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Boolean):
            return Boolean(self._value == right._value)
        else:
            raise UndefinedOperatorError


class Rational(Primitive):
    TYPE_NAME = 'rational'

    def __init__(self, value: typing.Union[int, fractions.Fraction]):
        # We must support float as well, because some operators on Fraction sometimes yield float, e.g. power.
        if not isinstance(value, (int, float, fractions.Fraction)):
            raise ValueError('Cannot construct a Rational instance from ' + type(value).__name__)
        self._value = fractions.Fraction(value)  # type: fractions.Fraction

    @property
    def native_value(self) -> fractions.Fraction:
        return self._value

    def as_native_integer(self) -> int:
        """
        Returns the inferior as a native integer,
        unless it cannot be represented as such without the loss of precision; i.e., if denominator != 1.
        """
        if self.is_integer():
            return self._value.numerator
        else:
            raise InvalidOperandError('Rational %s is not an integer' % self._value)

    def is_integer(self) -> bool:
        return self._value.denominator == 1

    def __hash__(self) -> int:
        return hash(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Rational):
            return self._value == other._value
        else:  # pragma: no cover
            return NotImplemented

    def __str__(self) -> str:
        return str(self._value)

    #
    # Unary operators.
    #
    def _positive(self) -> 'Rational':
        return Rational(+self._value)

    def _negative(self) -> 'Rational':
        return Rational(-self._value)

    #
    # Binary comparison operators.
    #
    def _generic_compare(self, right: 'Any', impl: typing.Callable[[typing.Any, typing.Any], bool]) -> Boolean:
        if isinstance(right, Rational):
            return Boolean(impl(self._value, right._value))
        else:
            raise UndefinedOperatorError

    def _equal(self, right: 'Any') -> 'Boolean':
        return self._generic_compare(right, operator.eq)

    def _less_or_equal(self, right: 'Any') -> 'Boolean':
        return self._generic_compare(right, operator.le)

    def _greater_or_equal(self, right: 'Any') -> 'Boolean':
        return self._generic_compare(right, operator.ge)

    def _less(self, right: 'Any') -> 'Boolean':
        return self._generic_compare(right, operator.lt)

    def _greater(self, right: 'Any') -> 'Boolean':
        return self._generic_compare(right, operator.gt)

    #
    # Binary bitwise operators.
    #
    def _generic_bitwise(self, right: 'Any', impl: typing.Callable[[typing.Any, typing.Any], typing.Any]) -> 'Rational':
        if isinstance(right, Rational):
            return Rational(impl(self.as_native_integer(), right.as_native_integer()))    # Throws if not an integer.
        else:
            raise UndefinedOperatorError

    def _bitwise_or(self, right: 'Any') -> 'Rational':
        return self._generic_bitwise(right, operator.or_)

    def _bitwise_xor(self, right: 'Any') -> 'Rational':
        return self._generic_bitwise(right, operator.xor)

    def _bitwise_and(self, right: 'Any') -> 'Rational':
        return self._generic_bitwise(right, operator.and_)

    #
    # Binary arithmetic operators.
    #
    def _generic_arithmetic(self,
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
            raise UndefinedOperatorError

    def _add(self, right: 'Any') -> 'Rational':
        return self._generic_arithmetic(right, operator.add)

    def _subtract(self, right: 'Any') -> 'Rational':
        return self._generic_arithmetic(right, operator.sub)

    def _multiply(self, right: 'Any') -> 'Rational':
        return self._generic_arithmetic(right, operator.mul)

    def _divide(self, right: 'Any') -> 'Rational':
        return self._generic_arithmetic(right, operator.truediv)

    def _modulo(self, right: 'Any') -> 'Rational':
        return self._generic_arithmetic(right, operator.mod)

    def _power(self, right: 'Any') -> 'Rational':
        return self._generic_arithmetic(right, operator.pow)


class String(Primitive):
    TYPE_NAME = 'string'

    def __init__(self, value: str):
        if not isinstance(value, str):
            raise ValueError('Cannot construct a String instance from ' + type(value).__name__)
        self._value = value  # type: str

    @property
    def native_value(self) -> str:
        return self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, String):
            return self._value == other._value
        else:  # pragma: no cover
            return NotImplemented

    def __str__(self) -> str:
        return repr(self._value)

    def _add(self, right: 'Any') -> 'String':
        if isinstance(right, String):
            return String(self._value + right._value)
        else:
            raise UndefinedOperatorError

    def _equal(self, right: 'Any') -> Boolean:
        if isinstance(right, String):
            return Boolean(self._value == right._value)
        else:
            raise UndefinedOperatorError


# noinspection PyAbstractClass
class Container(Any):
    @property
    def element_type(self) -> typing.Type[Any]:
        raise NotImplementedError  # pragma: no cover

    def __iter__(self) -> typing.Iterator[typing.Any]:
        raise NotImplementedError  # pragma: no cover


class Set(Container):
    TYPE_NAME = 'set'

    # noinspection PyProtectedMember
    class _Decorator:
        @staticmethod
        def homotypic_binary_operator(inferior: typing.Callable[['Set', 'Set'], OperatorOutput]) \
                -> typing.Callable[['Set', 'Set'], OperatorOutput]:
            def wrapper(self: 'Set', other: 'Set') -> OperatorOutput:
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
            return NotImplemented

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
    def _equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_equal_to(right))
        else:
            raise UndefinedOperatorError

    def _less_or_equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_subset_of(right))
        else:
            raise UndefinedOperatorError

    def _greater_or_equal(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_superset_of(right))
        else:
            raise UndefinedOperatorError

    def _less(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_proper_subset_of(right))
        else:
            raise UndefinedOperatorError

    def _greater(self, right: 'Any') -> 'Boolean':
        if isinstance(right, Set):
            return Boolean(self._is_proper_superset_of(right))
        else:
            raise UndefinedOperatorError

    #
    # Set algebra operators that yield a new set.
    #
    def _bitwise_or(self, right: 'Any') -> 'Set':
        if isinstance(right, Set):
            return self._create_union_with(right)
        else:
            raise UndefinedOperatorError

    def _bitwise_xor(self, right: 'Any') -> 'Set':
        if isinstance(right, Set):
            return self._create_disjunctive_union_with(right)
        else:
            raise UndefinedOperatorError

    def _bitwise_and(self, right: 'Any') -> 'Set':
        if isinstance(right, Set):
            return self._create_intersection_with(right)
        else:
            raise UndefinedOperatorError

    #
    # Elementwise application.
    # https://stackoverflow.com/questions/55148139/referring-to-a-pure-virtual-method
    #
    def _elementwise(self,
                     impl: typing.Callable[['Any', 'Any'], 'Any'],
                     other: 'Any',
                     swap: bool = False) -> 'Set':
        if isinstance(other, Primitive):
            return Set((impl(other, x) if swap else impl(x, other)) for x in self)
        else:
            raise UndefinedOperatorError

    def _add(self, right: 'Any') -> 'Set':
        return self._elementwise(add, right)

    def _add_right(self, left: 'Any') -> 'Set':
        return self._elementwise(add, left, swap=True)

    def _subtract(self, right: 'Any') -> 'Set':
        return self._elementwise(subtract, right)

    def _subtract_right(self, left: 'Any') -> 'Set':
        return self._elementwise(subtract, left, swap=True)

    def _multiply(self, right: 'Any') -> 'Set':
        return self._elementwise(multiply, right)

    def _multiply_right(self, left: 'Any') -> 'Set':
        return self._elementwise(multiply, left, swap=True)

    def _divide(self, right: 'Any') -> 'Set':
        return self._elementwise(divide, right)

    def _divide_right(self, left: 'Any') -> 'Set':
        return self._elementwise(divide, left, swap=True)

    def _modulo(self, right: 'Any') -> 'Set':
        return self._elementwise(modulo, right)

    def _modulo_right(self, left: 'Any') -> 'Set':
        return self._elementwise(modulo, left, swap=True)

    def _power(self, right: 'Any') -> 'Set':
        return self._elementwise(power, right)

    def _power_right(self, left: 'Any') -> 'Set':
        return self._elementwise(power, left, swap=True)

    #
    # Attributes
    #
    def _attribute(self, name: 'String') -> 'Any':
        if name.native_value == 'min':
            out = functools.reduce(lambda a, b: a if less(a, b) else b, self)
            assert isinstance(out, self.element_type)
        elif name.native_value == 'max':
            out = functools.reduce(lambda a, b: a if greater(a, b) else b, self)
            assert isinstance(out, self.element_type)
        elif name.native_value == 'count':  # "size" and "length" can be ambiguous, "cardinality" is long
            out = Rational(len(self._value))
        else:
            out = super(Set, self)._attribute(name)  # Hand over up the inheritance chain, this is important

        assert isinstance(out, Any)
        return out


#
# Operator wrappers. These wrappers serve two purposes:
#   - Late binding, as explained here: https://stackoverflow.com/questions/55148139/referring-to-a-pure-virtual-method
#   - Automatic left-right operand swapping when necessary (for some polyadic operators).
#
def _auto_swap(alternative_operator_name: typing.Optional[str] = None) -> \
        typing.Callable[[BinaryOperator[OperatorOutput]], BinaryOperator[OperatorOutput]]:
    def decorator(direct_operator: BinaryOperator[OperatorOutput]) -> BinaryOperator[OperatorOutput]:
        if alternative_operator_name:
            alternative_method_name = '_' + alternative_operator_name
        else:
            alternative_method_name = '_%s_right' % direct_operator.__name__

        if not hasattr(Any, alternative_method_name):  # pragma: no cover
            raise TypeError('The following alternative operator method is not defined: %r' % alternative_method_name)

        @functools.wraps(direct_operator)
        def wrapper(left: Any, right: Any) -> Any:
            if not isinstance(left, Any) or not isinstance(right, Any):  # pragma: no cover
                raise ValueError('Operators are only defined for implementations of Any; found this: %r, %r' %
                                 (type(left).__name__, type(right).__name__))
            try:
                result = direct_operator(left, right)
            except UndefinedOperatorError:
                if type(left) != type(right):
                    result = getattr(right, alternative_method_name)(left)  # Left and Right are swapped.
                else:
                    raise

            assert isinstance(result, Any)
            return result
        return wrapper
    return decorator


def logical_not(operand: Any) -> Boolean:                       # noinspection PyProtectedMember
    return operand._logical_not()


def positive(operand: Any) -> Any:                              # noinspection PyProtectedMember
    return operand._positive()


def negative(operand: Any) -> Any:                              # noinspection PyProtectedMember
    return operand._negative()


@_auto_swap('logical_or')  # Commutative
def logical_or(left: Any, right: Any) -> Boolean:               # noinspection PyProtectedMember
    return left._logical_or(right)


@_auto_swap('logical_and')  # Commutative
def logical_and(left: Any, right: Any) -> Boolean:              # noinspection PyProtectedMember
    return left._logical_and(right)


@_auto_swap('equal')  # Commutative
def equal(left: Any, right: Any) -> Boolean:                    # noinspection PyProtectedMember
    return left._equal(right)


# Special case - synthetic operator.
def not_equal(left: Any, right: Any) -> Boolean:                # noinspection PyProtectedMember
    return logical_not(equal(left, right))


@_auto_swap('greater_or_equal')
def less_or_equal(left: Any, right: Any) -> Boolean:            # noinspection PyProtectedMember
    return left._less_or_equal(right)


@_auto_swap('less_or_equal')
def greater_or_equal(left: Any, right: Any) -> Boolean:         # noinspection PyProtectedMember
    return left._greater_or_equal(right)


@_auto_swap('greater')
def less(left: Any, right: Any) -> Boolean:                     # noinspection PyProtectedMember
    return left._less(right)


@_auto_swap('less')
def greater(left: Any, right: Any) -> Boolean:                  # noinspection PyProtectedMember
    return left._greater(right)


@_auto_swap()
def bitwise_or(left: Any, right: Any) -> Any:                   # noinspection PyProtectedMember
    return left._bitwise_or(right)


@_auto_swap()
def bitwise_xor(left: Any, right: Any) -> Any:                  # noinspection PyProtectedMember
    return left._bitwise_xor(right)


@_auto_swap()
def bitwise_and(left: Any, right: Any) -> Any:                  # noinspection PyProtectedMember
    return left._bitwise_and(right)


@_auto_swap()
def add(left: Any, right: Any) -> Any:                          # noinspection PyProtectedMember
    return left._add(right)


@_auto_swap()
def subtract(left: Any, right: Any) -> Any:                     # noinspection PyProtectedMember
    return left._subtract(right)


@_auto_swap()
def multiply(left: Any, right: Any) -> Any:                     # noinspection PyProtectedMember
    return left._multiply(right)


@_auto_swap()
def divide(left: Any, right: Any) -> Any:                       # noinspection PyProtectedMember
    return left._divide(right)


@_auto_swap()
def modulo(left: Any, right: Any) -> Any:                       # noinspection PyProtectedMember
    return left._modulo(right)


@_auto_swap()
def power(left: Any, right: Any) -> Any:                        # noinspection PyProtectedMember
    return left._power(right)


# Special case - no argument-swapped alternative defined.
# We accept both native strings and String in order to support both dynamically computed attributes and
# statically defined attributes.
def attribute(value: Any, name: typing.Union[str, String]) -> Any:
    if isinstance(name, str):
        name = String(name)

    if isinstance(value, Any) and isinstance(name, String):     # noinspection PyProtectedMember
        return value._attribute(name)
    else:  # pragma: no cover
        raise ValueError('The argument types of the attribute operator are (Any, String), got (%r, %r)' %
                         (type(value).__name__, type(name).__name__))


# noinspection PyUnresolvedReferences,PyTypeChecker
def _unittest_expressions() -> None:
    r = Rational
    s = String

    for a in (True, False):
        for b in (True, False):
            assert Boolean(a).native_value == a
            assert logical_not(Boolean(a)).native_value == (not a)
            assert logical_and(Boolean(a), Boolean(b)).native_value == (a and b)
            assert logical_or(Boolean(a), Boolean(b)).native_value == (a or b)

    assert \
        equal(
            divide(
                multiply(
                    add(r(2), r(2)),
                    r(3)
                ),
                r(5)
            ),
            r(fractions.Fraction(12, 5))
        ).native_value

    assert add(s('123'), s('abc')).native_value == '123abc'  # type: ignore

    new_set = add(Set([s('123'), s('456')]),
                  s('abc'))
    assert set(new_set) == {s('123abc'), s('456abc')}  # type: ignore

    new_set = add(s('abc'),
                  Set([s('123'), s('456')]))
    assert set(new_set) == {s('abc123'), s('abc456')}  # type: ignore

    new_set = add(s('abc'),
                  Set([Set([s('123'), s('456')]),
                       Set([s('789'), s('987')])]))
    assert new_set == Set([Set([s('abc123'), s('abc456')]),
                           Set([s('abc789'), s('abc987')])])

    assert attribute(Set([r(1), r(2), r(3), r(-4), r(-5)]), s('min')) == r(-5)
    assert attribute(Set([r(1), r(2), r(3), r(-4), r(-5)]), s('max')) == r(3)


def _unittest_textual_representations() -> None:
    assert str(Rational(fractions.Fraction(123, 456))) == '41/152'
    assert repr(Rational(fractions.Fraction(123, 456))) == 'rational(41/152)'
    assert str(Rational(-123)) == '-123'
    assert repr(Rational(-123)) == 'rational(-123)'

    assert str(Boolean(True)) == 'true'
    assert repr(Boolean(False)) == 'bool(false)'

    assert str(String('Hello\nworld!')) == r"'Hello\nworld!'"
    assert repr(String('Hello\nworld!')) == r"string('Hello\nworld!')"

    tmp = str(Set([Rational(1), Rational(fractions.Fraction(-9, 7))]))
    assert tmp == '{1, -9/7}' or tmp == '{-9/7, 1}'

    tmp = repr(Set([Rational(1), Rational(fractions.Fraction(-9, 7))]))
    assert tmp == 'set({1, -9/7})' or tmp == 'set({-9/7, 1})'

    tmp = str(Set([Set([Rational(1), Rational(fractions.Fraction(-9, 7))]),
                   Set([Rational(fractions.Fraction(90, 7))])]))
    assert \
        tmp == '{{1, -9/7}, {90/7}}' or \
        tmp == '{{-9/7, 1}, {90/7}}' or \
        tmp == '{{90/7}, {-9/7, 1}}' or \
        tmp == '{{90/7}, {1, -9/7}}'

    assert repr(Set([String('123')])) == "set({'123'})"


# noinspection PyTypeChecker
def _unittest_basic() -> None:
    from pytest import raises

    assert hash(Boolean(True)) == hash(True)
    assert Boolean(True) == Boolean(True)
    assert Boolean(True) != Boolean(False)
    assert Boolean(True) != Rational(1)         # sic!
    assert Boolean(True) != Rational(123)
    assert Boolean(True) != Set([Boolean(True)])

    with raises(ValueError):
        Boolean(int)       # type: ignore

    with raises(ValueError):
        Rational({123})    # type: ignore

    with raises(ValueError):
        Rational('123')    # type: ignore

    with raises(ValueError):
        String(123)       # type: ignore

    with raises(ValueError):
        Set([123])        # type: ignore

    assert Rational(123).is_integer()
    assert not Rational(fractions.Fraction(123, 124)).is_integer()
    assert Rational(-123).as_native_integer() == -123
    with raises(InvalidOperandError):
        Rational(fractions.Fraction(123, 124)).as_native_integer()
