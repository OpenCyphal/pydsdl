#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing


def get_unsigned_integer_inclusive_range(bit_length: int) -> typing.Tuple[int, int]:
    """
    :param bit_length: bit size of the integer; must be in [1, 64]
    :return: a tuple containing the minimum and the maximum attainable values
    """
    if not 1 <= bit_length <= 64:
        raise ValueError('Invalid bit length for unsigned integer type: %d' % bit_length)

    return 0, (1 << bit_length) - 1


def get_signed_integer_inclusive_range(bit_length: int) -> typing.Tuple[int, int]:
    """
    :param bit_length: bit size of the integer; must be in [1, 64]
    :return: a tuple containing the minimum and the maximum attainable values
    """
    if not 2 <= bit_length <= 64:
        raise ValueError('Invalid bit length for signed integer type: %d' % bit_length)

    _, uint_max = get_unsigned_integer_inclusive_range(bit_length)
    return -int(uint_max // 2) - 1, int(uint_max // 2)


def get_float_inclusive_range(bit_length: int) -> typing.Tuple[float, float]:
    """
    :param bit_length: bit size of the float, assuming IEEE754; must be in {16, 32, 64}
    :return: a tuple containing the minimum and the maximum attainable values
    """
    try:
        max_value = {
            16: 65504.0,
            32: 3.40282346638528859812e+38,
            64: 1.79769313486231570815e+308
        }[bit_length]
    except KeyError:
        raise ValueError('Invalid bit length for float type: %d' % bit_length)

    return -max_value, max_value


def _unittest_type_limits():
    try:
        get_unsigned_integer_inclusive_range(0)
        assert False
    except ValueError:
        pass
    try:
        get_signed_integer_inclusive_range(65)
        assert False
    except ValueError:
        pass
    try:
        get_signed_integer_inclusive_range(1)
        assert False
    except ValueError:
        pass
    try:
        get_float_inclusive_range(11)
        assert False
    except ValueError:
        pass

    assert (0, 1) == get_unsigned_integer_inclusive_range(1)
    assert (0, 3) == get_unsigned_integer_inclusive_range(2)
    assert (0, 31) == get_unsigned_integer_inclusive_range(5)
    assert (0, 0xFFFF_FFFF_FFFF_FFFF) == get_unsigned_integer_inclusive_range(64)

    assert (-2, 1) == get_signed_integer_inclusive_range(2)
    assert (-16, 15) == get_signed_integer_inclusive_range(5)
    assert (-128, 127) == get_signed_integer_inclusive_range(8)

    assert -65505 < get_float_inclusive_range(16)[0] < -65503
    assert +65503 < get_float_inclusive_range(16)[1] < +65505
