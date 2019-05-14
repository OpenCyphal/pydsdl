#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import abc
import typing
from .. import _expression
from .. import _error
from .._bit_length_set import BitLengthSet


class TypeParameterError(_error.InvalidDefinitionError):
    pass


class SerializableType(_expression.Any):
    """
    Type objects are immutable. Immutability enables lazy evaluation of properties and hashability.
    Invoking __str__() on a data type returns its uniform normalized definition, e.g.:
        - uavcan.node.Heartbeat.1.0[<=36]
        - truncated float16[<=36]
    """

    TYPE_NAME = 'metaserializable'

    def __init__(self) -> None:
        super(SerializableType, self).__init__()
        self._cached_bit_length_set = None  # type: typing.Optional[BitLengthSet]

    @property
    def bit_length_set(self) -> BitLengthSet:
        """
        A set of all possible bit length values of serialized representations of the data type.
        Refer to the specification for the background. This method must never return an empty set.
        This is an expensive operation, so the result is cached in the base class. Derived classes should not
        override this property themselves; they must implement the method _compute_bit_length_set() instead.
        """
        if self._cached_bit_length_set is None:
            self._cached_bit_length_set = self._compute_bit_length_set()
        return self._cached_bit_length_set

    def _attribute(self, name: _expression.String) -> _expression.Any:
        if name.native_value == '_bit_length_':  # Experimental non-standard extension
            try:
                return _expression.Set(map(_expression.Rational, self.bit_length_set))
            except TypeError:
                pass

        return super(SerializableType, self)._attribute(name)  # Hand over up the inheritance chain, important

    @abc.abstractmethod
    def _compute_bit_length_set(self) -> BitLengthSet:
        """
        This is an expensive operation, so the result is cached in the base class. Derived classes should not
        override the bit_length_set property themselves; they must implement this method instead.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def __str__(self) -> str:   # pragma: no cover
        """
        Must return a DSDL spec-compatible textual representation of the type.
        The string representation is used for determining equivalency by the comparison operator __eq__().
        """
        raise NotImplementedError

    def __hash__(self) -> int:
        try:
            bls = self.bit_length_set
        except TypeError:   # If the type is non-serializable.
            bls = BitLengthSet()
        return hash(str(self) + str(bls))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SerializableType):
            same_type = isinstance(other, type(self)) and isinstance(self, type(other))
            try:    # Ensure equality of the bit length sets, otherwise, different types like voids may compare equal.
                same_bls = self.bit_length_set == other.bit_length_set
            except TypeError:   # If the type is non-serializable, assume equality.
                same_bls = same_type
            return same_type and same_bls and str(self) == str(other)
        else:
            return NotImplemented
