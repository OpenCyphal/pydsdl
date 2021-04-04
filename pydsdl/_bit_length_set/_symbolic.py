# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import abc
import math
import typing
import itertools


class Operator(abc.ABC):
    @abc.abstractmethod
    def modulo(self, bit_length: int) -> typing.Iterable[int]:
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
        This is useful for cross-checking derived solutions and for DSDL expression evaluation.
        For complex expressions this may be incomputable due to combinatorial explosion or memory limits.
        """
        raise NotImplementedError


class NullaryOperator(Operator):
    """
    A nullary operator represents a constant value, which is a leaf of the operator tree.
    """

    def __init__(self, values: typing.Iterable[int]) -> None:
        self._value = frozenset(values) or frozenset({0})

    def modulo(self, bit_length: int) -> typing.Iterable[int]:
        return set(map(lambda x: x % bit_length, self._value))

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
        if alignment < 1:  # pragma: no cover
            raise ValueError("Invalid alignment: %r bits" % alignment)
        self._child = child
        self._padding = int(alignment)

    def modulo(self, bit_length: int) -> typing.Iterable[int]:
        r = self._padding
        mx = self.max
        lcm = math.lcm(r, bit_length)
        for x in self._child.modulo(lcm):
            assert x <= mx and x < lcm
            yield self._pad(x) % bit_length

    @property
    def min(self) -> int:
        return self._pad(self._child.min)

    @property
    def max(self) -> int:
        return self._pad(self._child.max)

    def expand(self) -> typing.Iterable[int]:
        return map(self._pad, self._child.expand())

    def _pad(self, x: int) -> int:
        r = self._padding
        return ((x + r - 1) // r) * r


class ConcatenationOperator(Operator):
    """
    Given a set of children, transforms them into a single bit length set expression where each item is the
    elementwise sum of the cartesian product of the children's bit length sets.
    """

    def __init__(self, children: typing.Iterable[Operator]) -> None:
        self._children = list(children)
        if not self._children:
            raise ValueError("This operator is not defined on zero operands")

    def modulo(self, bit_length: int) -> typing.Iterable[int]:
        # Take the modulus from each child and find all combinations.
        # The computational complexity is tightly bounded because the cardinality of the modulus set is less than
        # the bit length operand.
        mods = [set(ch.modulo(bit_length)) for ch in self._children]
        prod = itertools.product(*mods)
        sums = set(map(sum, prod))
        return set(typing.cast(int, x) % bit_length for x in sums)

    @property
    def min(self) -> int:
        return sum(x.min for x in self._children)

    @property
    def max(self) -> int:
        return sum(x.max for x in self._children)

    def expand(self) -> typing.Iterable[int]:
        for el in itertools.product(*(x.expand() for x in self._children)):
            yield sum(el)
