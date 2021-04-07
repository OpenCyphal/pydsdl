# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import typing
import warnings
from ._symbolic import Operator, NullaryOperator, MemoizationOperator


class BitLengthSet:
    """
    This type represents the Bit Length Set as defined in the Specification.
    It is used for representing bit offsets of fields and bit lengths of serialized representations.

    Most of the methods are evaluated analytically in nearly constant time rather than numerically.
    This is critical for complex layouts where numerical methods break due to combinatorial explosion and/or memory
    limits (see this discussed in https://github.com/UAVCAN/pydsdl/issues/23).
    There are several methods that trigger numerical expansion of the solution;
    due to the aforementioned combinatorial difficulties, they may be effectively incomputable in reasonable time,
    so production systems should not rely on them.

    Instances are guaranteed to be immutable.

    >>> b = 16 + BitLengthSet(8).repeat_range(256)
    >>> b
    BitLengthSet(concat({16},repeat(<=256,{8})))
    >>> b = 32 + b.repeat_range(65536)
    >>> b
    BitLengthSet(concat({32},repeat(<=65536,concat({16},repeat(<=256,{8})))))
    >>> b.min, b.max
    (32, 135266336)
    >>> sorted(b % 16)
    [0, 8]
    >>> sorted(b % 32)
    [0, 8, 16, 24]
    """

    def __init__(self, value: typing.Union[typing.Iterable[int], int, Operator, "BitLengthSet"]):
        """
        Accepts any iterable that yields integers (like another bit length set) or a single integer.
        """
        if isinstance(value, BitLengthSet):
            self._op = value._op  # type: Operator
        elif isinstance(value, Operator):
            self._op = MemoizationOperator(value)
        elif isinstance(value, int):
            self._op = NullaryOperator([value])
        else:
            self._op = NullaryOperator(value)

    # ========================================  QUERY METHODS  ========================================

    def is_aligned_at(self, bit_length: int) -> bool:
        """
        Shorthand for ``set(self % bit_length) == {0}``.

        >>> BitLengthSet(64).is_aligned_at(32)
        True
        >>> BitLengthSet(48).is_aligned_at(32)
        False
        >>> BitLengthSet(48).is_aligned_at(16)
        True
        >>> BitLengthSet(0).is_aligned_at(1234567)
        True
        """
        return set(self % bit_length) == {0}

    def is_aligned_at_byte(self) -> bool:
        """
        A shorthand for :meth:`is_aligned_at` using the standard byte size as prescribed by the Specification.

        >>> BitLengthSet(32).is_aligned_at_byte()
        True
        >>> BitLengthSet(33).is_aligned_at_byte()
        False
        """
        from .._serializable import SerializableType

        return self.is_aligned_at(SerializableType.BITS_PER_BYTE)

    @property
    def min(self) -> int:
        """
        The smallest element in the set derived analytically.

        >>> BitLengthSet.concatenate([{1, 2, 3}, {4, 5, 6}, {7, 8, 9}]).min
        12
        """
        return self._op.min

    @property
    def max(self) -> int:
        """
        The largest element in the set derived analytically.

        >>> BitLengthSet.concatenate([{1, 2, 3}, {4, 5, 6}, {7, 8, 9}]).pad_to_alignment(8).max
        24
        """
        return self._op.max

    @property
    def fixed_length(self) -> bool:
        """
        Shorthand for ``self.min == self.max``.

        >>> BitLengthSet(8).repeat(1).fixed_length
        True
        >>> BitLengthSet(8).repeat_range(1).fixed_length
        False
        """
        return self.min == self.max

    def __mod__(self, divisor: int) -> typing.Iterable[int]:
        """
        Elementwise modulus derived analytically.

        >>> sorted(BitLengthSet([0]) % 12345)
        [0]
        >>> sorted(BitLengthSet([8, 12, 16]) % 8)
        [0, 4]
        """
        # The type is reported as iterable[int], not sure yet if we should specialize it further. Time will tell.
        return BitLengthSet(self._op.modulo(int(divisor)))

    # ========================================  COMPOSITION METHODS  ========================================

    def pad_to_alignment(self, bit_length: int) -> "BitLengthSet":
        """
        Transform the bit length set expression such that the set becomes aligned at the specified alignment goal.
        After this transformation is applied, elements may become up to ``bit_length-1`` bits larger.
        The argument shall be a positive integer, otherwise it's a :class:`ValueError`.

        >>> from random import randint
        >>> alignment = randint(1, 64)
        >>> BitLengthSet(randint(1, 1000) for _ in range(100)).pad_to_alignment(alignment).is_aligned_at(alignment)
        True
        """
        from ._symbolic import PaddingOperator

        return BitLengthSet(PaddingOperator(self._op, bit_length))

    def repeat(self, k: int) -> "BitLengthSet":
        """
        Construct a new bit length set expression that repeats the current one the specified number of times.
        This reflects the arrangement of fixed-length DSDL array elements.
        This is a special case of :meth:`concatenate`.

        >>> sorted(BitLengthSet(1).repeat(0))
        [0]
        >>> sorted(BitLengthSet(1).repeat(1))
        [1]
        >>> sorted(BitLengthSet({1, 2, 3}).repeat(1))
        [1, 2, 3]
        >>> sorted(BitLengthSet({1, 2, 3}).repeat(2))
        [2, 3, 4, 5, 6]
        """
        from ._symbolic import RepetitionOperator

        return BitLengthSet(RepetitionOperator(self._op, k))

    def repeat_range(self, k_max: int) -> "BitLengthSet":
        """
        This is like :meth:`repeat` but ``k`` spans the range ``[0, k_max]``.

        >>> sorted(BitLengthSet({1, 2, 3}).repeat_range(2))
        [0, 1, 2, 3, 4, 5, 6]
        """
        from ._symbolic import RangeRepetitionOperator

        return BitLengthSet(RangeRepetitionOperator(self._op, k_max))

    @staticmethod
    def concatenate(sets: typing.Iterable[typing.Union["BitLengthSet", typing.Iterable[int], int]]) -> "BitLengthSet":
        """
        Construct a new bit length set expression that concatenates multiple bit length sets one after another.
        This reflects the data fields arrangement in a DSDL structure type.

        >>> sorted(BitLengthSet.concatenate([1, 2, 10]))
        [13]
        >>> sorted(BitLengthSet.concatenate([{1, 2}, {4, 5}]))
        [5, 6, 7]
        >>> sorted(BitLengthSet.concatenate([{1, 2, 3}, {4, 5, 6}]))
        [5, 6, 7, 8, 9]
        >>> sorted(BitLengthSet.concatenate([{1, 2, 3}, {4, 5, 6}, {7, 8, 9}]))
        [12, 13, 14, 15, 16, 17, 18]
        """
        from ._symbolic import ConcatenationOperator

        op = ConcatenationOperator(BitLengthSet(s)._op for s in sets)  # pylint: disable=protected-access
        return BitLengthSet(op)

    @staticmethod
    def unite(sets: typing.Iterable[typing.Union["BitLengthSet", typing.Iterable[int], int]]) -> "BitLengthSet":
        """
        Construct a new bit length set expression that is a union of multiple bit length sets.
        This reflects the data fields arrangement in a DSDL discriminated union.

        >>> sorted(BitLengthSet.unite([1, 2, 10]))
        [1, 2, 10]
        >>> sorted(BitLengthSet.unite([{1, 2}, {2, 3}]))
        [1, 2, 3]
        """
        from ._symbolic import UnionOperator

        op = UnionOperator(BitLengthSet(s)._op for s in sets)  # pylint: disable=protected-access
        return BitLengthSet(op)

    def __add__(self, other: typing.Union["BitLengthSet", typing.Iterable[int], int]) -> "BitLengthSet":
        """
        A shorthand for ``concatenate([self, other])``.
        One can easily see that if the argument is a set of one value (or a scalar),
        this method will result in the addition of said scalar to every element of the original set.

        >>> sorted(BitLengthSet(0) + BitLengthSet(0))
        [0]
        >>> sorted(BitLengthSet(4) + BitLengthSet(3))
        [7]
        >>> sorted(BitLengthSet({4, 91}) + 3)
        [7, 94]
        >>> sorted(BitLengthSet({4, 91}) + {5, 7})
        [9, 11, 96, 98]
        """
        return BitLengthSet.concatenate([self, other])

    def __radd__(self, other: typing.Union["BitLengthSet", typing.Iterable[int], int]) -> "BitLengthSet":
        """
        See :meth:`__add__`.

        >>> sorted({1, 2, 3} + BitLengthSet({4, 5, 6}))
        [5, 6, 7, 8, 9]
        >>> sorted(1 + BitLengthSet({2, 5, 7}))
        [3, 6, 8]
        """
        return BitLengthSet.concatenate([other, self])

    def __or__(self, other: typing.Union["BitLengthSet", typing.Iterable[int], int]) -> "BitLengthSet":
        """
        A shorthand for ``unite([self, other])``.

        >>> a = BitLengthSet(0)
        >>> a = a | BitLengthSet({1, 2, 3})
        >>> sorted(a)
        [0, 1, 2, 3]
        >>> a = a | {3, 4, 5}
        >>> sorted(a)
        [0, 1, 2, 3, 4, 5]
        >>> sorted(a | 6)
        [0, 1, 2, 3, 4, 5, 6]
        """
        return BitLengthSet.unite([self, other])

    def __ror__(self, other: typing.Union["BitLengthSet", typing.Iterable[int], int]) -> "BitLengthSet":
        """
        See :meth:`__or__`.

        >>> sorted({1, 2, 3} | BitLengthSet({4, 5, 6}))
        [1, 2, 3, 4, 5, 6]
        >>> sorted(1 | BitLengthSet({2, 5, 7}))
        [1, 2, 5, 7]
        """
        return BitLengthSet.unite([other, self])

    # ========================================  SLOW NUMERICAL METHODS  ========================================

    def __iter__(self) -> typing.Iterator[int]:
        """
        ..  attention::
            This method triggers slow numerical expansion.

            You might be tempted to use ``min(foo)`` or ``max(foo)`` for detecting length bounds.
            This may be effectively incomputable for data types with complex layout.
            Instead, use :attr:`min` and :attr:`max`.
        """
        return iter(self._op.expand())

    def __len__(self) -> int:
        """
        ..  attention::
            This method triggers slow numerical expansion.

            You might be tempted to use something like ``len(foo) == 1`` for detecting fixed-length sets.
            This may be effectively incomputable for data types with complex layout.
            Instead, use :attr:`fixed_length`.

        >>> len(BitLengthSet(0))
        1
        >>> len(BitLengthSet([1, 2, 3]))
        3
        """
        return len(self._op.expand())

    # ========================================  AUXILIARY METHODS  ========================================

    def __eq__(self, other: typing.Any) -> bool:
        """
        Currently, this method performs an approximate comparison that may yield a false-positive for some operands.
        This is done to avoid performing the costly numerical expansion of the operands.
        The implementation may be changed to perform exact comparison in the future if the underlying solver is
        updated accordingly.

        >>> BitLengthSet([1, 2, 4]) == {1, 2, 4}
        True
        >>> BitLengthSet([1, 2, 4]) == {1, 3, 4}
        False
        >>> BitLengthSet([123]) == BitLengthSet(123)
        True
        """
        try:
            other = BitLengthSet(other)
        except TypeError:
            return NotImplemented
        divisor = 32
        return self.min == other.min and self.max == other.max and set(self % divisor) == set(other % divisor)

    def __hash__(self) -> int:
        """
        Hash is computed in constant time (numerical expansion is not performed).

        >>> hash(BitLengthSet({1, 4})) != hash(BitLengthSet({1, 3}))
        True
        """
        return hash((self.min, self.max))

    def __bool__(self) -> bool:
        """
        This method is overridden to avoid accidental invocation of :meth:`__len__` in boolean expressions
        because it triggers numerical expansion.

        :return: Always True.
        """
        return True  # pragma: no cover

    def __str__(self) -> str:
        return str(self._op)

    def __repr__(self) -> str:
        return "%s(%s)" % (type(self).__name__, self)

    # ========================================  DEPRECATED METHODS   ========================================

    def elementwise_sum_k_multicombinations(self, k: int) -> "BitLengthSet":  # pragma: no cover
        """
        :meta private:
        """
        warnings.warn("Use repeat() instead", DeprecationWarning)
        return self.repeat(k)

    @staticmethod
    def elementwise_sum_cartesian_product(
        sets: typing.Iterable[typing.Union[typing.Iterable[int], int]]
    ) -> "BitLengthSet":  # pragma: no cover
        """
        :meta private:
        """
        warnings.warn("Use concatenate() instead", DeprecationWarning)
        return BitLengthSet.concatenate(sets)


def _unittest_bit_length_set() -> None:
    from pytest import raises

    assert BitLengthSet(0) == BitLengthSet(0)
    assert not (BitLengthSet(0) != BitLengthSet(0))  # pylint: disable=unneeded-not
    assert BitLengthSet(123) == BitLengthSet([123])
    assert BitLengthSet(123) != BitLengthSet(124)
    assert BitLengthSet(123) == 123
    assert BitLengthSet(123) != 124
    assert not (BitLengthSet(123) == "123")  # pylint: disable=unneeded-not
    assert str(BitLengthSet(0)) == "{0}"
    assert str(BitLengthSet(123)) == "{123}"
    assert str(BitLengthSet((123, 0, 456, 12))) == "{0,12,123,456}"  # Always sorted!
    assert BitLengthSet(0).is_aligned_at(1)
    assert BitLengthSet(0).is_aligned_at(1024)
    assert BitLengthSet(8).is_aligned_at_byte()
    assert not BitLengthSet(8).is_aligned_at(16)

    s = BitLengthSet({0, 8})
    s += 8
    assert s == {8, 16}
    s = s + {0, 4, 8}
    assert s == {8, 16, 12, 20, 24}

    assert BitLengthSet(0) + BitLengthSet(0) == BitLengthSet(0)
    assert BitLengthSet(4) + BitLengthSet(3) == {7}
    assert BitLengthSet({4, 91}) + 3 == {7, 94}
    assert BitLengthSet(7) + {12, 15} == {19, 22}
    assert {1, 2, 3} + BitLengthSet([4, 5, 6]) == {5, 6, 7, 8, 9}

    with raises(TypeError):
        assert BitLengthSet([4, 5, 6]) + "a"  # type: ignore

    with raises(TypeError):
        assert "a" + BitLengthSet([4, 5, 6])  # type: ignore

    with raises(TypeError):
        assert "a" | BitLengthSet([4, 5, 6])  # type: ignore

    with raises(TypeError):
        assert BitLengthSet([4, 5, 6]) | "a"  # type: ignore

    with raises(ValueError):
        BitLengthSet([4, 5, 6]).pad_to_alignment(0)
