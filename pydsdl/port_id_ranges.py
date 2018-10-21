#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

from .communication_primitive import CommunicationPrimitiveKind as Kind, CommunicationPrimitiveOrigin as Origin


_STANDARD_MESSAGES = 62804, 65535
_VENDOR_MESSAGES   = 57344, 59391

_STANDARD_SERVICES = 384, 511
_VENDOR_SERVICES   = 256, 319


def is_valid_regulated_port_id(regulated_id: int,
                               kind: Kind,
                               origin: Origin) -> bool:
    """
    Evaluates the provided regulated port ID against valid ranges defined by the protocol specification.
    Returns true if the value is within the range dedicated for its category, false otherwise.
    :param regulated_id:    The port ID to check.
    :param kind:            The kind of the data type, either service or message.
    :param origin:          The source of the data type, either vendor or the standard.
    :return:                True if valid, False otherwise.
    """
    try:
        applicable_range = {
            (Kind.MESSAGE, Origin.STANDARD): _STANDARD_MESSAGES,
            (Kind.MESSAGE, Origin.VENDOR):   _VENDOR_MESSAGES,
            (Kind.SERVICE, Origin.STANDARD): _STANDARD_SERVICES,
            (Kind.SERVICE, Origin.VENDOR):   _VENDOR_SERVICES,
        }[(kind, origin)]
    except KeyError:
        raise ValueError('Invalid type category specifiers: %r, %r' % (kind, origin)) from None

    return applicable_range[0] <= int(regulated_id) <= applicable_range[1]
