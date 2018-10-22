#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
import logging
from .data_type import CompoundType
from .parser_error import ParserError


_logger = logging.getLogger(__name__)


def parse_namespace(root_namespace_directory: str,
                    lookup_directories: typing.List[str]) -> typing.List[CompoundType]:
    # Add the own root namespace to the set of lookup directories, remove duplicates
    lookup_directories = list(set(lookup_directories + [root_namespace_directory]))

    # Normalize lookup paths
    lookup_directories = list(map(lambda d: str(os.path.abspath(d)), lookup_directories))

    _logger.info('Root namespace directory: %s', root_namespace_directory)
    _logger.info('Lookup directories are listed below:')
    for a in lookup_directories:
        _logger.info(' ' * 4 + a)

    # Ensure that no lookup directory is a sub-directory of another one
    for a in lookup_directories:
        for b in lookup_directories:
            if (a is not b) and a.startswith(b):
                raise ParserError('This look-up path is nested within another lookup path, which is not permitted. '
                                  'The outer path is %r' % b,
                                  path=a)

    return []


def _unittest_parse_namespace_nested_directories() -> None:
    try:
        parse_namespace('/foo/bar/baz', ['/bat/wot', '/foo/bar/baz/bad'])
    except ParserError as ex:
        print(ex)
    else:
        assert False
