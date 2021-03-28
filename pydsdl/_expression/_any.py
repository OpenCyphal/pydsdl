# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import abc
from .. import _error


class InvalidOperandError(_error.InvalidDefinitionError):
    pass


class UndefinedOperatorError(InvalidOperandError):
    """Thrown when there is no matching operator for the supplied arguments."""

    def __init__(self) -> None:
        super().__init__("The requested operator is not defined for the provided arguments")


class UndefinedAttributeError(InvalidOperandError):
    """Thrown when the requested attribute does not exist."""

    def __init__(self) -> None:
        super().__init__("Invalid attribute name")


class Any(abc.ABC):
    """
    This abstract class represents an arbitrary intrinsic DSDL expression value.
    Both serializable types and expression types derive from this common ancestor.

    Per the DSDL data model, a serializable type is also a value.
    Serializable types have the suffix ``Type`` because their instances represent not DSDL values but DSDL types.

    Instances of this type can be pickled.
    """

    TYPE_NAME = None  # type: str
    """
    The DSDL-name of the data type implemented by the class, as defined in Specification.
    """

    @abc.abstractmethod
    def __hash__(self) -> int:
        raise NotImplementedError  # pragma: no cover

    @abc.abstractmethod
    def __eq__(self, other: object) -> bool:
        raise NotImplementedError  # pragma: no cover

    @abc.abstractmethod
    def __str__(self) -> str:
        """Returns a DSDL spec-compatible textual representation of the contained value suitable for printing."""
        raise NotImplementedError  # pragma: no cover

    def __repr__(self) -> str:
        return self.TYPE_NAME + "(" + str(self) + ")"

    # Unary operators.
    def _logical_not(self) -> "Boolean":
        raise UndefinedOperatorError

    def _positive(self) -> "Any":
        raise UndefinedOperatorError

    def _negative(self) -> "Any":
        raise UndefinedOperatorError

    # Binary operators.
    # The types of the operators defined here must match the specification.
    # Make sure to use least generic types in the derived classes - Python allows covariant return types.
    # fmt: off
    def _logical_or(self, right: 'Any')         -> 'Boolean': raise UndefinedOperatorError
    def _logical_and(self, right: 'Any')        -> 'Boolean': raise UndefinedOperatorError

    def _equal(self, right: 'Any')              -> 'Boolean': raise UndefinedOperatorError  # pragma: no branch
    def _less_or_equal(self, right: 'Any')      -> 'Boolean': raise UndefinedOperatorError
    def _greater_or_equal(self, right: 'Any')   -> 'Boolean': raise UndefinedOperatorError
    def _less(self, right: 'Any')               -> 'Boolean': raise UndefinedOperatorError
    def _greater(self, right: 'Any')            -> 'Boolean': raise UndefinedOperatorError

    def _bitwise_or(self, right: 'Any')         -> 'Any': raise UndefinedOperatorError
    def _bitwise_or_right(self, left: 'Any')    -> 'Any': raise UndefinedOperatorError

    def _bitwise_xor(self, right: 'Any')        -> 'Any': raise UndefinedOperatorError
    def _bitwise_xor_right(self, left: 'Any')   -> 'Any': raise UndefinedOperatorError

    def _bitwise_and(self, right: 'Any')        -> 'Any': raise UndefinedOperatorError
    def _bitwise_and_right(self, left: 'Any')   -> 'Any': raise UndefinedOperatorError

    def _add(self, right: 'Any')                -> 'Any': raise UndefinedOperatorError
    def _add_right(self, left: 'Any')           -> 'Any': raise UndefinedOperatorError

    def _subtract(self, right: 'Any')           -> 'Any': raise UndefinedOperatorError
    def _subtract_right(self, left: 'Any')      -> 'Any': raise UndefinedOperatorError

    def _multiply(self, right: 'Any')           -> 'Any': raise UndefinedOperatorError
    def _multiply_right(self, left: 'Any')      -> 'Any': raise UndefinedOperatorError

    def _divide(self, right: 'Any')             -> 'Any': raise UndefinedOperatorError
    def _divide_right(self, left: 'Any')        -> 'Any': raise UndefinedOperatorError

    def _modulo(self, right: 'Any')             -> 'Any': raise UndefinedOperatorError
    def _modulo_right(self, left: 'Any')        -> 'Any': raise UndefinedOperatorError

    def _power(self, right: 'Any')              -> 'Any': raise UndefinedOperatorError
    def _power_right(self, left: 'Any')         -> 'Any': raise UndefinedOperatorError
    # fmt: on

    # Attribute access operator. It is a binary operator as well, but its semantics is slightly different.
    # Implementations must invoke super()._attribute() when they encounter an unknown attribute, to allow
    # the parent classes to handle the requested attribute as a fallback option.
    def _attribute(self, name: "String") -> "Any":
        raise UndefinedAttributeError


# This import must be located at the bottom to break the circular dependency in the type annotations above.
# We must import specific names as opposed to the whole module because the latter breaks MyPy.
from ._primitive import Boolean, String  # pylint: disable=wrong-import-position,unused-import
