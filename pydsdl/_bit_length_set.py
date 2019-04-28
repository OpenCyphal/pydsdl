#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import itertools


class BitLengthSet:
    """
    This type represents the Bit Length Set as defined in the Specification.
    It is used for representing bit offsets of fields and bit lengths of serialized representations.
    Can be constructed from an iterable that yields integers (e.g., another instance of same type or native set),
    or from a single integer, in which case it will result in the set containing only the one specified integer.
    Comparable with itself, plain integer, and native sets of integers.
    When cast to bool, evaluates to True unless empty.
    The alignment check methods ensure whether all of the contained offset values match the specified alignment goal.
    This class, just like the UAVCAN specification, assumes that one byte contains eight bits.
    """

    def __init__(self, values: typing.Optional[typing.Union[typing.Iterable[int], int]] = None):
        """
        The source container is always deep-copied.
        If a scalar integer is supplied, it is treated as a container of one element.
        >>> BitLengthSet()
        BitLengthSet()
        >>> len(BitLengthSet()) == 0
        True
        >>> BitLengthSet(1)
        BitLengthSet({1})
        >>> BitLengthSet({1, 2, 3})
        BitLengthSet({1, 2, 3})
        """
        if values is None:
            values = set()
        elif isinstance(values, int):
            values = {values}
        else:
            values = set(map(int, values))

        if not all(map(lambda x: x >= 0, values)):
            raise ValueError('Bit length set elements cannot be negative: %r' % values)

        assert isinstance(values, set)
        assert all(map(lambda x: isinstance(x, int) and x >= 0, values))
        self._value = values  # type: typing.Set[int]

    def is_aligned_at(self, bit_length: int) -> bool:
        """
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
        A shorthand for is_aligned_at(8).
        >>> BitLengthSet(32).is_aligned_at_byte()
        True
        >>> BitLengthSet(33).is_aligned_at_byte()
        False
        """
        return self.is_aligned_at(8)

    def unite_with(self, other: typing.Union[typing.Iterable[int], int]) -> None:
        """
        Modifies the object so that it is a union of itself with another bit length set.
        >>> a = BitLengthSet()
        >>> a.unite_with({1, 2, 3})
        >>> a
        BitLengthSet({1, 2, 3})
        >>> a.unite_with({3, 4, 5})
        >>> a
        BitLengthSet({1, 2, 3, 4, 5})
        >>> a.unite_with(6)
        >>> a
        BitLengthSet({1, 2, 3, 4, 5, 6})
        """
        self._value |= BitLengthSet(other)._value

    def increment(self, bit_length_set_or_scalar: typing.Union[typing.Iterable[int], int]) -> None:
        """
        This operation represents addition of a new object to a serialized representation.

        If the argument is a bit length set, an elementwise sum set of the Cartesian product of the argument set
        with the current set will be computed, and the result will replace the current set (i.e., this method updates
        the object it is invoked on). One can easily see that if the argument is a set of one value (or a scalar),
        this method will result in addition of said scalar to every element of the current set.

        SPECIAL CASE: if the current set is empty at the time of invocation, it will be assumed to be equal {0}.

        >>> a = BitLengthSet({1, 2, 3})
        >>> a.increment(4)
        >>> a
        BitLengthSet({5, 6, 7})
        >>> a = BitLengthSet({1, 2, 3})
        >>> a.increment({4, 5, 6})
        >>> a
        BitLengthSet({5, 6, 7, 8, 9})
        >>> a = BitLengthSet()
        >>> a.increment({1, 2, 3})
        >>> a
        BitLengthSet({1, 2, 3})
        """
        self._value = BitLengthSet.elementwise_sum_cartesian_product([self or BitLengthSet(0),
                                                                      BitLengthSet(bit_length_set_or_scalar)])._value

    def elementwise_sum_k_multicombinations(self, k: int) -> 'BitLengthSet':
        """
        This is a special case of elementwise_sum_cartesian_product().

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
        computationally suboptimal, since the fact that the elements are of the same type allows us to replace
        the relatively expensive Cartesian product with k-multicombinations (k-selections).

        In the context of bit length analysis, variable-length arrays do not require special treatment, since a
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

    @staticmethod
    def for_struct(member_bit_length_sets: typing.Iterable[typing.Union[typing.Iterable[int], int]]) -> 'BitLengthSet':
        """
        Computes the bit length set for a structure type given the bit length sets of each of its fields.
        As far as bit length sets are concerned, structures are similar to fixed-length arrays. The difference
        here is that the length value sets are not homogeneous across fields, as they can be of different types.
        """
        return BitLengthSet.elementwise_sum_cartesian_product(member_bit_length_sets) \
            or BitLengthSet(0)  # Empty output not permitted

    @staticmethod
    def for_tagged_union(member_bit_length_sets: typing.Iterable[typing.Union[typing.Iterable[int], int]]) \
            -> 'BitLengthSet':
        """
        Computes the bit length set for a tagged union type given the bit length sets of each of its fields (variants).
        Unions are easy to handle because when serialized, a union is essentially just a single field prefixed with
        a fixed-length integer tag. So we just build a full set of combinations and then add the tag length
        to each element. Observe that unions are not defined for less than 2 elements; however, this function tries
        to be generic by properly handling those cases as well, even though they are not permitted by the specification.
        For zero fields, the function yields zero {0}; for one field, the function yields the BLS of the field itself.
        """
        ms = list(member_bit_length_sets)
        del member_bit_length_sets

        out = BitLengthSet()
        if len(ms) == 0:
            out = BitLengthSet(0)
        elif len(ms) == 1:
            out = BitLengthSet(ms[0])
        else:
            for s in ms:
                out.unite_with(s)
            # Add the union tag:
            out.increment((len(ms) - 1).bit_length())

        return out

    def __iter__(self) -> typing.Iterator[int]:
        return iter(self._value)

    def __len__(self) -> int:
        return len(self._value)

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, _OPERAND_TYPES):
            return self._value == BitLengthSet(other)._value
        else:
            return NotImplemented

    def __bool__(self) -> bool:
        """
        >>> assert not BitLengthSet()
        >>> assert not BitLengthSet({})
        >>> assert BitLengthSet(0)
        >>> assert BitLengthSet({1, 2, 3})
        """
        return bool(self._value)

    def __add__(self, other: typing.Any) -> 'BitLengthSet':
        """
        Alias for elementwise_sum_cartesian_product([self, other]).
        Other may be a bit length set, an integer, or a native typing.Set[int].

        >>> BitLengthSet() + BitLengthSet()
        BitLengthSet()
        >>> BitLengthSet(4) + BitLengthSet(3)
        BitLengthSet({7})
        >>> BitLengthSet({4, 91}) + 3
        BitLengthSet({7, 94})
        """
        if isinstance(other, _OPERAND_TYPES):
            left = BitLengthSet(self)   # Create copy
            left.increment(other)
            return left
        else:
            return NotImplemented

    def __radd__(self, other: typing.Any) -> 'BitLengthSet':
        """
        See __add__().

        >>> {1, 2, 3} + BitLengthSet({4, 5, 6})
        BitLengthSet({5, 6, 7, 8, 9})
        >>> 1 + BitLengthSet({2, 5, 7})
        BitLengthSet({3, 6, 8})
        """
        if isinstance(other, _OPERAND_TYPES):
            return BitLengthSet(other) + BitLengthSet(self)
        else:
            return NotImplemented

    def __iadd__(self, other: typing.Any) -> 'BitLengthSet':
        """
        Alias for self.increment(other).
        Other may be a bit length set, an integer, or a native typing.Set[int].

        >>> a = BitLengthSet({1, 2, 3})
        >>> a += {4, 5, 6}
        >>> a
        BitLengthSet({5, 6, 7, 8, 9})
        """
        if isinstance(other, _OPERAND_TYPES):
            self.increment(other)
            return self
        else:
            return NotImplemented

    def __str__(self) -> str:
        """
        Always yields a sorted representation for ease of human consumption.

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
    with raises(ValueError):
        BitLengthSet({-1})

    s = BitLengthSet({0, 8})
    s.increment(8)
    assert s == {8, 16}
    s.increment({0, 4, 8})
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
