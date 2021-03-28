# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

# pylint: disable=consider-using-in,protected-access,too-many-statements

import fractions
from . import _any, _primitive, _container, _operator


# noinspection PyUnresolvedReferences,PyTypeChecker
def _unittest_expressions() -> None:
    r = _primitive.Rational
    s = _primitive.String

    for a in (True, False):
        for b in (True, False):
            assert _primitive.Boolean(a).native_value == a
            assert _operator.logical_not(_primitive.Boolean(a)).native_value == (not a)
            assert _operator.logical_and(_primitive.Boolean(a), _primitive.Boolean(b)).native_value == (a and b)
            assert _operator.logical_or(_primitive.Boolean(a), _primitive.Boolean(b)).native_value == (a or b)

    assert _operator.equal(
        _operator.divide(_operator.multiply(_operator.add(r(2), r(2)), r(3)), r(5)), r(fractions.Fraction(12, 5))
    ).native_value

    assert _operator.add(s("123"), s("abc")).native_value == "123abc"  # type: ignore

    new_set = _operator.add(_container.Set([s("123"), s("456")]), s("abc"))
    assert set(new_set) == {s("123abc"), s("456abc")}  # type: ignore

    new_set = _operator.add(s("abc"), _container.Set([s("123"), s("456")]))
    assert set(new_set) == {s("abc123"), s("abc456")}  # type: ignore

    new_set = _operator.add(
        s("abc"), _container.Set([_container.Set([s("123"), s("456")]), _container.Set([s("789"), s("987")])])
    )
    assert new_set == _container.Set(
        [_container.Set([s("abc123"), s("abc456")]), _container.Set([s("abc789"), s("abc987")])]
    )

    assert _operator.attribute(_container.Set([r(1), r(2), r(3), r(-4), r(-5)]), s("min")) == r(-5)
    assert _operator.attribute(_container.Set([r(1), r(2), r(3), r(-4), r(-5)]), s("max")) == r(3)


def _unittest_textual_representations() -> None:
    assert str(_primitive.Rational(fractions.Fraction(123, 456))) == "41/152"
    assert repr(_primitive.Rational(fractions.Fraction(123, 456))) == "rational(41/152)"
    assert str(_primitive.Rational(-123)) == "-123"
    assert repr(_primitive.Rational(-123)) == "rational(-123)"

    assert str(_primitive.Boolean(True)) == "true"
    assert repr(_primitive.Boolean(False)) == "bool(false)"

    assert str(_primitive.String("Hello\nworld!")) == r"'Hello\nworld!'"
    assert repr(_primitive.String("Hello\nworld!")) == r"string('Hello\nworld!')"

    tmp = str(_container.Set([_primitive.Rational(1), _primitive.Rational(fractions.Fraction(-9, 7))]))
    assert tmp == "{1, -9/7}" or tmp == "{-9/7, 1}"

    tmp = repr(_container.Set([_primitive.Rational(1), _primitive.Rational(fractions.Fraction(-9, 7))]))
    assert tmp == "set({1, -9/7})" or tmp == "set({-9/7, 1})"

    tmp = str(
        _container.Set(
            [
                _container.Set([_primitive.Rational(1), _primitive.Rational(fractions.Fraction(-9, 7))]),
                _container.Set([_primitive.Rational(fractions.Fraction(90, 7))]),
            ]
        )
    )
    assert (
        tmp == "{{1, -9/7}, {90/7}}"
        or tmp == "{{-9/7, 1}, {90/7}}"
        or tmp == "{{90/7}, {-9/7, 1}}"
        or tmp == "{{90/7}, {1, -9/7}}"
    )

    assert repr(_container.Set([_primitive.String("123")])) == "set({'123'})"


# noinspection PyTypeChecker
def _unittest_basic() -> None:
    from pytest import raises

    assert hash(_primitive.Boolean(True)) == hash(True)
    assert _primitive.Boolean(True) == _primitive.Boolean(True)
    assert _primitive.Boolean(True) != _primitive.Boolean(False)
    assert _primitive.Boolean(True) != _primitive.Rational(1)  # sic!
    assert _primitive.Boolean(True) != _primitive.Rational(123)
    assert _primitive.Boolean(True) != _container.Set([_primitive.Boolean(True)])

    with raises(ValueError):
        _primitive.Boolean(int)  # type: ignore

    with raises(ValueError):
        _primitive.Rational({123})  # type: ignore

    with raises(ValueError):
        _primitive.Rational("123")  # type: ignore

    with raises(ValueError):
        _primitive.String(123)  # type: ignore

    with raises(ValueError):
        _container.Set([123])  # type: ignore

    assert _primitive.Rational(123).is_integer()
    assert not _primitive.Rational(fractions.Fraction(123, 124)).is_integer()
    assert _primitive.Rational(-123).as_native_integer() == -123
    with raises(_any.InvalidOperandError):
        _primitive.Rational(fractions.Fraction(123, 124)).as_native_integer()
