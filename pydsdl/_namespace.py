# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

# pylint: disable=logging-not-lazy

import os
from typing import Iterable, Callable, DefaultDict, List, Optional, Union, Set, Dict
import logging
import fnmatch
import collections
from pathlib import Path
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

        Type.1.0.dsdl
        2800.Type.1.0.dsdl
        2801.Type.1.0.dsdl
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


PrintOutputHandler = Callable[[Path, int, str], None]
"""Invoked when the frontend encounters a print directive or needs to output a generic diagnostic."""


def read_namespace(
    root_namespace_directory: Union[Path, str],
    lookup_directories: Union[None, Path, str, Iterable[Union[Path, str]]] = None,
    print_output_handler: Optional[PrintOutputHandler] = None,
    allow_unregulated_fixed_port_id: bool = False,
    allow_root_namespace_name_collision: bool = True,
) -> List[_serializable.CompositeType]:
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
        Please read https://opencyphal.org/guide.

    :param allow_root_namespace_name_collision: Allow using the source root namespace name in the look up dirs or
             the same root namespace name multiple times in the lookup dirs. This will enable defining a namespace
             partially and let other entities define new messages or new sub-namespaces in the same root namespace.

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
        lookup_directories_path_list: List[Path] = []
    elif isinstance(lookup_directories, (str, bytes, Path)):
        lookup_directories_path_list = [Path(lookup_directories)]
    else:
        lookup_directories_path_list = list(map(Path, lookup_directories))

    for a in lookup_directories_path_list:
        if not isinstance(a, (str, Path)):
            raise TypeError("Lookup directories shall be an iterable of paths. Found in list: " + type(a).__name__)
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(a))

    # Normalize paths and remove duplicates. Resolve symlinks to avoid ambiguities.
    root_namespace_directory = Path(root_namespace_directory).resolve()
    lookup_directories_path_list.append(root_namespace_directory)
    lookup_directories_path_list = list(sorted({x.resolve() for x in lookup_directories_path_list}))
    _logger.debug("Lookup directories are listed below:")
    for a in lookup_directories_path_list:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(a))

    # Check for common usage errors and warn the user if anything looks suspicious.
    _ensure_no_common_usage_errors(root_namespace_directory, lookup_directories_path_list, _logger.warning)

    # Check the namespaces.
    _ensure_no_nested_root_namespaces(lookup_directories_path_list)

    if not allow_root_namespace_name_collision:
        _ensure_no_namespace_name_collisions(lookup_directories_path_list)

    # Construct DSDL definitions from the target and the lookup dirs.
    target_dsdl_definitions = _construct_dsdl_definitions_from_namespace(root_namespace_directory)
    if not target_dsdl_definitions:
        _logger.info("The namespace at %s is empty", root_namespace_directory)
        return []
    _logger.debug("Target DSDL definitions are listed below:")
    for x in target_dsdl_definitions:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(x))

    lookup_dsdl_definitions = []  # type: List[_dsdl_definition.DSDLDefinition]
    for ld in lookup_directories_path_list:
        lookup_dsdl_definitions += _construct_dsdl_definitions_from_namespace(ld)

    # Check for collisions against the lookup definitions also.
    _ensure_no_name_collisions(target_dsdl_definitions, lookup_dsdl_definitions)

    _logger.debug("Lookup DSDL definitions are listed below:")
    for x in lookup_dsdl_definitions:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(x))

    _logger.info(
        "Reading %d definitions from the root namespace %s, "
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


_DSDL_FILE_GLOBS = [
    "*.dsdl",  # https://forum.opencyphal.org/t/uavcan-file-extension/438
    "*.uavcan",  # Legacy name, not for new projects.
]
_LOG_LIST_ITEM_PREFIX = " " * 4

_logger = logging.getLogger(__name__)


def _read_namespace_definitions(
    target_definitions: List[_dsdl_definition.DSDLDefinition],
    lookup_definitions: List[_dsdl_definition.DSDLDefinition],
    print_output_handler: Optional[PrintOutputHandler] = None,
    allow_unregulated_fixed_port_id: bool = False,
) -> List[_serializable.CompositeType]:
    """
    Construct type descriptors from the specified target definitions.
    Allow the target definitions to use the lookup definitions within themselves.
    :param target_definitions:  Which definitions to read.
    :param lookup_definitions:  Which definitions can be used by the processed definitions.
    :return: A list of types.
    """

    def make_print_handler(definition: _dsdl_definition.DSDLDefinition) -> Callable[[int, str], None]:
        def handler(line_number: int, text: str) -> None:
            if print_output_handler:  # pragma: no branch
                assert isinstance(line_number, int) and isinstance(text, str)
                assert line_number > 0, "Line numbers must be one-based"
                print_output_handler(definition.file_path, line_number, text)

        return handler

    types = []  # type: List[_serializable.CompositeType]
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
    target_definitions: List[_dsdl_definition.DSDLDefinition],
    lookup_definitions: List[_dsdl_definition.DSDLDefinition],
) -> None:
    for tg in target_definitions:
        tg_full_namespace_period = tg.full_namespace.lower() + "."
        tg_full_name_period = tg.full_name.lower() + "."
        for lu in lookup_definitions:
            lu_full_namespace_period = lu.full_namespace.lower() + "."
            lu_full_name_period = lu.full_name.lower() + "."
            """
            This is to allow the following messages to coexist happily:

            zubax/noncolliding/iceberg/Ice.0.1.dsdl
            zubax/noncolliding/Iceb.0.1.dsdl

            The following is still not allowed:

            zubax/colliding/iceberg/Ice.0.1.dsdl
            zubax/colliding/Iceberg.0.1.dsdl

            """
            if tg.full_name != lu.full_name and tg.full_name.lower() == lu.full_name.lower():
                raise DataTypeNameCollisionError(
                    "Full name of this definition differs from %s only by letter case, "
                    "which is not permitted" % lu.file_path,
                    path=tg.file_path,
                )
            if (tg_full_namespace_period).startswith(lu_full_name_period):
                raise DataTypeNameCollisionError(
                    "The namespace of this type conflicts with %s" % lu.file_path, path=tg.file_path
                )
            if (lu_full_namespace_period).startswith(tg_full_name_period):
                raise DataTypeNameCollisionError(
                    "This type conflicts with the namespace of %s" % lu.file_path, path=tg.file_path
                )


def _ensure_no_fixed_port_id_collisions(types: List[_serializable.CompositeType]) -> None:
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
                            "The fixed port ID of this definition is also used in %s" % b.source_file_path,
                            path=a.source_file_path,
                        )


def _ensure_minor_version_compatibility(types: List[_serializable.CompositeType]) -> None:
    by_name = collections.defaultdict(list)  # type: DefaultDict[str, List[_serializable.CompositeType]]
    for t in types:
        by_name[t.full_name].append(t)

    for definitions in by_name.values():
        by_major = collections.defaultdict(list)  # type: DefaultDict[int, List[_serializable.CompositeType]]
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
            "This definition shares its version number with %s" % b.source_file_path, path=a.source_file_path
        )

    # Must be of the same kind: both messages or both services
    if isinstance(a, _serializable.ServiceType) != isinstance(b, _serializable.ServiceType):
        raise VersionsOfDifferentKindError(
            "This definition is not of the same kind as %s" % b.source_file_path, path=a.source_file_path
        )

    # Must use either the same RPID, or the older one should not have an RPID
    if a.has_fixed_port_id == b.has_fixed_port_id:
        if a.fixed_port_id != b.fixed_port_id:
            raise MinorVersionFixedPortIDError(
                "Different fixed port ID values under the same version %s" % b.source_file_path, path=a.source_file_path
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
    root_namespace_directory: Path, lookup_directories: Iterable[Path], reporter: Callable[[str], None]
) -> None:
    suspicious_base_names = [
        "public_regulated_data_types",
        "dsdl",
    ]

    def base(s: Path) -> str:
        return str(os.path.basename(os.path.normpath(s)))

    def is_valid_name(s: str) -> bool:
        try:
            _serializable.check_name(s)
        except _error.InvalidDefinitionError:
            return False
        else:
            return True

    all_paths = set([root_namespace_directory] + list(lookup_directories))
    for p in all_paths:
        p = Path(os.path.normcase(p.resolve()))
        try:
            candidates = [x for x in os.listdir(p) if os.path.isdir(os.path.join(p, x)) and is_valid_name(str(x))]
        except OSError:  # pragma: no cover
            candidates = []
        if candidates and base(p) in suspicious_base_names:
            report = (
                "Possibly incorrect usage detected: input path %s is likely incorrect because the last path component "
                "should be the root namespace name rather than its parent directory. You probably meant:\n%s"
            ) % (
                p,
                "\n".join(("- %s" % os.path.join(p, s)) for s in candidates),
            )
            reporter(report)


def _ensure_no_nested_root_namespaces(directories: Iterable[Path]) -> None:
    dir_str = list(sorted([os.path.join(os.path.abspath(x), "") for x in set(directories)]))
    for a in dir_str:
        for b in dir_str:
            if (a != b) and a.startswith(b):
                raise NestedRootNamespaceError(
                    "The following namespace is nested inside this one, which is not permitted: %s" % a, path=Path(b)
                )


def _ensure_no_namespace_name_collisions(directories: Iterable[Path]) -> None:
    directories = list(sorted([x.resolve() for x in set(directories)]))
    for a in directories:
        for b in directories:
            if (a != b) and a.name.lower() == b.name.lower():
                _logger.info("Collision: %r [%r] == %r [%r]", a, a.name, b, b.name)
                raise RootNamespaceNameCollisionError("The name of this namespace conflicts with %s" % b, path=a)


def _construct_dsdl_definitions_from_namespace(
    root_namespace_path: Path,
) -> List[_dsdl_definition.DSDLDefinition]:
    """
    Accepts a directory path, returns a sorted list of abstract DSDL file representations. Those can be read later.
    The definitions are sorted by name lexicographically, then by major version (greatest version first),
    then by minor version (same ordering as the major version).
    """

    def on_walk_error(os_ex: Exception) -> None:
        raise os_ex  # pragma: no cover

    walker = os.walk(root_namespace_path, onerror=on_walk_error, followlinks=True)

    source_file_paths: Set[Path] = set()
    for root, _dirnames, filenames in walker:
        for glb in _DSDL_FILE_GLOBS:
            for filename in fnmatch.filter(filenames, glb):
                source_file_paths.add(Path(root, filename))

    output = []  # type: List[_dsdl_definition.DSDLDefinition]
    for fp in sorted(source_file_paths):
        dsdl_def = _dsdl_definition.DSDLDefinition(fp, root_namespace_path)
        output.append(dsdl_def)

    # Lexicographically by name, newest version first.
    return list(sorted(output, key=lambda d: (d.full_name, -d.version.major, -d.version.minor)))


def _unittest_dsdl_definition_constructor() -> None:
    import tempfile
    from ._dsdl_definition import FileNameFormatError

    directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
    root_ns_dir = Path(directory.name, "foo").resolve()
    (root_ns_dir / "nested").mkdir(parents=True)

    def touchy(relative_path: str) -> None:
        p = os.path.join(root_ns_dir, relative_path.replace("/", os.path.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("# TEST TEXT")

    def discard(relative_path: str) -> None:
        os.unlink(os.path.join(root_ns_dir, relative_path))

    touchy("123.Qwerty.123.234.dsdl")
    touchy("nested/2.Asd.21.32.dsdl")
    touchy("nested/Foo.32.43.dsdl")

    dsdl_defs = _construct_dsdl_definitions_from_namespace(root_ns_dir)
    print(dsdl_defs)
    lut = {x.full_name: x for x in dsdl_defs}  # type: Dict[str, _dsdl_definition.DSDLDefinition]
    assert len(lut) == 3

    assert str(lut["foo.Qwerty"]) == repr(lut["foo.Qwerty"])
    assert (
        str(lut["foo.Qwerty"])
        == "DSDLDefinition(full_name='foo.Qwerty', version=Version(major=123, minor=234), fixed_port_id=123, "
        "file_path=%s)" % lut["foo.Qwerty"].file_path
    )

    assert (
        str(lut["foo.nested.Foo"])
        == "DSDLDefinition(full_name='foo.nested.Foo', version=Version(major=32, minor=43), fixed_port_id=None, "
        "file_path=%s)" % lut["foo.nested.Foo"].file_path
    )

    t = lut["foo.Qwerty"]
    assert t.file_path == root_ns_dir / "123.Qwerty.123.234.dsdl"
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
    assert t.file_path == root_ns_dir / "nested" / "2.Asd.21.32.dsdl"
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
    assert t.file_path == root_ns_dir / "nested" / "Foo.32.43.dsdl"
    assert not t.has_fixed_port_id
    assert t.fixed_port_id is None
    assert t.text == "# TEST TEXT"
    assert t.version.major == 32
    assert t.version.minor == 43
    assert t.name_components == ["foo", "nested", "Foo"]
    assert t.short_name == "Foo"
    assert t.root_namespace == "foo"
    assert t.full_namespace == "foo.nested"

    touchy("nested/Malformed.MAJOR.MINOR.dsdl")
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
        discard("nested/Malformed.MAJOR.MINOR.dsdl")
    else:  # pragma: no cover
        assert False

    touchy("nested/NOT_A_NUMBER.Malformed.1.0.dsdl")
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
        discard("nested/NOT_A_NUMBER.Malformed.1.0.dsdl")
    else:  # pragma: no cover
        assert False

    touchy("nested/Malformed.dsdl")
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
        discard("nested/Malformed.dsdl")
    else:  # pragma: no cover
        assert False

    _construct_dsdl_definitions_from_namespace(root_ns_dir)  # making sure all errors are cleared

    touchy("nested/super.bad/Unreachable.1.0.dsdl")
    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir)
    except FileNameFormatError as ex:
        print(ex)
    else:  # pragma: no cover
        assert False

    try:
        _construct_dsdl_definitions_from_namespace(root_ns_dir / "nested/super.bad")
    except FileNameFormatError as ex:
        print(ex)
    else:  # pragma: no cover
        assert False

    discard("nested/super.bad/Unreachable.1.0.dsdl")


def _unittest_common_usage_errors() -> None:
    import tempfile

    directory = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
    root_ns_dir = Path(os.path.join(directory.name, "foo"))
    os.mkdir(root_ns_dir)

    reports = []  # type: List[str]

    _ensure_no_common_usage_errors(root_ns_dir, [], reports.append)
    assert not reports
    _ensure_no_common_usage_errors(root_ns_dir, [Path("/baz")], reports.append)
    assert not reports

    dir_dsdl = root_ns_dir / "dsdl"
    os.mkdir(dir_dsdl)
    _ensure_no_common_usage_errors(dir_dsdl, [Path("/baz")], reports.append)
    assert not reports  # Because empty.

    dir_dsdl_vscode = os.path.join(dir_dsdl, ".vscode")
    os.mkdir(dir_dsdl_vscode)
    _ensure_no_common_usage_errors(dir_dsdl, [Path("/baz")], reports.append)
    assert not reports  # Because the name is not valid.

    dir_dsdl_uavcan = os.path.join(dir_dsdl, "uavcan")
    os.mkdir(dir_dsdl_uavcan)
    _ensure_no_common_usage_errors(dir_dsdl, [Path("/baz")], reports.append)
    (rep,) = reports
    reports.clear()
    assert os.path.normcase(dir_dsdl_uavcan) in rep


def _unittest_nested_roots() -> None:
    from pytest import raises

    _ensure_no_nested_root_namespaces([])
    _ensure_no_nested_root_namespaces([Path("a")])
    _ensure_no_nested_root_namespaces([Path("a/b"), Path("a/c")])
    with raises(NestedRootNamespaceError):
        _ensure_no_nested_root_namespaces([Path("a/b"), Path("a")])
    _ensure_no_nested_root_namespaces([Path("aa/b"), Path("a")])
    _ensure_no_nested_root_namespaces([Path("a/b"), Path("aa")])


def _unittest_issue_71() -> None:  # https://github.com/OpenCyphal/pydsdl/issues/71
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        real = Path(directory, "real", "nested")
        real.mkdir(parents=True)
        link = Path(directory, "link")
        link.symlink_to(real, target_is_directory=True)
        (real / "Msg.0.1.dsdl").write_text("@sealed")
        assert len(read_namespace(real, [real, link])) == 1
        assert len(read_namespace(link, [real, link])) == 1
