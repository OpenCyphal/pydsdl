# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

# pylint: disable=protected-access

import abc
import typing
import functools
from . import _any, _primitive, _operator


_O = typing.TypeVar("_O")


# noinspection PyAbstractClass
class Container(_any.Any):
    @property
    @abc.abstractmethod
    def element_type(self) -> typing.Type[_any.Any]:
        raise NotImplementedError  # pragma: no cover

    @abc.abstractmethod
    def __iter__(self) -> typing.Iterator[typing.Any]:
        raise NotImplementedError  # pragma: no cover


class Set(Container):
    TYPE_NAME = "set"

    # noinspection PyProtectedMember
    class _Decorator:
        @staticmethod
        def homotypic_binary_operator(
            inferior: typing.Callable[["Set", "Set"], _O]
        ) -> typing.Callable[["Set", "Set"], _O]:
            def wrapper(self: "Set", other: "Set") -> _O:
                assert isinstance(self, Set) and isinstance(other, Set)
                if self.element_type == other.element_type:
                    return inferior(self, other)
                raise _any.InvalidOperandError(
                    "The requested binary operator is defined only for sets "
                    "that share the same element type. The different types are: %r, %r"
                    % (self.element_type.TYPE_NAME, other.element_type.TYPE_NAME)
                )

            return wrapper

    def __init__(self, elements: typing.Iterable[_any.Any]):
        list_of_elements = list(elements)  # type: typing.List[_any.Any]
        del elements
        if len(list_of_elements) < 1:
            raise _any.InvalidOperandError(
                "Zero-length sets are currently not permitted because "
                "of associated type deduction issues. This may change later."
            )

        element_types = set(map(type, list_of_elements))
        if len(element_types) != 1:
            # This also weeds out covariant sets, although our barbie-size type system is unaware of that.
            raise _any.InvalidOperandError("Heterogeneous sets are not permitted")

        # noinspection PyTypeChecker
        self._element_type = list(element_types)[0]  # type: typing.Type[_any.Any]
        self._value = frozenset(list_of_elements)  # type: typing.FrozenSet[_any.Any]

        if not issubclass(self._element_type, _any.Any):
            raise ValueError("Invalid element type: %r" % self._element_type)

    def __iter__(self) -> typing.Iterator[typing.Any]:
        return iter(self._value)

    @property
    def element_type(self) -> typing.Type[_any.Any]:
        return self._element_type

    def __hash__(self) -> int:
        return hash(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Set):
            return self._value == other._value
        return NotImplemented

    def __str__(self) -> str:
        return "{%s}" % ", ".join(map(str, self._value))  # This is recursive.

    #
    # Set algebra implementation.
    #
    @_Decorator.homotypic_binary_operator
    def _is_equal_to(self, right: "Set") -> bool:
        return self._value == right._value

    @_Decorator.homotypic_binary_operator
    def _is_superset_of(self, right: "Set") -> bool:
        return self._value.issuperset(right._value)

    @_Decorator.homotypic_binary_operator
    def _is_subset_of(self, right: "Set") -> bool:
        return self._value.issubset(right._value)

    @_Decorator.homotypic_binary_operator
    def _is_proper_superset_of(self, right: "Set") -> bool:
        return self._is_superset_of(right) and not self._is_equal_to(right)

    @_Decorator.homotypic_binary_operator
    def _is_proper_subset_of(self, right: "Set") -> bool:
        return self._is_subset_of(right) and not self._is_equal_to(right)

    @_Decorator.homotypic_binary_operator
    def _create_union_with(self, right: "Set") -> "Set":
        return Set(self._value.union(right._value))

    @_Decorator.homotypic_binary_operator
    def _create_intersection_with(self, right: "Set") -> "Set":
        return Set(self._value.intersection(right._value))

    @_Decorator.homotypic_binary_operator
    def _create_disjunctive_union_with(self, right: "Set") -> "Set":
        return Set(self._value.symmetric_difference(right._value))

    #
    # Set comparison.
    #
    def _equal(self, right: _any.Any) -> _primitive.Boolean:
        if isinstance(right, Set):
            return _primitive.Boolean(self._is_equal_to(right))
        raise _any.UndefinedOperatorError

    def _less_or_equal(self, right: _any.Any) -> _primitive.Boolean:
        if isinstance(right, Set):
            return _primitive.Boolean(self._is_subset_of(right))
        raise _any.UndefinedOperatorError

    def _greater_or_equal(self, right: _any.Any) -> _primitive.Boolean:
        if isinstance(right, Set):
            return _primitive.Boolean(self._is_superset_of(right))
        raise _any.UndefinedOperatorError

    def _less(self, right: _any.Any) -> _primitive.Boolean:
        if isinstance(right, Set):
            return _primitive.Boolean(self._is_proper_subset_of(right))
        raise _any.UndefinedOperatorError

    def _greater(self, right: _any.Any) -> _primitive.Boolean:
        if isinstance(right, Set):
            return _primitive.Boolean(self._is_proper_superset_of(right))
        raise _any.UndefinedOperatorError

    #
    # Set algebra operators that yield a new set.
    #
    def _bitwise_or(self, right: _any.Any) -> "Set":
        if isinstance(right, Set):
            return self._create_union_with(right)
        raise _any.UndefinedOperatorError

    def _bitwise_xor(self, right: _any.Any) -> "Set":
        if isinstance(right, Set):
            return self._create_disjunctive_union_with(right)
        raise _any.UndefinedOperatorError

    def _bitwise_and(self, right: _any.Any) -> "Set":
        if isinstance(right, Set):
            return self._create_intersection_with(right)
        raise _any.UndefinedOperatorError

    #
    # Elementwise application.
    # https://stackoverflow.com/questions/55148139/referring-to-a-pure-virtual-method
    #
    def _elementwise(
        self, impl: typing.Callable[[_any.Any, _any.Any], _any.Any], other: _any.Any, swap: bool = False
    ) -> "Set":
        if not isinstance(other, Set):
            return Set((impl(other, x) if swap else impl(x, other)) for x in self)
        raise _any.UndefinedOperatorError

    def _add(self, right: _any.Any) -> "Set":
        return self._elementwise(_operator.add, right)

    def _add_right(self, left: _any.Any) -> "Set":
        return self._elementwise(_operator.add, left, swap=True)

    def _subtract(self, right: _any.Any) -> "Set":
        return self._elementwise(_operator.subtract, right)

    def _subtract_right(self, left: _any.Any) -> "Set":
        return self._elementwise(_operator.subtract, left, swap=True)

    def _multiply(self, right: _any.Any) -> "Set":
        return self._elementwise(_operator.multiply, right)

    def _multiply_right(self, left: _any.Any) -> "Set":
        return self._elementwise(_operator.multiply, left, swap=True)

    def _divide(self, right: _any.Any) -> "Set":
        return self._elementwise(_operator.divide, right)

    def _divide_right(self, left: _any.Any) -> "Set":
        return self._elementwise(_operator.divide, left, swap=True)

    def _modulo(self, right: _any.Any) -> "Set":
        return self._elementwise(_operator.modulo, right)

    def _modulo_right(self, left: _any.Any) -> "Set":
        return self._elementwise(_operator.modulo, left, swap=True)

    def _power(self, right: _any.Any) -> "Set":
        return self._elementwise(_operator.power, right)

    def _power_right(self, left: _any.Any) -> "Set":
        return self._elementwise(_operator.power, left, swap=True)

    #
    # Attributes
    #
    def _attribute(self, name: "_primitive.String") -> _any.Any:
        if name.native_value == "min":
            out = functools.reduce(lambda a, b: a if _operator.less(a, b) else b, self)
            assert isinstance(out, self.element_type)
        elif name.native_value == "max":
            out = functools.reduce(lambda a, b: a if _operator.greater(a, b) else b, self)
            assert isinstance(out, self.element_type)
        elif name.native_value == "count":  # "size" and "length" can be ambiguous, "cardinality" is long
            out = _primitive.Rational(len(self._value))
        else:
            out = super()._attribute(name)  # Hand over up the inheritance chain, this is important

        assert isinstance(out, _any.Any)
        return out
