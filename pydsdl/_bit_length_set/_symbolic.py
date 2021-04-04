# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import abc
import math
import typing
import itertools


class Operator(abc.ABC):
    @abc.abstractmethod
    def modulo(self, divisor: int) -> typing.Iterable[int]:
        """
        May return duplicates.
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
        This is useful for cross-checking derived solutions and for DSDL expression evaluation.
        For complex expressions this may be incomputable due to combinatorial explosion or memory limits.
        May return duplicates.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def __repr__(self) -> str:
        raise NotImplementedError


class NullaryOperator(Operator):
    """
    A nullary operator represents a constant value, which is a leaf of the operator tree.
    """

    def __init__(self, values: typing.Iterable[int]) -> None:
        self._value = frozenset(values) or frozenset({0})

    def modulo(self, divisor: int) -> typing.Iterable[int]:
        return map(lambda x: x % divisor, self._value)

    @property
    def min(self) -> int:
        return min(self._value)

    @property
    def max(self) -> int:
        return max(self._value)

    def expand(self) -> typing.Iterable[int]:
        return self._value

    def __repr__(self) -> str:
        return "{%s}" % ",".join(str(x) for x in sorted(self._value))


class PaddingOperator(Operator):
    """
    Adds up to ``alignment - 1`` padding bits to each entry of the child to ensure that the values are aligned.
    """

    def __init__(self, child: Operator, alignment: int) -> None:
        if alignment < 1:  # pragma: no cover
            raise ValueError("Invalid alignment: %r bits" % alignment)
        self._child = child
        self._padding = int(alignment)

    def modulo(self, divisor: int) -> typing.Iterable[int]:
        r = self._padding
        mx = self.max
        lcm = math.lcm(r, divisor)
        for x in set(self._child.modulo(lcm)):
            assert x <= mx and x < lcm
            yield self._pad(x) % divisor

    @property
    def min(self) -> int:
        return self._pad(self._child.min)

    @property
    def max(self) -> int:
        return self._pad(self._child.max)

    def expand(self) -> typing.Iterable[int]:
        return set(map(self._pad, self._child.expand()))

    def _pad(self, x: int) -> int:
        r = self._padding
        return ((x + r - 1) // r) * r

    def __repr__(self) -> str:
        return "pad(%d,%r)" % (self._padding, self._child)


class ConcatenationOperator(Operator):
    """
    Given a set of children, transforms them into a single bit length set expression where each item is the
    elementwise sum of the cartesian product of the children's bit length sets.
    """

    def __init__(self, children: typing.Iterable[Operator]) -> None:
        self._children = list(children)
        if not self._children:
            raise ValueError("This operator is not defined on zero operands")

    def modulo(self, divisor: int) -> typing.Iterable[int]:
        # Take the modulus from each child and find all combinations.
        # The computational complexity is tightly bounded because the cardinality of the modulus set is less than
        # the bit length operand.
        mods = [set(ch.modulo(divisor)) for ch in self._children]
        prod = itertools.product(*mods)
        sums = set(map(sum, prod))
        return {typing.cast(int, x) % divisor for x in sums}

    @property
    def min(self) -> int:
        return sum(x.min for x in self._children)

    @property
    def max(self) -> int:
        return sum(x.max for x in self._children)

    def expand(self) -> typing.Iterable[int]:
        return {sum(el) for el in itertools.product(*(x.expand() for x in self._children))}

    def __repr__(self) -> str:
        return "concat(%s)" % ",".join(map(repr, self._children))


class RepetitionOperator(Operator):
    """
    Concatenates ``k`` copies of the child.
    This is equivalent to :class:`ConcatenationOperator` where the child is replicated ``k`` times.
    """

    def __init__(self, child: Operator, k: int) -> None:
        self._k = int(k)
        self._child = child

    def modulo(self, divisor: int) -> typing.Iterable[int]:
        return {
            (sum(el) % divisor) for el in itertools.combinations_with_replacement(self._child.modulo(divisor), self._k)
        }

    @property
    def min(self) -> int:
        return self._child.min * self._k

    @property
    def max(self) -> int:
        return self._child.max * self._k

    def expand(self) -> typing.Iterable[int]:
        return {sum(el) for el in itertools.combinations_with_replacement(self._child.expand(), self._k)}

    def __repr__(self) -> str:
        return "repeat(%d,%r)" % (self._k, self._child)


class RangeRepetitionOperator(Operator):
    """
    Concatenates ``k in [0, k_max]`` copies of the child.
    In other words, this is like ``k+1`` instances of :class:`RepetitionOperator`.
    """

    def __init__(self, child: Operator, k_max: int) -> None:
        self._k_max = int(k_max)
        self._child = child

    def modulo(self, divisor: int) -> typing.Iterable[int]:
        single = set(self._child.modulo(divisor))
        # Values of k > divisor will yield repeated entries so we can apply a reduction.
        equivalent_k_max = min(self._k_max, divisor)
        for k in range(equivalent_k_max + 1):
            for el in itertools.combinations_with_replacement(single, k):
                yield sum(el) % divisor

    @property
    def min(self) -> int:
        return 0

    @property
    def max(self) -> int:
        return self._child.max * self._k_max

    def expand(self) -> typing.Iterable[int]:
        ch = set(self._child.expand())
        for k in range(self._k_max + 1):
            for el in itertools.combinations_with_replacement(ch, k):
                yield sum(el)

    def __repr__(self) -> str:
        return "repeat(<=%d,%r)" % (self._k_max, self._child)


class UnionOperator(Operator):
    def __init__(self, children: typing.Iterable[Operator]) -> None:
        self._children = list(children)
        if not self._children:
            raise ValueError("This operator is not defined on zero operands")

    def modulo(self, divisor: int) -> typing.Iterable[int]:
        for x in self._children:
            yield from x.modulo(divisor)

    @property
    def min(self) -> int:
        return min(x.min for x in self._children)

    @property
    def max(self) -> int:
        return max(x.max for x in self._children)

    def expand(self) -> typing.Iterable[int]:
        for x in self._children:
            yield from x.expand()

    def __repr__(self) -> str:
        return "(%s)" % "|".join(map(repr, self._children))


def validate_numerically(op: Operator) -> None:
    """
    Validates the correctness of symbolic derivations by comparing the results against reference values
    obtained numerically.
    The computational complexity may be prohibitively high for some inputs due to combinatorial explosion.
    In case of a divergence the function triggers an assertion failure.
    """
    s = set(op.expand())
    assert min(s) == op.min
    assert max(s) == op.max
    for div in range(1, 65):
        assert set(op.modulo(div)) == {x % div for x in s}
