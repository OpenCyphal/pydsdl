# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import abc
import typing
import itertools


class Operator(abc.ABC):
    @abc.abstractmethod
    def is_aligned_at(self, bit_length: int) -> bool:
        """
        Whether all of the contained offset values match the specified alignment goal.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def min(self) -> int:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def max(self) -> int:
        raise NotImplementedError

    @abc.abstractmethod
    def expand(self) -> typing.Iterable[int]:
        """
        Transform the symbolic form into numerical form.
        For complex expressions this may be incomputable due to combinatorial explosion or memory limits.
        """
        raise NotImplementedError


class NullaryOperator(Operator):
    """
    A nullary operator represents a constant value, which is a leaf of the operator tree.
    """

    def __init__(self, values: typing.Iterable[int]) -> None:
        if isinstance(values, frozenset):
            self._value = values  # type: typing.FrozenSet[int]
        else:
            self._value = frozenset(values)
        self._value = self._value or frozenset({0})

    def is_aligned_at(self, bit_length: int) -> bool:
        return set(map(lambda x: x % bit_length, self._value)) == {0}

    @property
    def min(self) -> int:
        return min(self._value)

    @property
    def max(self) -> int:
        return max(self._value)

    def expand(self) -> typing.Iterable[int]:
        return self._value


class PaddingOperator(Operator):
    """
    Adds up to ``alignment - 1`` padding bits to each entry of the child to ensure that the values are aligned.
    """

    def __init__(self, child: Operator, alignment: int) -> None:
        if alignment < 1:
            raise ValueError("Invalid alignment: %r bits" % alignment)
        self._child = child
        self._padding = int(alignment)

    def is_aligned_at(self, bit_length: int) -> bool:
        if self._padding % bit_length == 0:
            return True
        return self._child.is_aligned_at(bit_length)

    @property
    def min(self) -> int:
        r = self._padding
        return ((self._child.min + r - 1) // r) * r

    @property
    def max(self) -> int:
        r = self._padding
        return ((self._child.max + r - 1) // r) * r

    def expand(self) -> typing.Iterable[int]:
        r = self._padding
        for x in self._child.expand():
            yield ((x + r - 1) // r) * r


class ConcatenationOperator(Operator):
    """
    Given a set of children, transforms them into a single bit length set expression where each item is the
    elementwise sum of the cartesian product of the children's bit length sets.
    """

    def __init__(self, children: typing.Iterable[Operator]) -> None:
        self._children = list(children)
        if not self._children:
            raise ValueError("This operator is not defined on zero operands")

    def is_aligned_at(self, bit_length: int) -> bool:
        # Trivial case: if all children are aligned, the result is also aligned.
        if all(x.is_aligned_at(bit_length) for x in self._children):
            return True
        # If all children are fixed-length, their sizes can be added to check alignment in constant time.
        mn, mx = self.min, self.max
        if mn == mx and mn % bit_length == 0:
            return True
        # Analytical solution is not possible, use brute-force check.
        for x in self.expand():
            if x % bit_length != 0:
                return False
        return True

    @property
    def min(self) -> int:
        return sum(x.min for x in self._children)

    @property
    def max(self) -> int:
        return sum(x.max for x in self._children)

    def expand(self) -> typing.Iterable[int]:
        for el in itertools.product(*(x.expand() for x in self._children)):
            yield sum(el)
