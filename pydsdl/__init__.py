#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import sys
from .version import __version__, __license__
from . import _non_intrusive_test
from .namespace_parser import parse_namespace
from . import data_type
from . import parse_error


if sys.version_info[:2] < (3, 5):   # pragma: no cover
    print('A newer version of Python is required', file=sys.stderr)
    sys.exit(1)
