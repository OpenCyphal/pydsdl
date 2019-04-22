#!/usr/bin/env python3
#
# This is a helper script used for testing the parser against a specified namespace directory.
# It just directly invokes the corresponding API, prints the output, and exits.
#

import sys
import time
import math
import pydsdl
import logging

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(levelname)-8s %(message)s')

target_directory = sys.argv[1]
lookup_directories = sys.argv[2:]


def _print_handler(file: str, line: int, text: str) -> None:
    print('%s:%d:' % (file, line), text)


def _show_fields(field_prefix: str, t: pydsdl.CompositeType, base_offset: pydsdl.BitLengthSet) -> None:
    for field, offset in t.iterate_fields_with_offsets(base_offset):
        field_type = field.data_type
        prefixed_name = '.'.join(filter(None, [field_prefix, field.name or '(padding)']))

        if isinstance(field_type, pydsdl.PrimitiveType):
            print('\t', prefixed_name, '# byte-aligned: %s; standard size: %s; standard-aligned: %s' %
                  (offset.is_aligned_at_byte(),
                   field_type.standard_length,
                   field_type.standard_length and offset.is_aligned_at(field_type.bit_length)))

        elif isinstance(field_type, pydsdl.VoidType):
            print('\t', prefixed_name)

        elif isinstance(field_type, pydsdl.VariableLengthArrayType):
            first_element_offset = offset + field_type.length_field_bit_length
            element_length = field_type.element_type.bit_length_set
            all_elements_byte_aligned = \
                first_element_offset.is_aligned_at_byte() and element_length.is_aligned_at_byte()
            print('\t', prefixed_name, '# length field is byte-aligned: %s; all elements are byte-aligned: %s' %
                  (offset.is_aligned_at_byte(), all_elements_byte_aligned))

        elif isinstance(field_type, pydsdl.FixedLengthArrayType):
            element_length = field_type.element_type.bit_length_set
            print('\t', prefixed_name, '# all elements are byte-aligned:',
                  offset.is_aligned_at_byte() and element_length.is_aligned_at_byte())

        elif isinstance(field_type, pydsdl.CompositeType):
            print('\t', '# unrolling a composite field', field)
            _show_fields(prefixed_name, field_type, offset)
            print('\t', '# end of unrolled composite field', field)

        else:
            raise RuntimeError('Unhandled type: %r' % field_type)


def _main():
    try:
        started_at = time.monotonic()
        compound_types = pydsdl.read_namespace(target_directory, lookup_directories, _print_handler)
    except pydsdl.InvalidDefinitionError as ex:
        print(ex, file=sys.stderr)                      # The DSDL definition is invalid.
    except pydsdl.InternalError as ex:
        print('Internal error:', ex, file=sys.stderr)   # Oops! Please report.
    else:
        for t in compound_types:
            # Service types are not directly serializable (see the UAVCAN specification)
            if isinstance(t, pydsdl.ServiceType):
                print(t, 'request:')
                _show_fields('request', t.request_type, pydsdl.BitLengthSet())
                print(t, 'response:')
                _show_fields('response', t.response_type, pydsdl.BitLengthSet())
            else:
                print(t, ':', sep='')
                _show_fields('', t, pydsdl.BitLengthSet())
            print()

        print('%d types parsed in %.1f seconds' % (len(compound_types), time.monotonic() - started_at))


_main()
