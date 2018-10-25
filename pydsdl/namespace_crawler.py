#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
import logging
import fnmatch
from .data_type import CompoundType, ServiceType
from .dsdl_definition import DSDLDefinition
from .parser import parse_definition
from .error import ParseError, InternalError, FileNameFormatError
from .error import RegulatedPortIDCollisionError, NamespaceNameCollisionError, NestedRootNamespaceError


DSDL_FILE_GLOB = '*.uavcan'


_logger = logging.getLogger(__name__)
_LOG_LIST_ITEM_PREFIX = ' ' * 4


def parse_namespace(root_namespace_directory: str,
                    lookup_directories: typing.Iterable[str]) -> typing.List[CompoundType]:
    """
    Parse all DSDL definitions in the specified root namespace directory.

    :param root_namespace_directory:    The path of the root namespace directory that will be parsed.
                                        For example, "dsdl/uavcan" to parse the "uavcan" namespace.

    :param lookup_directories:          List of other namespace directories containing data type definitions that are
                                        referred to from the parsed root namespace. For example, if you are parsing a
                                        vendor-specific namespace, the list of lookup directories should always include
                                        a path to the standard root namespace "uavcan", otherwise the types defined in
                                        the vendor-specific namespace won't be able to use data types from the standard
                                        namespace.

    :return: A list of CompoundType.

    :raises: ParseError
    """
    # Add the own root namespace to the set of lookup directories, remove duplicates
    lookup_directories = list(set(list(lookup_directories) + [root_namespace_directory]))

    # Normalize paths
    root_namespace_directory = os.path.abspath(root_namespace_directory)
    lookup_directories = list(map(lambda d: str(os.path.abspath(d)), lookup_directories))
    _logger.info('Lookup directories are listed below:')
    for a in lookup_directories:
        _logger.info(_LOG_LIST_ITEM_PREFIX + a)

    # Check the namespaces
    _ensure_no_nested_root_namespaces(lookup_directories)
    _ensure_no_namespace_name_collisions(lookup_directories)

    # Construct DSDL definitions from the target and the lookup dirs
    target_dsdl_definitions = _construct_dsdl_definitions_from_namespace(root_namespace_directory)
    _logger.debug('Target DSDL definitions are listed below:')
    for x in target_dsdl_definitions:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(x))

    lookup_dsdl_definitions = []    # type: typing.List[DSDLDefinition]
    for ld in lookup_directories:
        lookup_dsdl_definitions += _construct_dsdl_definitions_from_namespace(ld)

    _logger.debug('Lookup DSDL definitions are listed below:')
    for x in lookup_dsdl_definitions:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(x))

    # Parse the constructed definitions
    types = _parse_namespace_definitions(target_dsdl_definitions, lookup_dsdl_definitions)

    # Note that we check for collisions in the parsed namespace only.
    # We intentionally ignore (do not check for) possible collisions in the lookup directories,
    # because that would exceed the expected scope of responsibility of the parser, and the lookup
    # directories may contain issues and mistakes that are outside of the control of the user (e.g.,
    # they could be managed by a third party) -- the user shouldn't be affected by mistakes committed
    # by the third party.
    _ensure_no_regulated_port_id_collisions(types)

    return types


def _parse_namespace_definitions(target_definitions: typing.List[DSDLDefinition],
                                 lookup_definitions: typing.List[DSDLDefinition]) -> typing.List[CompoundType]:
    """
    Construct type descriptors from the specified target definitions.
    Allow the target definitions to use the lookup definitions within themselves.
    :param target_definitions:  Which definitions to parse.
    :param lookup_definitions:  Which definitions can be used by the parsed definitions.
    :return: A list of types.
    """
    types = []  # type: typing.List[CompoundType]
    for tdd in target_definitions:
        try:
            parsed = parse_definition(tdd, lookup_definitions)
        except ParseError as ex:
            ex.set_error_location_if_unknown(path=tdd.file_path)
            raise ex
        except Exception as ex:
            raise InternalError(culprit=ex, path=tdd.file_path) from ex
        else:
            types.append(parsed)

    return types


def _ensure_no_regulated_port_id_collisions(types: typing.List[CompoundType]) -> None:
    """
    Simply raises a RegulatedPortIDCollisionError if at least two types of the same kind (messages/services
    are orthogonal) use the same regulated port ID.
    """
    for a in types:
        for b in types:
            if a.name != b.name:
                if isinstance(a, ServiceType) == isinstance(b, ServiceType):
                    if a.has_regulated_port_id and b.has_regulated_port_id:
                        if a.regulated_port_id == b.regulated_port_id:
                            # TODO: IMPLEMENT THE PATH EXTRACTION LOGIC
                            raise RegulatedPortIDCollisionError(path='FIXME PLEASE', colliding_paths=[])


def _ensure_no_nested_root_namespaces(directories: typing.Iterable[str]) -> None:
    """
    Simply raises a NestedRootNamespaceError if one root namespace contains another one.
    """
    directories = list(sorted([str(os.path.abspath(x)) for x in set(directories)]))
    for a in directories:
        for b in directories:
            if (a != b) and a.startswith(b):
                raise NestedRootNamespaceError(outer_path=b, nested_paths=[a])


def _ensure_no_namespace_name_collisions(directories: typing.Iterable[str]) -> None:
    """
    Simply raises a NamespaceNameCollisionError if at least two namespaces share the same name.
    The same directory can be listed several times without causing any errors.
    """
    def get_namespace_name(d: str) -> str:
        return os.path.split(d)[-1]

    directories = list(sorted([str(os.path.abspath(x)) for x in set(directories)]))
    for a in directories:
        for b in directories:
            if (a != b) and get_namespace_name(a) == get_namespace_name(b):
                raise NamespaceNameCollisionError(path=a, colliding_paths=b)


def _construct_dsdl_definitions_from_namespace(root_namespace_path: str) -> typing.List[DSDLDefinition]:
    """
    Accepts a directory path, returns a list of abstract DSDL file representations.
    Those can be fed to the actual DSDL parser later.
    """
    def on_walk_error(os_ex: OSError) -> None:
        raise os_ex     # pragma: no cover

    walker = os.walk(root_namespace_path,
                     onerror=on_walk_error,
                     followlinks=True)

    source_file_paths = []  # type: typing.List[str]
    for root, _dirnames, filenames in walker:
        for filename in fnmatch.filter(filenames, DSDL_FILE_GLOB):
            source_file_paths.append(os.path.join(root, filename))

    _logger.info('DSDL files in the namespace dir %r are listed below:', root_namespace_path)
    for a in source_file_paths:
        _logger.info(_LOG_LIST_ITEM_PREFIX + a)

    output = []  # type: typing.List[DSDLDefinition]
    for fp in source_file_paths:
        dsdl_def = DSDLDefinition(fp, root_namespace_path)
        output.append(dsdl_def)

    return output


def _unittest_parse_namespace_faults() -> None:
    try:
        parse_namespace('/foo/bar/baz', ['/bat/wot', '/foo/bar/baz/bad'])
    except NestedRootNamespaceError as ex:
        print(ex)
    else:               # pragma: no cover
        assert False

    try:
        parse_namespace('/foo/bar/baz', ['/foo/bar/zoo', '/foo/bar/doo/roo/baz'])
    except NamespaceNameCollisionError as ex:
        print(ex)
    else:               # pragma: no cover
        assert False
    try:
        parse_namespace('/foo/bar/baz', ['/foo/bar/zoo', '/foo/bar/doo/roo/zoo', '/foo/bar/doo/roo/baz'])
    except NamespaceNameCollisionError as ex:
        print(ex)
    else:               # pragma: no cover
        assert False


def _unittest_dsdl_definition_constructor() -> None:
    import tempfile

    directory = tempfile.TemporaryDirectory()
    root_ns_dir = os.path.join(directory.name, 'foo')

    os.mkdir(root_ns_dir)
    os.mkdir(os.path.join(root_ns_dir, 'nested'))

    def touchy(relative_path: str) -> None:
        with open(os.path.join(root_ns_dir, relative_path), 'w') as f:
            f.write('# TEST TEXT')

    def discard(relative_path: str) -> None:
        os.unlink(os.path.join(root_ns_dir, relative_path))

    touchy('123.Qwerty.123.234.uavcan')
    touchy('nested/2.Asd.21.32.uavcan')
    touchy('nested/Foo.32.43.uavcan')

    dsdl_defs = _construct_dsdl_definitions_from_namespace(root_ns_dir)
    print(dsdl_defs)
    lut = {x.name: x for x in dsdl_defs}    # type: typing.Dict[str, DSDLDefinition]
    assert len(lut) == 3

    assert str(lut['foo.Qwerty']) == repr(lut['foo.Qwerty'])
    assert str(lut['foo.Qwerty']) == \
        "DSDLDefinition(name='foo.Qwerty', version=Version(major=123, minor=234), regulated_port_id=123, " \
        "file_path='%s')" % lut['foo.Qwerty'].file_path

    assert str(lut['foo.nested.Foo']) == \
        "DSDLDefinition(name='foo.nested.Foo', version=Version(major=32, minor=43), regulated_port_id=None, " \
        "file_path='%s')" % lut['foo.nested.Foo'].file_path

    t = lut['foo.Qwerty']
    assert t.file_path == os.path.join(root_ns_dir, '123.Qwerty.123.234.uavcan')
    assert t.has_regulated_port_id
    assert t.regulated_port_id == 123
    assert t.text == '# TEST TEXT'
    assert t.version.major == 123
    assert t.version.minor == 234
    assert t.name_components == ['foo', 'Qwerty']
    assert t.short_name == 'Qwerty'
    assert t.root_namespace == 'foo'
    assert t.namespace == 'foo'

    t = lut['foo.nested.Asd']
    assert t.file_path == os.path.join(root_ns_dir, 'nested', '2.Asd.21.32.uavcan')
    assert t.has_regulated_port_id
    assert t.regulated_port_id == 2
    assert t.text == '# TEST TEXT'
    assert t.version.major == 21
    assert t.version.minor == 32
    assert t.name_components == ['foo', 'nested', 'Asd']
    assert t.short_name == 'Asd'
    assert t.root_namespace == 'foo'
    assert t.namespace == 'foo.nested'

    t = lut['foo.nested.Foo']
    assert t.file_path == os.path.join(root_ns_dir, 'nested', 'Foo.32.43.uavcan')
    assert not t.has_regulated_port_id
    assert t.regulated_port_id is None
    assert t.text == '# TEST TEXT'
    assert t.version.major == 32
    assert t.version.minor == 43
    assert t.name_components == ['foo', 'nested', 'Foo']
    assert t.short_name == 'Foo'
    assert t.root_namespace == 'foo'
    assert t.namespace == 'foo.nested'

    touchy('nested/Malformed.MAJOR.MINOR.uavcan')
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
        discard('nested/Malformed.MAJOR.MINOR.uavcan')
    else:       # pragma: no cover
        assert False

    touchy('nested/NOT_A_NUMBER.Malformed.1.0.uavcan')
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
        discard('nested/NOT_A_NUMBER.Malformed.1.0.uavcan')
    else:       # pragma: no cover
        assert False

    touchy('nested/Malformed.uavcan')
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
        discard('nested/Malformed.uavcan')
    else:       # pragma: no cover
        assert False
