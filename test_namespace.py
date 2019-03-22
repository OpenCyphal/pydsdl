#!/usr/bin/env python3
#
# This is a helper script used for testing the parser against a specified namespace directory.
# It just directly invokes the corresponding API, prints the output, and exits.
#

import sys
import pydsdl

target_directory = sys.argv[1]
lookup_directories = sys.argv[2:]

output = pydsdl.read_namespace(target_directory, lookup_directories)

print('\n'.join(map(str, output)))
