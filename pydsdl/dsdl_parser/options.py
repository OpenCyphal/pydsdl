#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
from ..dsdl_definition import DSDLDefinition

# Arguments: emitting definition, line number, value to print
# The lines are numbered starting from one
PrintDirectiveOutputHandler = typing.Callable[[DSDLDefinition, int, typing.Any], None]


class ConfigurationOptions:
    def __init__(self) -> None:
        self.print_handler = None                       # type: typing.Optional[PrintDirectiveOutputHandler]
        self.allow_unregulated_fixed_port_id = False
        self.skip_assertion_checks = False
