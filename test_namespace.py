#!/usr/bin/env python3
#
# This is a helper script used for testing the parser against a specified namespace directory.
# It just directly invokes the corresponding API, prints the output, and exits.
#

import sys
import pydsdl

target_directory = sys.argv[1]
lookup_directories = sys.argv[2:]

try:
    compound_types = pydsdl.read_namespace(target_directory, lookup_directories, print)
except pydsdl.InvalidDefinitionError as ex:
    print(ex, file=sys.stderr)                      # The DSDL definition is invalid
except pydsdl.InternalError as ex:
    print('Internal error:', ex, file=sys.stderr)   # Oops! Please report.
else:
    for t in compound_types:
        if isinstance(t, pydsdl.ServiceType):
            blr, blv = 0, {0}
        else:
            blr, blv = t.bit_length_range, t.compute_bit_length_values()
        # The above is because service types are not directly serializable (see the UAVCAN specification)
        print(t.full_name, t.version, t.fixed_port_id, t.deprecated, blr, len(blv))
        for f in t.fields:
            print('\t', str(f.data_type), f.name)
        for c in t.constants:
            print('\t', str(c.data_type), c.name, '=', str(c.value.native_value))
