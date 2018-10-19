#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import sys
from .version import __version__, __license__


if sys.version_info[:2] < (3, 5):
    print('A newer version of Python is required', file=sys.stderr)
    sys.exit(1)
