# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import typing
import random
import itertools
from ._symbolic import NullaryOperator, validate_numerically


def _unittest_nullary() -> None:
    import pytest

    op = NullaryOperator([0])
    assert set(op.expand()) == {0}
    assert set(op.modulo(12345)) == {0}
    assert op.min == op.max == 0
    validate_numerically(op)

    op = NullaryOperator([1, 2, 3, 4, 5, 6, 7, 8])
    assert set(op.expand()) == {1, 2, 3, 4, 5, 6, 7, 8}
    assert set(op.modulo(4)) == {0, 1, 2, 3}
    assert (op.min, op.max) == (1, 8)
    validate_numerically(op)

    with pytest.raises(ValueError):
        NullaryOperator([])


def _unittest_padding() -> None:
    from ._symbolic import PaddingOperator

    op = PaddingOperator(
        NullaryOperator([1, 2, 3, 4, 5, 6, 7, 8, 9]),
        4,
    )
    assert op.min == 4
    assert op.max == 12
    assert set(op.expand()) == {4, 8, 12}
    assert set(op.modulo(2)) == {0}
    assert set(op.modulo(4)) == {0}
    assert set(op.modulo(8)) == {0, 4}
    assert set(op.modulo(16)) == {4, 8, 12}
    validate_numerically(op)

    assert set(x % 6 for x in op.expand()) == {0, 2, 4}  # Reference
    assert set(op.modulo(6)) == {0, 2, 4}

    assert set(x % 7 for x in op.expand()) == {1, 4, 5}  # Reference
    assert set(op.modulo(7)) == {1, 4, 5}

    for _ in range(1):
        child = NullaryOperator(random.randint(0, 1024) for _ in range(random.randint(1, 100)))
        alignment = random.randint(1, 64)
        op = PaddingOperator(child, alignment)
        div = random.randint(1, 64)
        assert set(op.modulo(div)) == {x % div for x in op.expand()}
        validate_numerically(op)


def _unittest_concatenation() -> None:
    import pytest
    from ._symbolic import ConcatenationOperator

    op = ConcatenationOperator(
        [
            NullaryOperator([1]),
            NullaryOperator([2]),
            NullaryOperator([10]),
        ]
    )
    assert op.min == op.max == 13
    assert set(op.expand()) == {13}
    assert set(op.modulo(1)) == {0}
    assert set(op.modulo(2)) == {1}
    assert set(op.modulo(13)) == {0}
    assert set(op.modulo(8)) == {5}
    validate_numerically(op)

    op = ConcatenationOperator(
        [
            NullaryOperator([1, 2, 10]),
        ]
    )
    assert op.min == 1
    assert op.max == 10
    assert set(op.expand()) == {1, 2, 10}
    assert set(op.modulo(1)) == {0}
    assert set(op.modulo(2)) == {0, 1}
    assert set(op.modulo(8)) == {1, 2}
    validate_numerically(op)

    op = ConcatenationOperator(
        [
            NullaryOperator([1, 2]),
            NullaryOperator([4, 5]),
        ]
    )
    assert op.min == 5
    assert op.max == 7
    assert set(op.expand()) == {5, 6, 7}
    assert set(op.modulo(5)) == {0, 1, 2}
    assert set(op.modulo(8)) == {5, 6, 7}
    validate_numerically(op)

    op = ConcatenationOperator(
        [
            NullaryOperator([1, 2, 3]),
            NullaryOperator([4, 5, 6]),
            NullaryOperator([7, 8, 9]),
        ]
    )
    assert op.min == 12
    assert op.max == 18
    assert set(op.expand()) == {12, 13, 14, 15, 16, 17, 18}
    assert set(op.modulo(8)) == {0, 1, 2, 4, 5, 6, 7}  # 3 is missing
    validate_numerically(op)

    for _ in range(1):
        op = ConcatenationOperator(
            [
                NullaryOperator(random.randint(0, 1024) for _ in range(random.randint(1, 10)))
                for _ in range(random.randint(1, 10))
            ]
        )
        div = random.randint(1, 64)
        assert set(op.modulo(div)) == {x % div for x in op.expand()}
        validate_numerically(op)

    with pytest.raises(ValueError):
        ConcatenationOperator([])


def _unittest_repetition() -> None:
    from ._symbolic import RepetitionOperator

    op = RepetitionOperator(
        NullaryOperator([7, 11, 17]),
        3,
    )
    assert op.min == 7 * 3
    assert op.max == 17 * 3
    assert set(op.expand()) == set(map(sum, itertools.combinations_with_replacement([7, 11, 17], 3)))
    assert set(op.expand()) == {21, 25, 29, 31, 33, 35, 39, 41, 45, 51}
    assert set(op.modulo(7)) == {0, 1, 2, 3, 4, 5, 6}
    assert set(op.modulo(8)) == {1, 3, 5, 7}
    validate_numerically(op)

    for _ in range(1):
        child = NullaryOperator(random.randint(0, 100) for _ in range(random.randint(1, 10)))
        k = random.randint(0, 10)
        ref = set(map(sum, itertools.combinations_with_replacement(child.expand(), k)))
        op = RepetitionOperator(child, k)
        assert set(op.expand()) == ref

        assert op.min == min(child.expand()) * k
        assert op.max == max(child.expand()) * k

        div = random.randint(1, 64)
        assert set(op.modulo(div)) == {typing.cast(int, x) % div for x in ref}

        validate_numerically(op)


def _unittest_range_repetition() -> None:
    from ._symbolic import RangeRepetitionOperator

    op = RangeRepetitionOperator(
        NullaryOperator([7, 11, 17]),
        3,
    )
    assert op.min == 0  # Always 0
    assert op.max == 17 * 3
    assert set(op.expand()) == (
        {0}
        | set(map(sum, itertools.combinations_with_replacement([7, 11, 17], 1)))
        | set(map(sum, itertools.combinations_with_replacement([7, 11, 17], 2)))
        | set(map(sum, itertools.combinations_with_replacement([7, 11, 17], 3)))
    )
    assert set(op.expand()) == {0, 7, 11, 14, 17, 18, 21, 22, 24, 25, 28, 29, 31, 33, 34, 35, 39, 41, 45, 51}
    assert set(op.modulo(7)) == {0, 1, 2, 3, 4, 5, 6}
    validate_numerically(op)

    op = RangeRepetitionOperator(
        NullaryOperator([7, 11]),
        2,
    )
    assert op.min == 0  # Always 0
    assert op.max == 22
    assert set(op.expand()) == {0, 7, 14, 11, 18, 22}
    assert set(op.modulo(7)) == {0, 1, 4}
    assert set(op.modulo(8)) == {0, 2, 3, 6, 7}
    validate_numerically(op)

    for _ in range(1):
        child = NullaryOperator(random.randint(0, 100) for _ in range(random.randint(1, 10)))
        k_max = random.randint(0, 10)
        ref = set(
            itertools.chain(
                *(map(sum, itertools.combinations_with_replacement(child.expand(), k)) for k in range(k_max + 1))
            )
        )
        op = RangeRepetitionOperator(child, k_max)
        assert set(op.expand()) == ref

        assert op.min == 0
        assert op.max == max(child.expand()) * k_max

        div = random.randint(1, 64)
        assert set(op.modulo(div)) == {typing.cast(int, x) % div for x in ref}

        validate_numerically(op)


def _unittest_union() -> None:
    import pytest
    from ._symbolic import UnionOperator

    op = UnionOperator(
        [
            NullaryOperator([1, 2, 3]),
            NullaryOperator([4, 5, 6]),
            NullaryOperator([7, 8, 9]),
        ]
    )
    assert op.min == 1
    assert op.max == 9
    assert set(op.expand()) == {1, 2, 3, 4, 5, 6, 7, 8, 9}
    assert set(op.modulo(8)) == {x % 8 for x in op.expand()}
    validate_numerically(op)

    op = UnionOperator(
        [
            NullaryOperator([13, 17, 21, 29]),
            NullaryOperator([8, 16]),
        ]
    )
    assert op.min == 8
    assert op.max == 29
    assert set(op.expand()) == {13, 17, 21, 29, 8, 16}
    assert set(op.modulo(7)) == {x % 7 for x in op.expand()}
    assert set(op.modulo(8)) == {x % 8 for x in op.expand()}
    validate_numerically(op)

    for _ in range(1):
        op = UnionOperator(
            [
                NullaryOperator(random.randint(0, 1024) for _ in range(random.randint(1, 10)))
                for _ in range(random.randint(1, 10))
            ]
        )
        validate_numerically(op)

    with pytest.raises(ValueError):
        UnionOperator([])


def _unittest_repr() -> None:
    from ._symbolic import (
        PaddingOperator,
        ConcatenationOperator,
        RepetitionOperator,
        RangeRepetitionOperator,
        UnionOperator,
        MemoizationOperator,
    )

    op = MemoizationOperator(
        UnionOperator(
            [
                PaddingOperator(NullaryOperator([1, 2, 3, 4, 5, 6, 7, 8]), 4),
                ConcatenationOperator(
                    [
                        NullaryOperator([8, 16]),
                        NullaryOperator([96, 112, 120]),
                        RangeRepetitionOperator(NullaryOperator([64]), 8),
                    ]
                ),
                RepetitionOperator(
                    UnionOperator(
                        [
                            NullaryOperator([32]),
                            NullaryOperator([40]),
                        ]
                    ),
                    2,
                ),
            ]
        )
    )
    validate_numerically(op)
    assert repr(op) == "(pad(4,{1,2,3,4,5,6,7,8})|concat({8,16},{96,112,120},repeat(<=8,{64}))|repeat(2,({32}|{40})))"
