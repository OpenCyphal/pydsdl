#!/usr/bin/env python3
#
# This is a helper script used for testing the parser against a specified namespace directory.
# It just directly invokes the corresponding API, prints the output, and exits.
#

import sys
import time
import pydsdl
import logging

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(levelname)-8s %(message)s')

target_directory = sys.argv[1]
lookup_directories = sys.argv[2:]


def _print_handler(file: str, line: int, text: str) -> None:
    print('%s:%d:' % (file, line), text)


def _show_fields(t: pydsdl.CompositeType) -> None:
    pass


def _main():
    try:
        started_at = time.monotonic()
        compound_types = pydsdl.read_namespace(target_directory, lookup_directories, _print_handler)
        done_at = time.monotonic()
    except pydsdl.InvalidDefinitionError as ex:
        print(ex, file=sys.stderr)                      # The DSDL definition is invalid.
    except pydsdl.InternalError as ex:
        print('Internal error:', ex, file=sys.stderr)   # Oops! Please report.
    else:
        for t in compound_types:
            # Service types are not directly serializable (see the UAVCAN specification)
            bls = pydsdl.BitLengthSet() if isinstance(t, pydsdl.ServiceType) else t.bit_length_set
            print(t.full_name, t.version, t.fixed_port_id, t.deprecated, len(bls))
            for f in t.fields:
                print('\t', str(f.data_type), f.name)
            for c in t.constants:
                print('\t', str(c.data_type), c.name, '=', str(c.value.native_value))

        print('%d types parsed in %.1f seconds' % (len(compound_types), done_at - started_at))


_main()
