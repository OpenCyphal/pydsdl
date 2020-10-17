#
# Copyright (C) 2018-2020  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import itertools


class BitLengthSet:
    """
    This type represents the Bit Length Set as defined in the Specification.
    It is used for representing bit offsets of fields and bit lengths of serialized representations.

    Instances are comparable between each other, with plain integers, and with native sets of integers.
    The methods do not mutate the instance they are invoked on; instead, the result is returned as a new instance,
    excepting the in-place ``__ixx__()`` operator overloads.

    This class performs very intensive computations that largely define the data type processing time
    so it has been carefully optimized for speed. For details, see https://github.com/UAVCAN/pydsdl/issues/49.
    """

    def __init__(self, values: typing.Optional[typing.Union[typing.Iterable[int], int]] = None):
        """
        Accepts any iterable that yields integers (like another bit length set) or a single integer,
        in which case it will result in the set containing only the one specified integer.
        The source container is always deep-copied.

        >>> BitLengthSet()
        BitLengthSet()
        >>> len(BitLengthSet()) == 0
        True
        >>> BitLengthSet(1)
        BitLengthSet({1})
        >>> BitLengthSet({1, 2, 3})
        BitLengthSet({1, 2, 3})
        """
        if isinstance(values, set):
            self._value = values  # Do not convert if already a set
        elif values is None:
            self._value = set()
        elif isinstance(values, int):
            self._value = {values}
        else:
            self._value = set(map(int, values))

    def is_aligned_at(self, bit_length: int) -> bool:
        """
        Checks whether all of the contained offset values match the specified alignment goal.
        An empty bit length set is considered to have infinite alignment.

        >>> BitLengthSet(64).is_aligned_at(32)
        True
        >>> BitLengthSet(48).is_aligned_at(32)
        False
        >>> BitLengthSet(48).is_aligned_at(16)
        True
        >>> BitLengthSet().is_aligned_at(123456)
        True
        """
        if self:
            return set(map(lambda x: x % bit_length, self._value)) == {0}
        else:
            return True     # An empty set is always aligned.

    def is_aligned_at_byte(self) -> bool:
        """
        A shorthand for :meth:`is_aligned_at` using the standard byte size as prescribed by the Specification.

        >>> BitLengthSet(32).is_aligned_at_byte()
        True
        >>> BitLengthSet(33).is_aligned_at_byte()
        False
        """
        from ._serializable import SerializableType
        return self.is_aligned_at(SerializableType.BITS_PER_BYTE)

    def pad_to_alignment(self, bit_length: int) -> 'BitLengthSet':
        """
        Pad each element in the set such that the set becomes aligned at the specified alignment goal.
        After this transformation is applied, elements may become up to ``bit_length-1`` bits larger.
        The argument shall be a positive integer, otherwise it's a :class:`ValueError`.

        >>> BitLengthSet({0, 1, 2, 3, 4, 5, 6, 7, 8}).pad_to_alignment(1)  # Alignment to 1 is a no-op.
        BitLengthSet({0, 1, 2, 3, 4, 5, 6, 7, 8})
        >>> BitLengthSet({0, 1, 2, 3, 4, 5, 6, 7, 8}).pad_to_alignment(2)
        BitLengthSet({0, 2, 4, 6, 8})
        >>> BitLengthSet({0, 1, 5, 7}).pad_to_alignment(2)
        BitLengthSet({0, 2, 6, 8})
        >>> BitLengthSet({0, 1, 2, 3, 4, 5, 6, 7, 8}).pad_to_alignment(3)
        BitLengthSet({0, 3, 6, 9})
        >>> BitLengthSet({0, 1, 2, 3, 4, 5, 6, 7, 8}).pad_to_alignment(8)
        BitLengthSet({0, 8})
        >>> BitLengthSet({0, 9}).pad_to_alignment(8)
        BitLengthSet({0, 16})
        >>> from random import randint
        >>> alignment = randint(1, 64)
        >>> BitLengthSet(randint(1, 1000) for _ in range(100)).pad_to_alignment(alignment).is_aligned_at(alignment)
        True
        """
        r = int(bit_length)
        if r < 1:
            raise ValueError('Invalid alignment: %r bits' % r)
        else:
            assert r >= 1
            out = BitLengthSet(((x + r - 1) // r) * r for x in self)
            assert not out or 0 <= min(out) - min(self) < r
            assert not out or 0 <= max(out) - max(self) < r
            assert len(out) <= len(self)
            return out

    def elementwise_sum_k_multicombinations(self, k: int) -> 'BitLengthSet':
        """
        This is a special case of :meth:`elementwise_sum_cartesian_product`.
        The original object is not modified.

        One can replace this method with the aforementioned general case method and the behavior would not change;
        however, we need this special case method for performance reasons. When dealing with arrays (either fixed- or
        variable-length), usage of this method instead of the generic one yields significantly better performance,
        since the computational complexity of k-selections is much lower than that of the Cartesian product.

        >>> BitLengthSet(1).elementwise_sum_k_multicombinations(1)
        BitLengthSet({1})
        >>> BitLengthSet({1, 2, 3}).elementwise_sum_k_multicombinations(1)
        BitLengthSet({1, 2, 3})
        >>> BitLengthSet({1, 2, 3}).elementwise_sum_k_multicombinations(2)
        BitLengthSet({2, 3, 4, 5, 6})
        """
        k_multicombination = itertools.combinations_with_replacement(self, k)
        elementwise_sums = map(sum, k_multicombination)
        return BitLengthSet(elementwise_sums)  # type: ignore

    @staticmethod
    def elementwise_sum_cartesian_product(sets: typing.Iterable[typing.Union[typing.Iterable[int], int]]) \
            -> 'BitLengthSet':
        """
        This operation is fundamental for bit length and bit offset (which are, generally, the same thing) computation.

        The basic background is explained in the specification. The idea is that the bit offset of a given entity
        in a data type definition of the structure category (or, in other words, the bit length set of serialized
        representations of the preceding entities, which is the same thing, assuming that the data type is of the
        structure category) is a function of bit length sets of each preceding entity. Various combinations of
        bit lengths of the preceding entities are possible, which can be expressed through the Cartesian product over
        the bit length sets of the preceding entities. Since in a type of the structure category entities are arranged
        as an ordered sequence of a fixed length (meaning that entities can't be added or removed), the resulting
        bit length (offset) is computed by elementwise summation of each element of the Cartesian product.

        This method is not applicable for the tagged union type category, since a tagged union holds exactly one
        value at any moment; therefore, the bit length set of a tagged union is simply a union of bit length sets
        of each entity that can be contained in the union, plus the length of the implicit union tag field.

        From the standpoint of bit length combination analysis, fixed-length arrays are a special case of structures,
        because they also contain a fixed ordered sequence of fields, where all fields are of the same type.
        The method defined for structures applies to fixed-length arrays, but one should be aware that it may be
        computationally suboptimal, since the fact that all array elements are of the same type allows us to replace
        the computationally expensive Cartesian product with k-multicombinations (k-selections).

        In the context of bit length analysis, variable-length arrays do not require any special treatment, since a
        variable-length array with the capacity of N elements can be modeled as a tagged union containing
        N fixed arrays of length from 1 to N, plus one empty field (representing the case of an empty variable-length
        array).

        >>> BitLengthSet.elementwise_sum_cartesian_product([1, 2, 10])
        BitLengthSet({13})
        >>> BitLengthSet.elementwise_sum_cartesian_product([{1, 2}, {4, 5}])
        BitLengthSet({5, 6, 7})
        >>> BitLengthSet.elementwise_sum_cartesian_product([{1, 2, 3}, {4, 5, 6}])
        BitLengthSet({5, 6, 7, 8, 9})
        >>> BitLengthSet.elementwise_sum_cartesian_product([{1, 2, 3}, {4, 5, 6}, {7, 8, 9}])
        BitLengthSet({12, 13, 14, 15, 16, 17, 18})
        """
        cartesian_product = itertools.product(*list(map(BitLengthSet, sets)))
        elementwise_sums = map(sum, cartesian_product)
        return BitLengthSet(elementwise_sums)  # type: ignore

    def __iter__(self) -> typing.Iterator[int]:
        return iter(self._value)

    def __len__(self) -> int:
        """Cardinality."""
        return len(self._value)

    def __eq__(self, other: typing.Any) -> bool:
        """
        Whether the current set equals the other.
        The other may be a bit length set, an integer, or a native ``typing.Set[int]``.
        """
        if isinstance(other, _OPERAND_TYPES):
            return self._value == BitLengthSet(other)._value
        else:
            return NotImplemented

    def __bool__(self) -> bool:
        """
        Evaluates to True unless empty.

        >>> assert not BitLengthSet()
        >>> assert not BitLengthSet({})
        >>> assert BitLengthSet(0)
        >>> assert BitLengthSet({1, 2, 3})
        """
        return bool(self._value)

    def __add__(self, other: typing.Any) -> 'BitLengthSet':
        """
        This operation models the addition of a new object to a serialized representation;
        i.e., it is an alias for ``elementwise_sum_cartesian_product([self, other])``.
        The result is stored into a new instance which is returned.

        If the argument is a bit length set, an elementwise sum set of the Cartesian product of the argument set
        with the current set will be computed, and the result will be returned as a new set (self is not modified).
        One can easily see that if the argument is a set of one value (or a scalar),
        this method will result in the addition of said scalar to every element of the original set.

        SPECIAL CASE: if the current set is empty at the time of invocation, it will be assumed to be equal ``{0}``.

        The other may be a bit length set, an integer, or a native ``typing.Set[int]``.

        >>> BitLengthSet() + BitLengthSet()
        BitLengthSet()
        >>> BitLengthSet(4) + BitLengthSet(3)
        BitLengthSet({7})
        >>> BitLengthSet({4, 91}) + 3
        BitLengthSet({7, 94})
        >>> BitLengthSet({4, 91}) + {5, 7}
        BitLengthSet({9, 11, 96, 98})
        """
        if isinstance(other, _OPERAND_TYPES):
            return BitLengthSet.elementwise_sum_cartesian_product([self or BitLengthSet(0), BitLengthSet(other)])
        else:
            return NotImplemented

    def __radd__(self, other: typing.Any) -> 'BitLengthSet':
        """
        See :meth:`__add__`.

        >>> {1, 2, 3} + BitLengthSet({4, 5, 6})
        BitLengthSet({5, 6, 7, 8, 9})
        >>> 1 + BitLengthSet({2, 5, 7})
        BitLengthSet({3, 6, 8})
        """
        if isinstance(other, _OPERAND_TYPES):
            return BitLengthSet(other) + self
        else:
            return NotImplemented

    def __iadd__(self, other: typing.Any) -> 'BitLengthSet':
        """
        See :meth:`__add__`.

        >>> a = BitLengthSet({1, 2, 3})
        >>> a += {4, 5, 6}
        >>> a
        BitLengthSet({5, 6, 7, 8, 9})
        """
        if isinstance(other, _OPERAND_TYPES):
            self._value = (self + other)._value
            return self
        else:
            return NotImplemented

    def __or__(self, other: typing.Any) -> 'BitLengthSet':
        """
        Creates and returns a new set that is a union of this set with another bit length set.

        >>> a = BitLengthSet()
        >>> a = a | BitLengthSet({1, 2, 3})
        >>> a
        BitLengthSet({1, 2, 3})
        >>> a = a | {3, 4, 5}
        >>> a
        BitLengthSet({1, 2, 3, 4, 5})
        >>> a | 6
        BitLengthSet({1, 2, 3, 4, 5, 6})
        """
        if isinstance(other, _OPERAND_TYPES):
            if not isinstance(other, BitLengthSet):  # Speed optimization
                other = BitLengthSet(other)
            return BitLengthSet(self._value | other._value)
        else:
            return NotImplemented

    def __ror__(self, other: typing.Any) -> 'BitLengthSet':
        """
        See :meth:`__or__`.

        >>> {1, 2, 3} | BitLengthSet({4, 5, 6})
        BitLengthSet({1, 2, 3, 4, 5, 6})
        >>> 1 | BitLengthSet({2, 5, 7})
        BitLengthSet({1, 2, 5, 7})
        """
        if isinstance(other, _OPERAND_TYPES):
            return BitLengthSet(other) | self
        else:
            return NotImplemented

    def __ior__(self, other: typing.Any) -> 'BitLengthSet':
        """
        See :meth:`__or__`.

        >>> a = BitLengthSet({4, 5, 6})
        >>> a |= {1, 2, 3}
        >>> a
        BitLengthSet({1, 2, 3, 4, 5, 6})
        """
        if isinstance(other, _OPERAND_TYPES):
            self._value = (self | other)._value
            return self
        else:
            return NotImplemented

    def __str__(self) -> str:
        """
        Always yields a sorted representation for the ease of human consumption.

        >>> str(BitLengthSet())
        '{}'
        >>> str(BitLengthSet({918, 16, 7, 42}))
        '{7, 16, 42, 918}'
        """
        return '{' + ', '.join(map(str, sorted(self._value))) + '}'

    def __repr__(self) -> str:
        """
        >>> BitLengthSet()
        BitLengthSet()
        >>> BitLengthSet({918, 16, 7, 42})
        BitLengthSet({7, 16, 42, 918})
        """
        return type(self).__name__ + '(' + str(self or '') + ')'


_OPERAND_TYPES = BitLengthSet, set, int


def _unittest_bit_length_set() -> None:
    from pytest import raises
    assert not BitLengthSet()
    assert BitLengthSet() == BitLengthSet()
    assert not (BitLengthSet() != BitLengthSet())
    assert BitLengthSet(123) == BitLengthSet([123])
    assert BitLengthSet(123) != BitLengthSet(124)
    assert BitLengthSet(123) == 123
    assert BitLengthSet(123) != 124
    assert not (BitLengthSet(123) == '123')  # not implemented
    assert str(BitLengthSet()) == '{}'
    assert str(BitLengthSet(123)) == '{123}'
    assert str(BitLengthSet((123, 0, 456, 12))) == '{0, 12, 123, 456}'  # Always sorted!
    assert BitLengthSet().is_aligned_at(1)
    assert BitLengthSet().is_aligned_at(1024)
    assert BitLengthSet(8).is_aligned_at_byte()
    assert not BitLengthSet(8).is_aligned_at(16)

    s = BitLengthSet({0, 8})
    s += 8
    assert s == {8, 16}
    s = s + {0, 4, 8}
    assert s == {8, 16, 12, 20, 24}

    assert BitLengthSet() + BitLengthSet() == BitLengthSet()
    assert BitLengthSet(4) + BitLengthSet(3) == {7}
    assert BitLengthSet({4, 91}) + 3 == {7, 94}
    assert BitLengthSet(7) + {12, 15} == {19, 22}
    assert {1, 2, 3} + BitLengthSet([4, 5, 6]) == {5, 6, 7, 8, 9}

    with raises(TypeError):
        assert BitLengthSet([4, 5, 6]) + '1'

    with raises(TypeError):
        assert '1' + BitLengthSet([4, 5, 6])

    with raises(TypeError):
        s = BitLengthSet([4, 5, 6])
        s += '1'

    with raises(TypeError):
        assert '1' | BitLengthSet([4, 5, 6])

    with raises(TypeError):
        assert BitLengthSet([4, 5, 6]) | '1'

    with raises(TypeError):
        s = BitLengthSet([4, 5, 6])
        s |= '1'

    with raises(ValueError):
        BitLengthSet([4, 5, 6]).pad_to_alignment(0)
