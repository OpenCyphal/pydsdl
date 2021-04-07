# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import abc
from .. import _expression
from .. import _error
from .._bit_length_set import BitLengthSet


class TypeParameterError(_error.InvalidDefinitionError):
    pass


class SerializableType(_expression.Any):
    """
    Instances are immutable.
    Invoking :meth:`__str__` on a data type returns its uniform normalized definition, e.g.,
    ``uavcan.node.Heartbeat.1.0[<=36]``, ``truncated float16[<=36]``.
    """

    TYPE_NAME = "metaserializable"

    BITS_PER_BYTE = 8
    """
    This is dictated by the UAVCAN Specification.
    """

    def __init__(self) -> None:
        super().__init__()

    @property
    @abc.abstractmethod
    def bit_length_set(self) -> BitLengthSet:
        """
        A set of all possible bit length values of the serialized representations of this type.
        Refer to the specification for the background. The returned set is guaranteed to be non-empty.
        See :class:`pydsdl.BitLengthSet`.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def alignment_requirement(self) -> int:
        """
        Serialized representations of this type are required/guaranteed to be aligned such that their offset
        from the beginning of the containing serialized representation, in bits, is a multiple of this value, in bits.
        Alignment of a type whose alignment requirement is X bits is facilitated by injecting ``[0, X)`` zero
        padding bits before the serialized representation of the type.

        For any element ``L`` of the bit length set of a type whose alignment requirement is ``A``, ``L % A = 0``.
        I.e., the length of a serialized representation of the type is always a multiple of its alignment requirement.

        This value is always a non-negative integer power of two. The alignment of one is a degenerate case denoting
        no alignment.
        """
        raise NotImplementedError

    def _attribute(self, name: _expression.String) -> _expression.Any:
        if name.native_value == "_bit_length_":  # Experimental non-standard extension
            try:
                return _expression.Set(map(_expression.Rational, self.bit_length_set))
            except TypeError:
                pass

        return super()._attribute(name)  # Hand over up the inheritance chain, important

    @abc.abstractmethod
    def __str__(self) -> str:  # pragma: no cover
        # Implementations must return a DSDL spec-compatible textual representation of the type.
        # The string representation is used for determining equivalency by the comparison operator __eq__().
        raise NotImplementedError

    def __hash__(self) -> int:
        try:
            bls = self.bit_length_set
        except TypeError:  # If the type is non-serializable.
            bls = BitLengthSet(0)
        return hash((str(self), bls))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SerializableType):
            same_type = isinstance(other, type(self)) and isinstance(self, type(other))
            try:  # Ensure equality of the bit length sets, otherwise, different types like voids may compare equal.
                same_bls = self.bit_length_set == other.bit_length_set
            except TypeError:  # If the type is non-serializable, assume equality.
                same_bls = same_type
            return same_type and same_bls and str(self) == str(other)
        return NotImplemented
