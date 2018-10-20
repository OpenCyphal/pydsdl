#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import enum


class DataTypeOrigin(enum.Enum):
    STANDARD = 0
    VENDOR   = 1


class DataTypeKind(enum.Enum):
    SERVICE = 0
    MESSAGE = 1
