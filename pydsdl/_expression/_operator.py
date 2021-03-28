# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

# pylint: disable=protected-access

import typing
import functools
from . import _any, _primitive


OperatorOutput = typing.TypeVar("OperatorOutput")
BinaryOperator = typing.Callable[[_any.Any, _any.Any], OperatorOutput]
AttributeOperator = typing.Callable[[_any.Any, typing.Union[_primitive.String, str]], OperatorOutput]


#
# Operator wrappers. These wrappers serve two purposes:
#   - Late binding, as explained here: https://stackoverflow.com/questions/55148139/referring-to-a-pure-virtual-method
#   - Automatic left-right operand swapping when necessary (for some polyadic operators).
#
def _auto_swap(
    alternative_operator_name: typing.Optional[str] = None,
) -> typing.Callable[[BinaryOperator[OperatorOutput]], BinaryOperator[OperatorOutput]]:
    def decorator(direct_operator: BinaryOperator[OperatorOutput]) -> BinaryOperator[OperatorOutput]:
        if alternative_operator_name:
            alternative_method_name = "_" + alternative_operator_name
        else:
            alternative_method_name = "_%s_right" % direct_operator.__name__

        if not hasattr(_any.Any, alternative_method_name):  # pragma: no cover
            raise TypeError("The following alternative operator method is not defined: %r" % alternative_method_name)

        @functools.wraps(direct_operator)
        def wrapper(left: _any.Any, right: _any.Any) -> OperatorOutput:
            if not isinstance(left, _any.Any) or not isinstance(right, _any.Any):  # pragma: no cover
                raise ValueError(
                    "Operators are only defined for implementations of Any; found this: %r, %r"
                    % (type(left).__name__, type(right).__name__)
                )
            try:
                result = direct_operator(left, right)
            except _any.UndefinedOperatorError:
                if type(left) != type(right):  # pylint: disable=unidiomatic-typecheck
                    result = getattr(right, alternative_method_name)(left)  # Left and Right are swapped.
                else:
                    raise

            assert isinstance(result, _any.Any)
            return typing.cast(OperatorOutput, result)

        return wrapper

    return decorator


def logical_not(operand: _any.Any) -> _primitive.Boolean:  # noinspection PyProtectedMember
    result = operand._logical_not()
    assert isinstance(result, _primitive.Boolean)
    return result


def positive(operand: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return operand._positive()


def negative(operand: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return operand._negative()


@_auto_swap("logical_or")  # Commutative
def logical_or(left: _any.Any, right: _any.Any) -> _primitive.Boolean:  # noinspection PyProtectedMember
    result = left._logical_or(right)
    assert isinstance(result, _primitive.Boolean)
    return result


@_auto_swap("logical_and")  # Commutative
def logical_and(left: _any.Any, right: _any.Any) -> _primitive.Boolean:  # noinspection PyProtectedMember
    result = left._logical_and(right)
    assert isinstance(result, _primitive.Boolean)
    return result


@_auto_swap("equal")  # Commutative
def equal(left: _any.Any, right: _any.Any) -> _primitive.Boolean:  # noinspection PyProtectedMember
    result = left._equal(right)
    assert isinstance(result, _primitive.Boolean)
    return result


# Special case - synthetic operator.
def not_equal(left: _any.Any, right: _any.Any) -> _primitive.Boolean:  # noinspection PyProtectedMember
    result = logical_not(equal(left, right))
    assert isinstance(result, _primitive.Boolean)
    return result


@_auto_swap("greater_or_equal")
def less_or_equal(left: _any.Any, right: _any.Any) -> _primitive.Boolean:  # noinspection PyProtectedMember
    result = left._less_or_equal(right)
    assert isinstance(result, _primitive.Boolean)
    return result


@_auto_swap("less_or_equal")
def greater_or_equal(left: _any.Any, right: _any.Any) -> _primitive.Boolean:  # noinspection PyProtectedMember
    result = left._greater_or_equal(right)
    assert isinstance(result, _primitive.Boolean)
    return result


@_auto_swap("greater")
def less(left: _any.Any, right: _any.Any) -> _primitive.Boolean:  # noinspection PyProtectedMember
    result = left._less(right)
    assert isinstance(result, _primitive.Boolean)
    return result


@_auto_swap("less")
def greater(left: _any.Any, right: _any.Any) -> _primitive.Boolean:  # noinspection PyProtectedMember
    result = left._greater(right)
    assert isinstance(result, _primitive.Boolean)
    return result


@_auto_swap()
def bitwise_or(left: _any.Any, right: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return left._bitwise_or(right)


@_auto_swap()
def bitwise_xor(left: _any.Any, right: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return left._bitwise_xor(right)


@_auto_swap()
def bitwise_and(left: _any.Any, right: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return left._bitwise_and(right)


@_auto_swap()
def add(left: _any.Any, right: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return left._add(right)


@_auto_swap()
def subtract(left: _any.Any, right: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return left._subtract(right)


@_auto_swap()
def multiply(left: _any.Any, right: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return left._multiply(right)


@_auto_swap()
def divide(left: _any.Any, right: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return left._divide(right)


@_auto_swap()
def modulo(left: _any.Any, right: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return left._modulo(right)


@_auto_swap()
def power(left: _any.Any, right: _any.Any) -> _any.Any:  # noinspection PyProtectedMember
    return left._power(right)


# Special case - no argument-swapped alternative defined.
# We accept both native strings and String in order to support both dynamically computed attributes and
# statically defined attributes.
def attribute(value: _any.Any, name: typing.Union[str, _primitive.String]) -> _any.Any:
    if isinstance(name, str):
        name = _primitive.String(name)

    if isinstance(value, _any.Any) and isinstance(name, _primitive.String):  # noinspection PyProtectedMember
        return value._attribute(name)

    raise ValueError(  # pragma: no cover
        "The argument types of the attribute operator are (Any, String), got (%r, %r)"
        % (type(value).__name__, type(name).__name__)
    )
