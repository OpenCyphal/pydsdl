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
    def __init__(self, *, path: str, colliding_paths: typing.Iterable[str]):
        text = 'The name of this namespace conflicts with: %r' % list(colliding_paths)
        super(NamespaceNameCollisionError, self).__init__(text=text, path=str(path))


class NestedRootNamespaceError(InvalidDefinitionError):
    """
    Nested root namespaces are not allowed. This exception is thrown when this rule is violated.
    """
    def __init__(self, *, outer_path: str, nested_paths: typing.Iterable[str]):
        text = 'The following namespaces are nested inside this one, which is not permitted: %r' % list(nested_paths)
        super(NestedRootNamespaceError, self).__init__(text=text, path=str(outer_path))


class RegulatedPortIDCollisionError(InvalidDefinitionError):
    """
    Raised when there is more than one definition using the same regulated port ID.
    """
    def __init__(self, *, path: str, colliding_paths: typing.Iterable[str]):
        text = 'The regulated port ID of this definition is also used in: %r' % list(colliding_paths)
        super(RegulatedPortIDCollisionError, self).__init__(text=text, path=str(path))


class VersionsNotBitCompatibleError(InvalidDefinitionError):
    """
    Raised when the versioning requirements are not met.
    """
    def __init__(self, *, path: str, incompatible_paths: typing.Iterable[str]):
        text = 'This definition is not bit-compatible with: %r' % list(incompatible_paths)
        super(VersionsNotBitCompatibleError, self).__init__(text=text, path=str(path))


class MultipleDefinitionsUnderSameVersionError(InvalidDefinitionError):
    """
    For example:
        Type.1.0.uavcan
        58000.Type.1.0.uavcan
        58001.Type.1.0.uavcan
    """
    def __init__(self, *, path: str, incompatible_paths: typing.Iterable[str]):
        text = 'Other definitions under the same version: %r' % list(incompatible_paths)
        super(MultipleDefinitionsUnderSameVersionError, self).__init__(text=text, path=str(path))


class VersionsOfDifferentKindError(InvalidDefinitionError):
    def __init__(self, *, path: str, incompatible_paths: typing.Iterable[str]):
        text = 'This definition is not of the same kind as: %r' % list(incompatible_paths)
        super(VersionsOfDifferentKindError, self).__init__(text=text, path=str(path))


class MinorVersionRegulatedPortIDError(InvalidDefinitionError):
    def __init__(self, *, path: str, incompatible_paths: typing.Iterable[str]):
        text = 'Regulated port ID versioning error: %r' % list(incompatible_paths)
        super(MinorVersionRegulatedPortIDError, self).__init__(text=text, path=str(path))


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

    :raises: ParseError
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
    """
    Simply raises a RegulatedPortIDCollisionError if at least two types of the same kind (messages/services
    are orthogonal) use the same regulated port ID.
    """
    for a in types:
        for b in types:
            rpid_must_be_different = (a.name != b.name) or (a.version.major != b.version.major)
            if rpid_must_be_different:
                if isinstance(a, ServiceType) == isinstance(b, ServiceType):
                    if a.has_regulated_port_id and b.has_regulated_port_id:
                        if a.regulated_port_id == b.regulated_port_id:
                            raise RegulatedPortIDCollisionError(path=a.source_file_path,
                                                                colliding_paths=[b.source_file_path])


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
                        raise MultipleDefinitionsUnderSameVersionError(path=a.source_file_path,
                                                                       incompatible_paths=[b.source_file_path])

                    # Must be of the same kind: both messages or both services
                    if isinstance(a, ServiceType) != isinstance(b, ServiceType):
                        raise VersionsOfDifferentKindError(path=a.source_file_path,
                                                           incompatible_paths=[b.source_file_path])

                    # Must be bit-compatible
                    if isinstance(a, ServiceType):
                        assert isinstance(b, ServiceType)
                        ok = (a.request_type.bit_length_values  == b.request_type.bit_length_values) and \
                             (a.response_type.bit_length_values == b.response_type.bit_length_values)
                    else:
                        ok = a.bit_length_values == b.bit_length_values

                    if not ok:
                        raise VersionsNotBitCompatibleError(path=a.source_file_path,
                                                            incompatible_paths=[b.source_file_path])

                    # Must use either the same RPID, or the older one should not have an RPID
                    if a.has_regulated_port_id == b.has_regulated_port_id:
                        if a.regulated_port_id != b.regulated_port_id:
                            raise MinorVersionRegulatedPortIDError(path=a.source_file_path,
                                                                   incompatible_paths=[b.source_file_path])
                    else:
                        ok = a.has_regulated_port_id if a.version.minor > b.version.minor else b.has_regulated_port_id
                        if not ok:
                            raise MinorVersionRegulatedPortIDError(path=a.source_file_path,
                                                                   incompatible_paths=[b.source_file_path])


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
