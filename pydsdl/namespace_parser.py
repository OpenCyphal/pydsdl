#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
import logging
import fnmatch
from collections import defaultdict
from .data_type import CompoundType, ServiceType
from .dsdl_definition import DSDLDefinition
from .dsdl_parser import parse_definition, PrintDirectiveOutputHandler
from .parse_error import ParseError, InternalError, InvalidDefinitionError


DSDL_FILE_GLOB = '*.uavcan'


_logger = logging.getLogger(__name__)
_LOG_LIST_ITEM_PREFIX = ' ' * 4


class NamespaceNameCollisionError(InvalidDefinitionError):
    """
    Raised when there is more than one namespace under the same name.
    This may occur if there are identically named namespaces located in different directories.
    """
    pass


class NestedRootNamespaceError(InvalidDefinitionError):
    """
    Nested root namespaces are not allowed. This exception is thrown when this rule is violated.
    """
    pass


class RegulatedPortIDCollisionError(InvalidDefinitionError):
    """
    Raised when there is more than one data type, or different major versions of the same data type
    using the same regulated port ID.
    """
    pass


class MinorVersionsNotBitCompatibleError(InvalidDefinitionError):
    """
    Raised when definitions under the same major version are not bit-compatible.
    """
    pass


class MultipleDefinitionsUnderSameVersionError(InvalidDefinitionError):
    """
    For example:
        Type.1.0.uavcan
        58000.Type.1.0.uavcan
        58001.Type.1.0.uavcan
    """
    pass


class VersionsOfDifferentKindError(InvalidDefinitionError):
    """
    Definitions that share the same name but are of different kinds.
    """
    pass


class MinorVersionRegulatedPortIDError(InvalidDefinitionError):
    """
    Different regulated port ID under the same major version, or a regulated port ID was removed under the same
    major version.
    """
    pass


def parse_namespace(root_namespace_directory:       str,
                    lookup_directories:             typing.Iterable[str],
                    print_directive_output_handler: typing.Optional[PrintDirectiveOutputHandler]=None) -> \
        typing.List[CompoundType]:
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

    :param print_directive_output_handler:  If provided, this callable will be invoked when a @print directive is
                                            encountered. If not provided, print directives will not produce any output
                                            except for the log (at the INFO level).

    :return: A list of CompoundType.

    :raises: ParseError, OSError (if directories do not exist or inaccessible)
    """
    # Add the own root namespace to the set of lookup directories, remove duplicates
    lookup_directories = list(set(list(lookup_directories) + [root_namespace_directory]))

    # Normalize paths
    root_namespace_directory = os.path.abspath(root_namespace_directory)
    lookup_directories = list(map(lambda d: str(os.path.abspath(d)), lookup_directories))
    _logger.debug('Lookup directories are listed below:')
    for a in lookup_directories:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + a)

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
    types = _parse_namespace_definitions(target_dsdl_definitions,
                                         lookup_dsdl_definitions,
                                         print_directive_output_handler)

    # Note that we check for collisions in the parsed namespace only.
    # We intentionally ignore (do not check for) possible collisions in the lookup directories,
    # because that would exceed the expected scope of responsibility of the parser, and the lookup
    # directories may contain issues and mistakes that are outside of the control of the user (e.g.,
    # they could be managed by a third party) -- the user shouldn't be affected by mistakes committed
    # by the third party.
    _ensure_no_regulated_port_id_collisions(types)
    _ensure_minor_version_compatibility(types)

    return types


def _parse_namespace_definitions(target_definitions: typing.List[DSDLDefinition],
                                 lookup_definitions: typing.List[DSDLDefinition],
                                 print_handler:      typing.Optional[PrintDirectiveOutputHandler]) -> \
        typing.List[CompoundType]:
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
            parsed = parse_definition(tdd,
                                      lookup_definitions,
                                      print_handler=print_handler)
        except ParseError as ex:    # pragma: no cover
            ex.set_error_location_if_unknown(path=tdd.file_path)
            raise ex
        except Exception as ex:     # pragma: no cover
            raise InternalError(culprit=ex, path=tdd.file_path) from ex
        else:
            types.append(parsed)

    return types


def _ensure_no_regulated_port_id_collisions(types: typing.List[CompoundType]) -> None:
    for a in types:
        for b in types:
            rpid_must_be_different = (a.name != b.name) or (a.version.major != b.version.major)
            if rpid_must_be_different:
                if isinstance(a, ServiceType) == isinstance(b, ServiceType):
                    if a.has_regulated_port_id and b.has_regulated_port_id:
                        if a.regulated_port_id == b.regulated_port_id:
                            raise RegulatedPortIDCollisionError(
                                'The regulated port ID of this definition is also used in %r' % b.source_file_path,
                                path=a.source_file_path
                            )


def _ensure_minor_version_compatibility(types: typing.List[CompoundType]) -> None:
    by_name = defaultdict(list)  # type: typing.DefaultDict[str, typing.List[CompoundType]]
    for t in types:
        by_name[t.name].append(t)

    for name, definitions in by_name.items():
        by_major = defaultdict(list)    # type: typing.DefaultDict[int, typing.List[CompoundType]]
        for t in definitions:
            by_major[t.version.major].append(t)

        for subject_to_check in by_major.values():
            _logger.debug('Minor version compatibility check amongst: %s', [str(x) for x in subject_to_check])
            for a in subject_to_check:
                for b in subject_to_check:
                    if a is b:
                        continue

                    assert a.version.major == b.version.major
                    assert a.name == b.name

                    # Version collision
                    if a.version.minor == b.version.minor:
                        raise MultipleDefinitionsUnderSameVersionError(
                            'This definition shares its version number with %r' % b.source_file_path,
                            path=a.source_file_path
                        )

                    # Must be of the same kind: both messages or both services
                    if isinstance(a, ServiceType) != isinstance(b, ServiceType):
                        raise VersionsOfDifferentKindError(
                            'This definition is not of the same kind as %r' % b.source_file_path,
                            path=a.source_file_path
                        )

                    # Must be bit-compatible
                    if isinstance(a, ServiceType):
                        assert isinstance(b, ServiceType)
                        ok = a.request_type.is_bit_compatible_with(b.request_type) and \
                            a.response_type.is_bit_compatible_with(b.response_type)
                    else:
                        ok = a.bit_length_values == b.bit_length_values

                    if not ok:
                        raise MinorVersionsNotBitCompatibleError(
                            'This definition is not bit-compatible with %r' % b.source_file_path,
                            path=a.source_file_path
                        )

                    # Must use either the same RPID, or the older one should not have an RPID
                    if a.has_regulated_port_id == b.has_regulated_port_id:
                        if a.regulated_port_id != b.regulated_port_id:
                            raise MinorVersionRegulatedPortIDError(
                                'Different regulated port ID values under the same version %r' % b.source_file_path,
                                path=a.source_file_path
                            )
                    else:
                        must_have = a if a.version.minor > b.version.minor else b
                        if not must_have.has_regulated_port_id:
                            raise MinorVersionRegulatedPortIDError(
                                'Regulated port ID cannot be removed under the same major version',
                                path=must_have.source_file_path
                            )


def _ensure_no_nested_root_namespaces(directories: typing.Iterable[str]) -> None:
    directories = list(sorted([str(os.path.abspath(x)) for x in set(directories)]))
    for a in directories:
        for b in directories:
            if (a != b) and a.startswith(b):
                raise NestedRootNamespaceError(
                    'The following namespace is nested inside this one, which is not permitted: %r' % a,
                    path=b
                )


def _ensure_no_namespace_name_collisions(directories: typing.Iterable[str]) -> None:
    def get_namespace_name(d: str) -> str:
        return os.path.split(d)[-1]

    directories = list(sorted([str(os.path.abspath(x)) for x in set(directories)]))
    for a in directories:
        for b in directories:
            if (a != b) and get_namespace_name(a) == get_namespace_name(b):
                raise NamespaceNameCollisionError('The name of this namespace conflicts with %r' % b,
                                                  path=a)


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

    _logger.debug('DSDL files in the namespace dir %r are listed below:', root_namespace_path)
    for a in source_file_paths:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + a)

    output = []  # type: typing.List[DSDLDefinition]
    for fp in source_file_paths:
        dsdl_def = DSDLDefinition(fp, root_namespace_path)
        output.append(dsdl_def)

    return output


def _unittest_dsdl_definition_constructor() -> None:
    import tempfile
    from .dsdl_definition import FileNameFormatError

    directory = tempfile.TemporaryDirectory()
    root_ns_dir = os.path.join(directory.name, 'foo')

    os.mkdir(root_ns_dir)
    os.mkdir(os.path.join(root_ns_dir, 'nested'))

    def touchy(relative_path: str) -> None:
        p = os.path.join(root_ns_dir, relative_path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w') as f:
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

    _construct_dsdl_definitions_from_namespace(root_ns_dir)  # making sure all errors are cleared

    touchy('nested/super.bad/Unreachable.1.0.uavcan')
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
    else:       # pragma: no cover
        assert False

    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir + '/nested/super.bad')
    except FileNameFormatError as ex:
        print(ex)
    else:       # pragma: no cover
        assert False

    discard('nested/super.bad/Unreachable.1.0.uavcan')
