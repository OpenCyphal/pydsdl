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


def _show_fields(indent_level: int,
                 field_prefix: str,
                 t: pydsdl.CompositeType,
                 base_offset: pydsdl.BitLengthSet) -> None:
    # This function is intended to be a crude demonstration of how the static bit layout analysis can be leveraged
    # to generate very efficient serialization and deserialization routines. With PyDSDL it is possible to determine
    # whether any given field at an arbitrary level of nesting always meets a certain alignment goal. This information
    # allows the code generator to choose the most efficient serialization/deserialization strategy. For example:
    #
    #   - If every field of a data structure is a standard-bit-length field (e.g., uint64) and its offset meets the
    #     native alignment requirement, the whole structure can be serialized and deserialized by simple memcpy().
    #     We call it "zero-cost serialization".
    #
    #   - Otherwise, if a field is standard-bit-length and its offset is always a multiple of eight bits, the field
    #     itself can be serialized by memcpy(). This case differs from the above in that the whole structure may not
    #     be zero-cost-serializable, but some or all of its fields still may be.
    #
    #  - Various other optimizations are possible depending on whether the bit length of a field is a multiple of
    #    eight bits and/or whether its base offset is byte-aligned. Many optimization possibilities depend on a
    #    particular programming language and platform, so they will not be reviewed here in detail. Interested readers
    #    are advised to consult with existing implementations.
    #
    #  - In the worst case, if none of the possible optimizations are discoverable statically, the code generator will
    #    resort to bit-level serialization, where a field is serialized/deserialized bit-by-bit. Such fields are
    #    extremely uncommon, and a data type designer can easily ensure that their data type definitions are free from
    #    such fields by using @assert expressions checking against _offset_. More info in the specification.
    #
    # The key part of static layout analysis is the class pydsdl.BitLengthSet; please read its documentation.
    indent = ' ' * indent_level * 4
    for field, offset in t.iterate_fields_with_offsets(base_offset):
        field_type = field.data_type
        prefixed_name = '.'.join(filter(None, [field_prefix, field.name or '(padding)']))

        if isinstance(field_type, pydsdl.PrimitiveType):
            print(indent, prefixed_name, '# byte-aligned: %s; standard bit length: %s; standard-aligned: %s' %
                  (offset.is_aligned_at_byte(),
                   field_type.standard_bit_length,
                   field_type.standard_bit_length and offset.is_aligned_at(field_type.bit_length)))

        elif isinstance(field_type, pydsdl.VoidType):
            print(indent, prefixed_name)

        elif isinstance(field_type, pydsdl.VariableLengthArrayType):
            offset_of_every_element = offset + field_type.bit_length_set  # All possible element offsets for this array
            print(indent, prefixed_name, '# length field is byte-aligned: %s; every element is byte-aligned: %s' %
                  (offset.is_aligned_at_byte(), offset_of_every_element.is_aligned_at_byte()))

        elif isinstance(field_type, pydsdl.FixedLengthArrayType):
            for index, element_offset in field_type.enumerate_elements_with_offsets(offset):
                # Real implementations would recurse; this is not shown in this demo for compactness.
                print(indent, prefixed_name + '[%d]' % index, '# byte-aligned:', element_offset.is_aligned_at_byte())

        elif isinstance(field_type, pydsdl.CompositeType):
            print(indent, str(field) + ':')
            _show_fields(indent_level + 1, prefixed_name, field_type, offset)

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
            if isinstance(t, pydsdl.ServiceType):
                print(t, 'request:')
                _show_fields(1, 'request', t.request_type, pydsdl.BitLengthSet())
                print(t, 'response:')
                _show_fields(1, 'response', t.response_type, pydsdl.BitLengthSet())
            else:
                print(t, ':', sep='')
                _show_fields(1, '', t, pydsdl.BitLengthSet())
            print()

        print('%d types parsed in %.1f seconds' % (len(compound_types), time.monotonic() - started_at))


_main()
