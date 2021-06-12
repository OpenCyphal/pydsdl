# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

# pylint: disable=logging-not-lazy

import os
import typing
import logging
import fnmatch
import collections
from . import _serializable
from . import _dsdl_definition
from . import _error


class RootNamespaceNameCollisionError(_error.InvalidDefinitionError):
    """
    Raised when there is more than one namespace under the same name.
    This may occur if there are identically named namespaces located in different directories.
    """


class DataTypeNameCollisionError(_error.InvalidDefinitionError):
    """
    Raised when there are conflicting data type names.
    """


class NestedRootNamespaceError(_error.InvalidDefinitionError):
    """
    Nested root namespaces are not allowed. This exception is thrown when this rule is violated.
    """


class FixedPortIDCollisionError(_error.InvalidDefinitionError):
    """
    Raised when there is more than one data type, or different major versions of the same data type
    using the same fixed port ID.
    """


class MultipleDefinitionsUnderSameVersionError(_error.InvalidDefinitionError):
    """
    For example::

        Type.1.0.uavcan
        2800.Type.1.0.uavcan
        2801.Type.1.0.uavcan
    """


class VersionsOfDifferentKindError(_error.InvalidDefinitionError):
    """
    Definitions that share the same name but are of different kinds.
    """


class MinorVersionFixedPortIDError(_error.InvalidDefinitionError):
    """
    Different fixed port-ID under the same major version, or a fixed port ID was removed under the same major version.
    """


class ExtentConsistencyError(_error.InvalidDefinitionError):
    """
    Different extent under the same major version.
    """


class SealingConsistencyError(_error.InvalidDefinitionError):
    """
    Different sealing status under the same major version.
    """


PrintOutputHandler = typing.Callable[[str, int, str], None]
"""Invoked when the frontend encounters a print directive or needs to output a generic diagnostic."""


def read_namespace(
    root_namespace_directory: str,
    lookup_directories: typing.Optional[typing.Union[str, typing.Iterable[str]]] = None,
    print_output_handler: typing.Optional[PrintOutputHandler] = None,
    allow_unregulated_fixed_port_id: bool = False,
) -> typing.List[_serializable.CompositeType]:
    """
    This function is the main entry point of the library.
    It reads all DSDL definitions from the specified root namespace directory and produces the annotated AST.

    :param root_namespace_directory: The path of the root namespace directory that will be read.
        For example, ``dsdl/uavcan`` to read the ``uavcan`` namespace.

    :param lookup_directories: List of other namespace directories containing data type definitions that are
        referred to from the target root namespace. For example, if you are reading a vendor-specific namespace,
        the list of lookup directories should always include a path to the standard root namespace ``uavcan``,
        otherwise the types defined in the vendor-specific namespace won't be able to use data types from the
        standard namespace.

    :param print_output_handler: If provided, this callable will be invoked when a ``@print`` directive
        is encountered or when the frontend needs to emit a diagnostic;
        the arguments are: path, line number (1-based), text.
        If not provided, no output will be produced except for the standard Python logging subsystem
        (but ``@print`` expressions will be evaluated anyway, and a failed evaluation will be a fatal error).

    :param allow_unregulated_fixed_port_id: Do not reject unregulated fixed port identifiers.
        As demanded by the specification, the frontend rejects unregulated fixed port ID by default.
        This is a dangerous feature that must not be used unless you understand the risks.
        Please read https://uavcan.org/guide.

    :return: A list of :class:`pydsdl.CompositeType` sorted lexicographically by full data type name,
             then by major version (newest version first), then by minor version (newest version first).
             The ordering guarantee allows the caller to always find the newest version simply by picking
             the first matching occurrence.

    :raises: :class:`pydsdl.FrontendError`, :class:`MemoryError`, :class:`SystemError`,
        :class:`OSError` if directories do not exist or inaccessible,
        :class:`ValueError`/:class:`TypeError` if the arguments are invalid.
    """
    # Add the own root namespace to the set of lookup directories, sort lexicographically, remove duplicates.
    # We'd like this to be an iterable list of strings but we handle the common practice of passing in a single path.
    if lookup_directories is None:
        lookup_directories_path_list = []  # type: typing.List[str]
    elif isinstance(lookup_directories, (str, bytes)):
        lookup_directories_path_list = [lookup_directories]
    else:
        lookup_directories_path_list = list(lookup_directories)

    for a in lookup_directories_path_list:
        if not isinstance(a, str):  # non-string paths
            raise TypeError("Lookup directories shall be an iterable of strings. Found in list: " + type(a).__name__)
        _logger.debug(_LOG_LIST_ITEM_PREFIX + a)

    # Normalize paths and remove duplicates.
    root_namespace_directory = os.path.abspath(root_namespace_directory)
    lookup_directories_path_list.append(root_namespace_directory)
    lookup_directories_path_list = list(sorted({os.path.abspath(x) for x in lookup_directories_path_list}))
    _logger.debug("Lookup directories are listed below:")
    for a in lookup_directories_path_list:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + a)

    # Check for common usage errors and warn the user if anything looks suspicious.
    _ensure_no_common_usage_errors(root_namespace_directory, lookup_directories_path_list, _logger.warning)

    # Check the namespaces.
    _ensure_no_nested_root_namespaces(lookup_directories_path_list)
    _ensure_no_namespace_name_collisions(lookup_directories_path_list)

    # Construct DSDL definitions from the target and the lookup dirs.
    target_dsdl_definitions = _construct_dsdl_definitions_from_namespace(root_namespace_directory)
    if not target_dsdl_definitions:
        _logger.info("The namespace at %r is empty", root_namespace_directory)
        return []
    _logger.debug("Target DSDL definitions are listed below:")
    for x in target_dsdl_definitions:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(x))

    lookup_dsdl_definitions = []  # type: typing.List[_dsdl_definition.DSDLDefinition]
    for ld in lookup_directories_path_list:
        lookup_dsdl_definitions += _construct_dsdl_definitions_from_namespace(ld)

    # Check for collisions against the lookup definitions also.
    _ensure_no_name_collisions(target_dsdl_definitions, lookup_dsdl_definitions)

    _logger.debug("Lookup DSDL definitions are listed below:")
    for x in lookup_dsdl_definitions:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(x))

    _logger.info(
        "Reading %d definitions from the root namespace %r, "
        "with %d lookup definitions located in root namespaces: %s",
        len(target_dsdl_definitions),
        list(set(map(lambda t: t.root_namespace, target_dsdl_definitions)))[0],
        len(lookup_dsdl_definitions),
        ", ".join(set(sorted(map(lambda t: t.root_namespace, lookup_dsdl_definitions)))),
    )

    # Read the constructed definitions.
    types = _read_namespace_definitions(
        target_dsdl_definitions, lookup_dsdl_definitions, print_output_handler, allow_unregulated_fixed_port_id
    )

    # Note that we check for collisions in the read namespace only.
    # We intentionally ignore (do not check for) possible collisions in the lookup directories,
    # because that would exceed the expected scope of responsibility of the frontend, and the lookup
    # directories may contain issues and mistakes that are outside of the control of the user (e.g.,
    # they could be managed by a third party) -- the user shouldn't be affected by mistakes committed
    # by the third party.
    _ensure_no_fixed_port_id_collisions(types)
    _ensure_minor_version_compatibility(types)

    return types


_DSDL_FILE_GLOB = "*.uavcan"
_LOG_LIST_ITEM_PREFIX = " " * 4

_logger = logging.getLogger(__name__)


def _read_namespace_definitions(
    target_definitions: typing.List[_dsdl_definition.DSDLDefinition],
    lookup_definitions: typing.List[_dsdl_definition.DSDLDefinition],
    print_output_handler: typing.Optional[PrintOutputHandler] = None,
    allow_unregulated_fixed_port_id: bool = False,
) -> typing.List[_serializable.CompositeType]:
    """
    Construct type descriptors from the specified target definitions.
    Allow the target definitions to use the lookup definitions within themselves.
    :param target_definitions:  Which definitions to read.
    :param lookup_definitions:  Which definitions can be used by the processed definitions.
    :return: A list of types.
    """

    def make_print_handler(definition: _dsdl_definition.DSDLDefinition) -> typing.Callable[[int, str], None]:
        def handler(line_number: int, text: str) -> None:
            if print_output_handler:  # pragma: no branch
                assert isinstance(line_number, int) and isinstance(text, str)
                assert line_number > 0, "Line numbers must be one-based"
                print_output_handler(definition.file_path, line_number, text)

        return handler

    types = []  # type: typing.List[_serializable.CompositeType]
    for tdd in target_definitions:
        try:
            dt = tdd.read(lookup_definitions, make_print_handler(tdd), allow_unregulated_fixed_port_id)
        except _error.FrontendError as ex:  # pragma: no cover
            ex.set_error_location_if_unknown(path=tdd.file_path)
            raise ex
        except (MemoryError, SystemError):  # pragma: no cover
            raise
        except Exception as ex:  # pragma: no cover
            raise _error.InternalError(culprit=ex, path=tdd.file_path) from ex
        else:
            types.append(dt)

    return types


def _ensure_no_name_collisions(
    target_definitions: typing.List[_dsdl_definition.DSDLDefinition],
    lookup_definitions: typing.List[_dsdl_definition.DSDLDefinition],
) -> None:
    for tg in target_definitions:
        for lu in lookup_definitions:
            if tg.full_name != lu.full_name and tg.full_name.lower() == lu.full_name.lower():
                raise DataTypeNameCollisionError(
                    "Full name of this definition differs from %r only by letter case, "
                    "which is not permitted" % lu.file_path,
                    path=tg.file_path,
                )

            if tg.full_namespace.lower().startswith(lu.full_name.lower()):  # pragma: no cover
                raise DataTypeNameCollisionError(
                    "The namespace of this type conflicts with %r" % lu.file_path, path=tg.file_path
                )

            if lu.full_namespace.lower().startswith(tg.full_name.lower()):
                raise DataTypeNameCollisionError(
                    "This type conflicts with the namespace of %r" % lu.file_path, path=tg.file_path
                )


def _ensure_no_fixed_port_id_collisions(types: typing.List[_serializable.CompositeType]) -> None:
    for a in types:
        for b in types:
            different_names = a.full_name != b.full_name
            different_major_versions = a.version.major != b.version.major
            # Must be the same kind because port ID sets of subjects and services are orthogonal
            same_kind = isinstance(a, _serializable.ServiceType) == isinstance(b, _serializable.ServiceType)
            # Data types where the major version is zero are allowed to collide
            both_released = (a.version.major > 0) and (b.version.major > 0)

            fpid_must_be_different = same_kind and (different_names or (different_major_versions and both_released))

            if fpid_must_be_different:
                if a.has_fixed_port_id and b.has_fixed_port_id:
                    if a.fixed_port_id == b.fixed_port_id:
                        raise FixedPortIDCollisionError(
                            "The fixed port ID of this definition is also used in %r" % b.source_file_path,
                            path=a.source_file_path,
                        )


def _ensure_minor_version_compatibility(types: typing.List[_serializable.CompositeType]) -> None:
    by_name = collections.defaultdict(list)  # type: typing.DefaultDict[str, typing.List[_serializable.CompositeType]]
    for t in types:
        by_name[t.full_name].append(t)

    for definitions in by_name.values():
        by_major = collections.defaultdict(
            list
        )  # type: typing.DefaultDict[int, typing.List[_serializable.CompositeType]]
        for t in definitions:
            by_major[t.version.major].append(t)

        for subject_to_check in by_major.values():
            _logger.debug("Minor version compatibility check amongst: %s", [str(x) for x in subject_to_check])
            for a in subject_to_check:
                for b in subject_to_check:
                    if a is not b:
                        _ensure_minor_version_compatibility_pairwise(a, b)


def _ensure_minor_version_compatibility_pairwise(
    a: _serializable.CompositeType, b: _serializable.CompositeType
) -> None:
    assert a is not b
    assert a.version.major == b.version.major
    assert a.full_name == b.full_name

    # Version collision
    if a.version.minor == b.version.minor:
        raise MultipleDefinitionsUnderSameVersionError(
            "This definition shares its version number with %r" % b.source_file_path, path=a.source_file_path
        )

    # Must be of the same kind: both messages or both services
    if isinstance(a, _serializable.ServiceType) != isinstance(b, _serializable.ServiceType):
        raise VersionsOfDifferentKindError(
            "This definition is not of the same kind as %r" % b.source_file_path, path=a.source_file_path
        )

    # Must use either the same RPID, or the older one should not have an RPID
    if a.has_fixed_port_id == b.has_fixed_port_id:
        if a.fixed_port_id != b.fixed_port_id:
            raise MinorVersionFixedPortIDError(
                "Different fixed port ID values under the same version %r" % b.source_file_path, path=a.source_file_path
            )
    else:
        must_have = a if a.version.minor > b.version.minor else b
        if not must_have.has_fixed_port_id:
            raise MinorVersionFixedPortIDError(
                "Fixed port ID cannot be removed under the same major version", path=must_have.source_file_path
            )

    # Extent and sealing equality
    if isinstance(a, _serializable.ServiceType) and isinstance(b, _serializable.ServiceType):
        _ensure_minor_version_compatibility_pairwise(a.request_type, b.request_type)
        _ensure_minor_version_compatibility_pairwise(a.response_type, b.response_type)
    elif a.version.major > 0:  # Types with major=0 are exempt from compatibility requirements.
        if a.extent != b.extent:
            raise ExtentConsistencyError(
                "The extent of %s is %d bits, whereas the extent of %s is %d bits. "
                "The types share the same major version, so their extents should be equal "
                "to avoid wire compatibility issues." % (a, a.extent, b, b.extent),
                path=a.source_file_path,
            )
        a_sealed = not isinstance(a, _serializable.DelimitedType)
        b_sealed = not isinstance(b, _serializable.DelimitedType)
        sealing_name = ["delimited", "sealed"]
        if a_sealed != b_sealed:
            raise SealingConsistencyError(
                "%s is %s, but %s is %s. "
                "Mixing sealed and delimited types under the same major version will cause wire compatibility issues."
                % (
                    a,
                    sealing_name[a_sealed],
                    b,
                    sealing_name[b_sealed],
                ),
                path=a.source_file_path,
            )


def _ensure_no_common_usage_errors(
    root_namespace_directory: str, lookup_directories: typing.Iterable[str], reporter: typing.Callable[[str], None]
) -> None:
    suspicious_base_names = [
        "public_regulated_data_types",
        "dsdl",
    ]

    def base(s: str) -> str:
        return os.path.basename(os.path.normpath(s))

    def is_valid_name(s: str) -> bool:
        try:
            _serializable.check_name(s)
        except _error.InvalidDefinitionError:
            return False
        else:
            return True

    all_paths = set([root_namespace_directory] + list(lookup_directories))
    for p in all_paths:
        p = os.path.normcase(os.path.abspath(p))
        try:
            candidates = [x for x in os.listdir(p) if os.path.isdir(os.path.join(p, x)) and is_valid_name(x)]
        except OSError:  # pragma: no cover
            candidates = []
        if candidates and base(p) in suspicious_base_names:
            report = (
                "Possibly incorrect usage detected: input path %r is likely incorrect because the last path component "
                "should be the root namespace name rather than its parent directory. You probably meant:\n%s"
            ) % (
                p,
                "\n".join(("- %s" % os.path.join(p, s)) for s in candidates),
            )
            reporter(report)


def _ensure_no_nested_root_namespaces(directories: typing.Iterable[str]) -> None:
    directories = list(sorted([str(os.path.join(os.path.abspath(x), "")) for x in set(directories)]))
    for a in directories:
        for b in directories:
            if (a != b) and a.startswith(b):
                raise NestedRootNamespaceError(
                    "The following namespace is nested inside this one, which is not permitted: %r" % a, path=b
                )


def _ensure_no_namespace_name_collisions(directories: typing.Iterable[str]) -> None:
    def get_namespace_name(d: str) -> str:
        return os.path.split(d)[-1]

    directories = list(sorted([str(os.path.abspath(x)) for x in set(directories)]))
    for a in directories:
        for b in directories:
            if (a != b) and get_namespace_name(a).lower() == get_namespace_name(b).lower():
                raise RootNamespaceNameCollisionError("The name of this namespace conflicts with %r" % b, path=a)


def _construct_dsdl_definitions_from_namespace(
    root_namespace_path: str,
) -> typing.List[_dsdl_definition.DSDLDefinition]:
    """
    Accepts a directory path, returns a sorted list of abstract DSDL file representations. Those can be read later.
    The definitions are sorted by name lexicographically, then by major version (greatest version first),
    then by minor version (same ordering as the major version).
    """

    def on_walk_error(os_ex: Exception) -> None:
        raise os_ex  # pragma: no cover

    walker = os.walk(root_namespace_path, onerror=on_walk_error, followlinks=True)

    source_file_paths = []  # type: typing.List[str]
    for root, _dirnames, filenames in walker:
        for filename in fnmatch.filter(filenames, _DSDL_FILE_GLOB):
            source_file_paths.append(os.path.join(root, filename))

    _logger.debug("DSDL files in the namespace dir %r are listed below:", root_namespace_path)
    for a in source_file_paths:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + a)

    output = []  # type: typing.List[_dsdl_definition.DSDLDefinition]
    for fp in source_file_paths:
        dsdl_def = _dsdl_definition.DSDLDefinition(fp, root_namespace_path)
        output.append(dsdl_def)

    # Lexicographically by name, newest version first.
    return list(sorted(output, key=lambda d: (d.full_name, -d.version.major, -d.version.minor)))


def _unittest_dsdl_definition_constructor() -> None:
    import tempfile
    from ._dsdl_definition import FileNameFormatError

    directory = tempfile.TemporaryDirectory()
    root_ns_dir = os.path.join(directory.name, "foo")

    os.mkdir(root_ns_dir)
    os.mkdir(os.path.join(root_ns_dir, "nested"))

    def touchy(relative_path: str) -> None:
        p = os.path.join(root_ns_dir, relative_path.replace("/", os.path.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("# TEST TEXT")

    def discard(relative_path: str) -> None:
        os.unlink(os.path.join(root_ns_dir, relative_path))

    touchy("123.Qwerty.123.234.uavcan")
    touchy("nested/2.Asd.21.32.uavcan")
    touchy("nested/Foo.32.43.uavcan")

    dsdl_defs = _construct_dsdl_definitions_from_namespace(root_ns_dir)
    print(dsdl_defs)
    lut = {x.full_name: x for x in dsdl_defs}  # type: typing.Dict[str, _dsdl_definition.DSDLDefinition]
    assert len(lut) == 3

    assert str(lut["foo.Qwerty"]) == repr(lut["foo.Qwerty"])
    assert (
        str(lut["foo.Qwerty"])
        == "DSDLDefinition(full_name='foo.Qwerty', version=Version(major=123, minor=234), fixed_port_id=123, "
        "file_path=%r)" % lut["foo.Qwerty"].file_path
    )

    assert (
        str(lut["foo.nested.Foo"])
        == "DSDLDefinition(full_name='foo.nested.Foo', version=Version(major=32, minor=43), fixed_port_id=None, "
        "file_path=%r)" % lut["foo.nested.Foo"].file_path
    )

    t = lut["foo.Qwerty"]
    assert t.file_path == os.path.join(root_ns_dir, "123.Qwerty.123.234.uavcan")
    assert t.has_fixed_port_id
    assert t.fixed_port_id == 123
    assert t.text == "# TEST TEXT"
    assert t.version.major == 123
    assert t.version.minor == 234
    assert t.name_components == ["foo", "Qwerty"]
    assert t.short_name == "Qwerty"
    assert t.root_namespace == "foo"
    assert t.full_namespace == "foo"

    t = lut["foo.nested.Asd"]
    assert t.file_path == os.path.join(root_ns_dir, "nested", "2.Asd.21.32.uavcan")
    assert t.has_fixed_port_id
    assert t.fixed_port_id == 2
    assert t.text == "# TEST TEXT"
    assert t.version.major == 21
    assert t.version.minor == 32
    assert t.name_components == ["foo", "nested", "Asd"]
    assert t.short_name == "Asd"
    assert t.root_namespace == "foo"
    assert t.full_namespace == "foo.nested"

    t = lut["foo.nested.Foo"]
    assert t.file_path == os.path.join(root_ns_dir, "nested", "Foo.32.43.uavcan")
    assert not t.has_fixed_port_id
    assert t.fixed_port_id is None
    assert t.text == "# TEST TEXT"
    assert t.version.major == 32
    assert t.version.minor == 43
    assert t.name_components == ["foo", "nested", "Foo"]
    assert t.short_name == "Foo"
    assert t.root_namespace == "foo"
    assert t.full_namespace == "foo.nested"

    touchy("nested/Malformed.MAJOR.MINOR.uavcan")
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
        discard("nested/Malformed.MAJOR.MINOR.uavcan")
    else:  # pragma: no cover
        assert False

    touchy("nested/NOT_A_NUMBER.Malformed.1.0.uavcan")
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
        discard("nested/NOT_A_NUMBER.Malformed.1.0.uavcan")
    else:  # pragma: no cover
        assert False

    touchy("nested/Malformed.uavcan")
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
        discard("nested/Malformed.uavcan")
    else:  # pragma: no cover
        assert False

    _construct_dsdl_definitions_from_namespace(root_ns_dir)  # making sure all errors are cleared

    touchy("nested/super.bad/Unreachable.1.0.uavcan")
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
    else:  # pragma: no cover
        assert False

    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir + "/nested/super.bad")
    except FileNameFormatError as ex:
        print(ex)
    else:  # pragma: no cover
        assert False

    discard("nested/super.bad/Unreachable.1.0.uavcan")


def _unittest_common_usage_errors() -> None:
    import tempfile

    directory = tempfile.TemporaryDirectory()
    root_ns_dir = os.path.join(directory.name, "foo")
    os.mkdir(root_ns_dir)

    reports = []  # type: typing.List[str]

    _ensure_no_common_usage_errors(root_ns_dir, [], reports.append)
    assert not reports
    _ensure_no_common_usage_errors(root_ns_dir, ["/baz"], reports.append)
    assert not reports

    dir_dsdl = os.path.join(root_ns_dir, "dsdl")
    os.mkdir(dir_dsdl)
    _ensure_no_common_usage_errors(dir_dsdl, ["/baz"], reports.append)
    assert not reports  # Because empty.

    dir_dsdl_vscode = os.path.join(dir_dsdl, ".vscode")
    os.mkdir(dir_dsdl_vscode)
    _ensure_no_common_usage_errors(dir_dsdl, ["/baz"], reports.append)
    assert not reports  # Because the name is not valid.

    dir_dsdl_uavcan = os.path.join(dir_dsdl, "uavcan")
    os.mkdir(dir_dsdl_uavcan)
    _ensure_no_common_usage_errors(dir_dsdl, ["/baz"], reports.append)
    (rep,) = reports
    reports.clear()
    assert os.path.normcase(dir_dsdl_uavcan) in rep


def _unittest_nested_roots() -> None:
    from pytest import raises

    _ensure_no_nested_root_namespaces([])
    _ensure_no_nested_root_namespaces(["a"])
    _ensure_no_nested_root_namespaces(["a/b", "a/c"])
    with raises(NestedRootNamespaceError):
        _ensure_no_nested_root_namespaces(["a/b", "a"])
    _ensure_no_nested_root_namespaces(["aa/b", "a"])
    _ensure_no_nested_root_namespaces(["a/b", "aa"])
