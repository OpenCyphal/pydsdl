#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

from .data_type_categories import DataTypeKind, DataTypeOrigin


_STANDARD_MESSAGES = 62804, 65535
_VENDOR_MESSAGES   = 57344, 59391

_STANDARD_SERVICES = 384, 511
_VENDOR_SERVICES   = 256, 319


def is_valid_regulated_id(regulated_id: int, kind: DataTypeKind, origin: DataTypeOrigin) -> bool:
    """
    Evaluates the provided regulated data type ID against valid ranges defined by the protocol specification.
    Returns true if the value is within the range dedicated for its category, false otherwise.
    :param regulated_id:    The data type ID to check.
    :param kind:            The kind of the data type, either service or message.
    :param origin:          The source of the data type, either vendor or the standard.
    :return:                True if valid, False otherwise.
    """
    try:
        applicable_range = {
            (DataTypeKind.MESSAGE, DataTypeOrigin.STANDARD): _STANDARD_MESSAGES,
            (DataTypeKind.MESSAGE, DataTypeOrigin.VENDOR):   _VENDOR_MESSAGES,
            (DataTypeKind.SERVICE, DataTypeOrigin.STANDARD): _STANDARD_SERVICES,
            (DataTypeKind.SERVICE, DataTypeOrigin.VENDOR):   _VENDOR_SERVICES,
        }[(kind, origin)]
    except KeyError:
        raise ValueError('Invalid type category specifiers: %r, %r' % (kind, origin)) from None

    return applicable_range[0] <= int(regulated_id) <= applicable_range[1]
