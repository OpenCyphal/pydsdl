#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import sys

if sys.version_info[:2] < (3, 5):   # pragma: no cover
    print('A newer version of Python is required', file=sys.stderr)
    sys.exit(1)

# Our unorthodox approach to dependency management requires us to apply certain workarounds.
# Here, the objective is to allow our library to import stuff from its third-party dependency directory,
# but at the same time we don't want to interfere with the application that depends on this library.
# So we modify the import lookup path temporarily while the package initialization is in progress;
# when done, we restore the path back to its original value. One implication is that it won't be possbile
# to import stuff dynamically after the initialization is finished (e.g., function-local imports won't be
# able to reach the third-party stuff), but we don't care.
_original_sys_path = sys.path
sys.path = [os.path.join(os.path.dirname(__file__), 'third_party')] + sys.path

# Never import anything that is not exposed here - API stability guarantees are only provided for the exposed items.
from .version import __version__, __license__       # noqa
from .namespace_parser import parse_namespace       # noqa
from . import data_type                             # noqa
from . import frontend_error                        # noqa
from . import _non_intrusive_test as _              # noqa This is only needed for testing purposes

sys.path = _original_sys_path
