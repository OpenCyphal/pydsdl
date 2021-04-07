# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import os
import abc
import math
import typing
import logging
import itertools


class Operator(abc.ABC):
    """
    Operators are immutable. This allows for aggressive caching and reference-sharing.
    """

    @abc.abstractmethod
    def modulo(self, divisor: int) -> typing.Set[int]:
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
    def expand(self) -> typing.Set[int]:
        """
        Transform the symbolic form into numerical form.
        This is useful for cross-checking derived solutions and for DSDL expression evaluation.
        For complex expressions this may be incomputable due to combinatorial explosion or memory limits.
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
        self._value = set(values)
        if not self._value:
            raise ValueError("A bit length set cannot be empty. Did you mean to pass {0}?")
        for x in self._value:
            if not isinstance(x, int):
                raise TypeError("Invalid element for nullary set operator: %r" % x)

    def modulo(self, divisor: int) -> typing.Set[int]:
        return set(map(lambda x: x % divisor, self._value))

    @property
    def min(self) -> int:
        return min(self._value)

    @property
    def max(self) -> int:
        return max(self._value)

    def expand(self) -> typing.Set[int]:
        return set(self._value)

    def __repr__(self) -> str:
        return "{%s}" % ",".join(str(x) for x in sorted(self._value))


class PaddingOperator(Operator):
    """
    Adds up to ``alignment - 1`` padding bits to each entry of the child to ensure that the values are aligned.
    """

    def __init__(self, child: Operator, alignment: int) -> None:
        if alignment < 1:
            raise ValueError("Invalid alignment: %r bits" % alignment)
        self._child = child
        self._padding = int(alignment)

    def modulo(self, divisor: int) -> typing.Set[int]:
        r = self._padding
        mx = self.max
        lcm = least_common_multiple(r, divisor)
        out = set()  # type: typing.Set[int]
        for x in self._child.modulo(lcm):
            assert x <= mx and x < lcm
            out.add(self._pad(x) % divisor)
        return out

    @property
    def min(self) -> int:
        return self._pad(self._child.min)

    @property
    def max(self) -> int:
        return self._pad(self._child.max)

    def expand(self) -> typing.Set[int]:
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

    def modulo(self, divisor: int) -> typing.Set[int]:
        # Take the modulus from each child and find all combinations.
        # The computational complexity is tightly bounded because the cardinality of the modulus set is less than
        # the bit length operand.
        mods = [ch.modulo(divisor) for ch in self._children]
        prod = itertools.product(*mods)
        sums = set(map(sum, prod))
        return {typing.cast(int, x) % divisor for x in sums}

    @property
    def min(self) -> int:
        return sum(x.min for x in self._children)

    @property
    def max(self) -> int:
        return sum(x.max for x in self._children)

    def expand(self) -> typing.Set[int]:
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

    def modulo(self, divisor: int) -> typing.Set[int]:
        # Values of k > divisor will yield repeated entries so we can apply a reduction,
        # but the equivalent k modulo divisor shall be the same as k modulo divisor.
        # This is because the solution doesn't converge at k -> inf:
        #   {sum(x) % 2 for x in combinations_with_replacement({1, 3}, 2)} == {0}
        #   {sum(x) % 2 for x in combinations_with_replacement({1, 3}, 3)} == {1}
        #   {sum(x) % 2 for x in combinations_with_replacement({1, 3}, 4)} == {0}
        #   {sum(x) % 2 for x in combinations_with_replacement({1, 3}, 5)} == {1}
        # etc.
        equivalent_k = min(self._k, divisor + self._k % divisor)
        assert (self._k % divisor) == (equivalent_k % divisor), (divisor, self._k)
        return {
            (sum(el) % divisor)
            for el in itertools.combinations_with_replacement(self._child.modulo(divisor), equivalent_k)
        }

    @property
    def min(self) -> int:
        return self._child.min * self._k

    @property
    def max(self) -> int:
        return self._child.max * self._k

    def expand(self) -> typing.Set[int]:
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

    def modulo(self, divisor: int) -> typing.Set[int]:
        single = self._child.modulo(divisor)
        assert isinstance(single, set)
        # Values of k > divisor will yield repeated entries so we can apply a reduction (see non-range case above).
        # This holds only if the argument does not contain repeated entries which is guaranteed by `set`.
        equivalent_k_max = min(self._k_max, divisor + self._k_max % divisor)
        assert (self._k_max % divisor) == (equivalent_k_max % divisor), (divisor, self._k_max)
        out = set()  # type: typing.Set[int]
        for k in range(equivalent_k_max + 1):
            for el in itertools.combinations_with_replacement(single, k):
                out.add(sum(el) % divisor)
        return out

    @property
    def min(self) -> int:
        return 0

    @property
    def max(self) -> int:
        return self._child.max * self._k_max

    def expand(self) -> typing.Set[int]:
        ch = self._child.expand()
        assert isinstance(ch, set)
        out = set()  # type: typing.Set[int]
        for k in range(self._k_max + 1):
            for el in itertools.combinations_with_replacement(ch, k):
                out.add(sum(el))
        return out

    def __repr__(self) -> str:
        return "repeat(<=%d,%r)" % (self._k_max, self._child)


class UnionOperator(Operator):
    def __init__(self, children: typing.Iterable[Operator]) -> None:
        self._children = list(children)
        if not self._children:
            raise ValueError("This operator is not defined on zero operands")

    def modulo(self, divisor: int) -> typing.Set[int]:
        out = set()  # type: typing.Set[int]
        for x in self._children:
            out |= x.modulo(divisor)
        return out

    @property
    def min(self) -> int:
        return min(x.min for x in self._children)

    @property
    def max(self) -> int:
        return max(x.max for x in self._children)

    def expand(self) -> typing.Set[int]:
        out = set()  # type: typing.Set[int]
        for x in self._children:
            out |= x.expand()
        return out

    def __repr__(self) -> str:
        return "(%s)" % "|".join(map(repr, self._children))


class MemoizationOperator(Operator):
    """
    This is a no-op transparent lazy cache on top of the child operator.
    It also logs a stack trace if the child takes too long to expand to help with bottleneck optimization.
    """

    def __init__(self, child: Operator) -> None:
        self._child = child
        self._min = None  # type: typing.Optional[int]
        self._max = None  # type: typing.Optional[int]
        self._modula = {}  # type: typing.Dict[int, typing.Set[int]]
        self._expansion = None  # type: typing.Optional[typing.Set[int]]

    def modulo(self, divisor: int) -> typing.Set[int]:
        try:
            return self._modula[divisor]
        except LookupError:
            self._modula[divisor] = self._child.modulo(divisor)
        return self._modula[divisor]

    @property
    def min(self) -> int:
        if self._min is None:
            self._min = self._child.min
        return self._min

    @property
    def max(self) -> int:
        if self._max is None:
            self._max = self._child.max
        return self._max

    def expand(self) -> typing.Set[int]:
        if self._expansion is None:
            from time import monotonic

            # Track the time and log occurrences that take a long time to help find bottlenecks in user code
            # that accidentally relies on numerical expansion. This is mainly intended to help us transition
            # Nunavut to the new solver API instead of numerical methods. It may be removed later.
            started_at = monotonic()
            self._expansion = self._child.expand()
            elapsed = monotonic() - started_at
            if elapsed > 2.0:  # pragma: no cover
                _logger.info(
                    "Numerical expansion took %.1f seconds; the result contains %d items:\n%s",
                    elapsed,
                    len(self._expansion),
                    self._child,
                    stack_info=True,
                )
            assert elapsed < _POISON_SLOW_EXPANSION_SECONDS

            # Since we did an expansion anyway, the set must be compact,
            # so we use this opportunity to validate the correctness of the solver.
            # This may be removed easily since it has no visible effects.
            validate_numerically(self)

        return self._expansion

    def __repr__(self) -> str:
        return repr(self._child)  # Not sure if we should indicate our presence considering that we're a no-op


def least_common_multiple(a: int, b: int) -> int:
    """
    This replicates :func:`math.lcm` to support Python <3.9.
    """
    return abs(a * b) // math.gcd(a, b)


def validate_numerically(op: Operator) -> None:
    """
    Validates the correctness of symbolic derivations by comparing the results against reference values
    obtained numerically.
    The computational complexity may be prohibitively high for some inputs due to combinatorial explosion.
    In case of a divergence the function triggers an assertion failure.
    """
    s = op.expand()
    assert min(s) == op.min
    assert max(s) == op.max
    for div in range(1, 65):
        assert op.modulo(div) == {x % div for x in s}, div


_POISON_SLOW_EXPANSION_SECONDS = float(os.environ.get("PYDSDL_POISON_SLOW_EXPANSION_SECONDS", "999999999"))
"""
This is intended for developers only so it is not mentioned in the public documentation.
The purpose is to trigger an assertion failure if a numerical expansion takes more than this many seconds.
"""

_logger = logging.getLogger(__name__)
