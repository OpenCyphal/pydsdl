# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import random
from ._symbolic import NullaryOperator, PaddingOperator, ConcatenationOperator


def _unittest_nullary() -> None:
    op = NullaryOperator([])
    assert set(op.expand()) == {0}
    assert set(op.modulo(12345)) == {0}
    assert op.min == op.max == 0

    op = NullaryOperator([1, 2, 3, 4, 5, 6, 7, 8])
    assert set(op.expand()) == {1, 2, 3, 4, 5, 6, 7, 8}
    assert set(op.modulo(4)) == {0, 1, 2, 3}
    assert (op.min, op.max) == (1, 8)


def _unittest_padding() -> None:
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

    assert set(x % 6 for x in op.expand()) == {0, 2, 4}  # Reference
    assert set(op.modulo(6)) == {0, 2, 4}

    assert set(x % 7 for x in op.expand()) == {1, 4, 5}  # Reference
    assert set(op.modulo(7)) == {1, 4, 5}

    for _ in range(10_000):
        child = NullaryOperator(random.randint(0, 1024) for _ in range(random.randint(0, 100)))
        alignment = random.randint(1, 64)
        op = PaddingOperator(child, alignment)
        bl = random.randint(1, 64)
        assert set(op.modulo(bl)) == {x % bl for x in op.expand()}


def _unittest_concatenation() -> None:
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

    for _ in range(100):
        op = ConcatenationOperator(
            [
                NullaryOperator(random.randint(0, 1024) for _ in range(random.randint(0, 10)))
                for _ in range(random.randint(1, 10))
            ]
        )
        bl = random.randint(1, 64)
        assert set(op.modulo(bl)) == {x % bl for x in op.expand()}
