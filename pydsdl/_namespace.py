# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

# pylint: disable=logging-not-lazy

from __future__ import annotations
import collections
import logging
from itertools import product, repeat
from pathlib import Path
from typing import Callable, DefaultDict, Iterable

from . import _dsdl_definition, _error, _serializable
from ._dsdl import ReadableDSDLFile, PrintOutputHandler, SortedFileList
from ._dsdl import file_sort as dsdl_file_sort
from ._dsdl import normalize_paths_argument_to_list
from ._namespace_reader import DSDLDefinitions, read_definitions

_logger = logging.getLogger(__name__)


class RootNamespaceNameCollisionError(_error.InvalidDefinitionError):
    """
    Raised when there is more than one namespace under the same name.
    This may occur if there are identically named namespaces located in different directories.
    """


class DataTypeCollisionError(_error.InvalidDefinitionError):
    """
    Raised when there are conflicting data type definitions.
    """


class DataTypeNameCollisionError(DataTypeCollisionError):
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


# +--[PUBLIC API]-----------------------------------------------------------------------------------------------------+


def read_namespace(
    root_namespace_directory: Path | str,
    lookup_directories: None | Path | str | Iterable[Path | str] = None,
    print_output_handler: PrintOutputHandler | None = None,
    allow_unregulated_fixed_port_id: bool = False,
    allow_root_namespace_name_collision: bool = True,
) -> list[_serializable.CompositeType]:
    """
    This function is a main entry point for the library.
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

    :return: A list of :class:`pydsdl.CompositeType` found under the `root_namespace_directory` and sorted
             lexicographically by full data type name, then by major version (newest version first), then by minor
             version (newest version first). The ordering guarantee allows the caller to always find the newest version
             simply by picking the first matching occurrence.

    :raises: :class:`pydsdl.FrontendError`, :class:`MemoryError`, :class:`SystemError`,
        :class:`OSError` if directories do not exist or inaccessible,
        :class:`ValueError`/:class:`TypeError` if the arguments are invalid.
    """
    # Normalize paths and remove duplicates. Resolve symlinks to avoid ambiguities.
    root_namespace_directory = Path(root_namespace_directory).resolve()

    lookup_directories_path_list = _construct_lookup_directories_path_list(
        [root_namespace_directory],
        normalize_paths_argument_to_list(lookup_directories),
        allow_root_namespace_name_collision,
    )

    # Construct DSDL definitions from the target and the lookup dirs.
    target_dsdl_definitions = _construct_dsdl_definitions_from_namespaces([root_namespace_directory])
    if not target_dsdl_definitions:
        _logger.info("The namespace at %s is empty", root_namespace_directory)
        return []
    _logger.debug("Target DSDL definitions are listed below:")
    for x in target_dsdl_definitions:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(x))

    return _complete_read_function(
        target_dsdl_definitions, lookup_directories_path_list, print_output_handler, allow_unregulated_fixed_port_id
    ).direct


# pylint: disable=too-many-arguments
def read_files(
    dsdl_files: None | Path | str | Iterable[Path | str],
    root_namespace_directories_or_names: None | Path | str | Iterable[Path | str],
    lookup_directories: None | Path | str | Iterable[Path | str] = None,
    print_output_handler: PrintOutputHandler | None = None,
    allow_unregulated_fixed_port_id: bool = False,
) -> tuple[list[_serializable.CompositeType], list[_serializable.CompositeType]]:
    """
    This function is a main entry point for the library.
    It reads all DSDL definitions from the specified ``dsdl_files`` and produces the annotated AST for these types and
    the transitive closure of the types they depend on.

    :param dsdl_files: A list of paths to dsdl files to parse.

    :param root_namespace_directories_or_names: This can be a set of names of root namespaces or relative paths to
        root namespaces. All ``dsdl_files`` provided must be under one of these roots. For example, given:

        .. code-block:: python

            dsdl_files = [
                            Path("workspace/project/types/animals/felines/Tabby.1.0.dsdl"),
                            Path("workspace/project/types/animals/canines/Boxer.1.0.dsdl"),
                            Path("workspace/project/types/plants/trees/DouglasFir.1.0.dsdl")
                         ]


        then this argument must be one of:

        .. code-block:: python

            root_namespace_directories_or_names = ["animals", "plants"]

            root_namespace_directories_or_names = [
                                                    Path("workspace/project/types/animals"),
                                                    Path("workspace/project/types/plants")
                                                  ]


    :param lookup_directories: List of other namespace directories containing data type definitions that are
        referred to from the target dsdl files. For example, if you are reading vendor-specific types,
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

    :return: A Tuple of lists of :class:`pydsdl.CompositeType`. The first index in the Tuple are the types parsed from
        the ``dsdl_files`` argument. The second index are types that the target ``dsdl_files`` utilizes.
        A note for using these values to describe build dependencies: each :class:`pydsdl.CompositeType` has two
        fields that provide links back to the filesystem where the dsdl files were located when parsing the type;
        ``source_file_path`` and ``source_file_path_to_root``.

    :raises: :class:`pydsdl.FrontendError`, :class:`MemoryError`, :class:`SystemError`,
        :class:`OSError` if directories do not exist or inaccessible,
        :class:`ValueError`/:class:`TypeError` if the arguments are invalid.
    """
    # Normalize paths and remove duplicates. Resolve symlinks to avoid ambiguities.
    target_dsdl_definitions = _construct_dsdl_definitions_from_files(
        normalize_paths_argument_to_list(dsdl_files),
        normalize_paths_argument_to_list(root_namespace_directories_or_names),
    )
    if len(target_dsdl_definitions) == 0:
        _logger.info("No DSDL files found in the specified directories")
        return ([], [])

    if _logger.isEnabledFor(logging.DEBUG):  # pragma: no cover
        _logger.debug("Target DSDL definitions are listed below:")

        for x in target_dsdl_definitions:
            _logger.debug(_LOG_LIST_ITEM_PREFIX + str(x.file_path))

    root_namespaces = {f.root_namespace_path.resolve() for f in target_dsdl_definitions}
    lookup_directories_path_list = _construct_lookup_directories_path_list(
        root_namespaces,
        normalize_paths_argument_to_list(lookup_directories),
        True,
    )

    definitions = _complete_read_function(
        target_dsdl_definitions, lookup_directories_path_list, print_output_handler, allow_unregulated_fixed_port_id
    )

    return (definitions.direct, definitions.transitive)


# +--[INTERNAL API::PUBLIC API HELPERS]-------------------------------------------------------------------------------+
# These are functions called by the public API before the actual processing begins.

DSDL_FILE_SUFFIX = ".dsdl"
DSDL_FILE_GLOB = f"*{DSDL_FILE_SUFFIX}"
DSDL_FILE_SUFFIX_LEGACY = ".uavcan"
DSDL_FILE_GLOB_LEGACY = f"*{DSDL_FILE_SUFFIX_LEGACY}"
_LOG_LIST_ITEM_PREFIX = " " * 4


def _complete_read_function(
    target_dsdl_definitions: SortedFileList[ReadableDSDLFile],
    lookup_directories_path_list: list[Path],
    print_output_handler: PrintOutputHandler | None,
    allow_unregulated_fixed_port_id: bool,
) -> DSDLDefinitions:

    lookup_dsdl_definitions = _construct_dsdl_definitions_from_namespaces(lookup_directories_path_list)

    # Check for collisions against the lookup definitions also.
    _ensure_no_collisions(target_dsdl_definitions, lookup_dsdl_definitions)

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

    # This is the biggie. All the rest of the wrangling is just to get to this point. This will take the
    # most time and memory.
    definitions = read_definitions(
        target_dsdl_definitions, lookup_dsdl_definitions, print_output_handler, allow_unregulated_fixed_port_id
    )

    # Note that we check for collisions in the read namespace only.
    # We intentionally ignore (do not check for) possible collisions in the lookup directories,
    # because that would exceed the expected scope of responsibility of the frontend, and the lookup
    # directories may contain issues and mistakes that are outside of the control of the user (e.g.,
    # they could be managed by a third party) -- the user shouldn't be affected by mistakes committed
    # by the third party.
    _ensure_no_fixed_port_id_collisions(definitions.direct)
    _ensure_minor_version_compatibility(definitions.transitive + definitions.direct)

    return definitions


def _construct_lookup_directories_path_list(
    root_namespace_directories: Iterable[Path],
    lookup_directories_path_list: list[Path],
    allow_root_namespace_name_collision: bool,
) -> list[Path]:
    """
    Intermediate transformation and validation of inputs into a list of lookup directories as paths.

    :param root_namespace_directories: The path of the root namespace directory that will be read.
        For example, ``dsdl/uavcan`` to read the ``uavcan`` namespace.

    :param lookup_directories_path_list: List of other namespace directories containing data type definitions that are
        referred to from the target root namespace. For example, if you are reading a vendor-specific namespace,
        the list of lookup directories should always include a path to the standard root namespace ``uavcan``,
        otherwise the types defined in the vendor-specific namespace won't be able to use data types from the
        standard namespace.

    :param allow_root_namespace_name_collision: Allow using the source root namespace name in the look up dirs or
             the same root namespace name multiple times in the lookup dirs. This will enable defining a namespace
             partially and let other entities define new messages or new sub-namespaces in the same root namespace.

    :return: A list of lookup directories as paths.

    :raises: :class:`pydsdl.FrontendError`, :class:`MemoryError`, :class:`SystemError`,
        :class:`OSError` if directories do not exist or inaccessible,
        :class:`ValueError`/:class:`TypeError` if the arguments are invalid.
    """
    # Add the own root namespace to the set of lookup directories, sort lexicographically, remove duplicates.
    # We'd like this to be an iterable list of strings but we handle the common practice of passing in a single path.

    # Normalize paths and remove duplicates. Resolve symlinks to avoid ambiguities.
    lookup_directories_path_list.extend(root_namespace_directories)
    lookup_directories_path_list = list(sorted({x.resolve() for x in lookup_directories_path_list}))
    _logger.debug("Lookup directories are listed below:")
    for a in lookup_directories_path_list:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(a))

    # Check for common usage errors and warn the user if anything looks suspicious.
    _ensure_no_common_usage_errors(root_namespace_directories, lookup_directories_path_list, _logger.warning)

    # Check the namespaces and ensure that there are no name collisions.
    _ensure_no_namespace_name_collisions_or_nested_root_namespaces(
        lookup_directories_path_list, allow_root_namespace_name_collision
    )

    return lookup_directories_path_list


def _construct_dsdl_definitions_from_files(
    dsdl_files: list[Path],
    valid_roots: list[Path],
) -> SortedFileList[ReadableDSDLFile]:
    """ """
    output = set()  # type:  set[ReadableDSDLFile]
    for fp in dsdl_files:
        resolved_fp = fp.resolve(strict=False)
        if resolved_fp.suffix == DSDL_FILE_SUFFIX_LEGACY:
            _logger.warning(
                "File uses deprecated extension %r, please rename to use %r: %s",
                DSDL_FILE_SUFFIX_LEGACY,
                DSDL_FILE_SUFFIX,
                resolved_fp,
            )
        output.add(_dsdl_definition.DSDLDefinition.from_first_in(resolved_fp, list(valid_roots)))

    return dsdl_file_sort(output)


def _construct_dsdl_definitions_from_namespaces(
    root_namespace_paths: list[Path],
) -> SortedFileList[ReadableDSDLFile]:
    """
    Accepts a directory path, returns a sorted list of abstract DSDL file representations. Those can be read later.
    The definitions are sorted by name lexicographically, then by major version (greatest version first),
    then by minor version (same ordering as the major version).
    """
    source_file_paths: set[tuple[Path, Path]] = set()  # index of all file paths already found
    for root_namespace_path in root_namespace_paths:
        for p in root_namespace_path.rglob(DSDL_FILE_GLOB):
            source_file_paths.add((p, root_namespace_path))
        for p in root_namespace_path.rglob(DSDL_FILE_GLOB_LEGACY):
            source_file_paths.add((p, root_namespace_path))
            _logger.warning(
                "File uses deprecated extension %r, please rename to use %r: %s",
                DSDL_FILE_GLOB_LEGACY,
                DSDL_FILE_GLOB,
                p,
            )

    return dsdl_file_sort([_dsdl_definition.DSDLDefinition(*p) for p in source_file_paths])


def _ensure_no_collisions(
    target_definitions: list[ReadableDSDLFile],
    lookup_definitions: list[ReadableDSDLFile],
) -> None:
    for tg in target_definitions:
        tg_full_namespace_period = tg.full_namespace.lower() + "."
        tg_full_name_period = tg.full_name.lower() + "."
        for lu in lookup_definitions:
            lu_full_namespace_period = lu.full_namespace.lower() + "."
            lu_full_name_period = lu.full_name.lower() + "."
            # This is to allow the following messages to coexist happily:
            #   zubax/non_colliding/iceberg/Ice.0.1.dsdl
            #   zubax/non_colliding/IceB.0.1.dsdl
            # The following is still not allowed:
            #   zubax/colliding/iceberg/Ice.0.1.dsdl
            #   zubax/colliding/Iceberg.0.1.dsdl
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
            if (
                tg_full_name_period == lu_full_name_period
                and tg.version == lu.version
                and not tg.file_path.samefile(lu.file_path)
            ):  # https://github.com/OpenCyphal/pydsdl/issues/94
                raise DataTypeCollisionError("This type is redefined in %s" % lu.file_path, path=tg.file_path)


def _ensure_no_fixed_port_id_collisions(types: list[_serializable.CompositeType]) -> None:
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


def _ensure_minor_version_compatibility(types: list[_serializable.CompositeType]) -> None:
    by_name = collections.defaultdict(list)  # type: DefaultDict[str, list[_serializable.CompositeType]]
    for t in types:
        by_name[t.full_name].append(t)

    for definitions in by_name.values():
        by_major = collections.defaultdict(list)  # type: DefaultDict[int, list[_serializable.CompositeType]]
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
    assert a.full_name == b.full_name
    assert a.version.major == b.version.major
    assert a.version.minor != b.version.minor  # This is the whole point of this function.

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
    root_namespace_directories: Iterable[Path], lookup_directories: Iterable[Path], reporter: Callable[[str], None]
) -> None:
    suspicious_base_names = [
        "public_regulated_data_types",
        "dsdl",
    ]

    def is_valid_name(s: str) -> bool:
        try:
            _serializable.check_name(s)
        except _error.InvalidDefinitionError:
            return False
        else:
            return True

    # resolve() will also normalize the case in case-insensitive filesystems.
    all_paths = {y.resolve() for y in root_namespace_directories} | {x.resolve() for x in lookup_directories}
    for p in all_paths:
        try:
            candidates = [x for x in p.iterdir() if x.is_dir() and is_valid_name(x.name)]
        except OSError:  # pragma: no cover
            candidates = []
        if candidates and p.name in suspicious_base_names:
            report = (
                "Possibly incorrect usage detected: input path %s is likely incorrect because the last path component "
                "should be the root namespace name rather than its parent directory. You probably meant:\n%s"
            ) % (
                p,
                "\n".join(("- %s" % (p / s)) for s in candidates),
            )
            reporter(report)


def _ensure_no_namespace_name_collisions_or_nested_root_namespaces(
    directories: Iterable[Path], allow_name_collisions: bool
) -> None:
    directories = {x.resolve() for x in directories}  # normalize the case in case-insensitive filesystems

    def check_each(path_tuple_with_result: tuple[tuple[Path, Path], list[int]]) -> bool:
        path_tuple = path_tuple_with_result[0]
        if not path_tuple[0].samefile(path_tuple[1]):
            if not allow_name_collisions and path_tuple[0].name.lower() == path_tuple[1].name.lower():
                return True
            try:
                path_tuple[0].relative_to(path_tuple[1])
            except ValueError:
                pass
            else:
                path_tuple_with_result[1][0] = 1
                return True
        return False

    # zip a list[1] of int 0 so we can assign a failure type. 0 is name collision and 1 is nested root namespace
    # further cartesian checks can be added here using this pattern

    # next/filter returns the first failure or None if no failures
    check_result = next(filter(check_each, zip(product(directories, directories), repeat([0]))), None)

    if check_result:
        path_tuple = check_result[0]
        failure_type = check_result[1][0]
        if failure_type == 0:
            raise RootNamespaceNameCollisionError(
                "The following namespaces have the same name: %s" % path_tuple[0], path=path_tuple[1]
            )
        else:
            raise NestedRootNamespaceError(
                "The following namespace is nested inside this one, which is not permitted: %s" % path_tuple[0],
                path=path_tuple[1],
            )


# +--[ UNIT TESTS ]---------------------------------------------------------------------------------------------------+


def _unittest_dsdl_definition_constructor() -> None:
    import tempfile

    from ._dsdl_definition import FileNameFormatError

    with tempfile.TemporaryDirectory() as directory:
        di = Path(directory).resolve()
        root = di / "foo"
        (root / "nested").mkdir(parents=True)

        (root / "123.Qwerty.123.234.dsdl").write_text("# TEST A")
        (root / "nested/2.Asd.21.32.dsdl").write_text("# TEST B")
        (root / "nested/Foo.32.43.dsdl").write_text("# TEST C")

        dsdl_defs = _construct_dsdl_definitions_from_namespaces([root])
        print(dsdl_defs)
        lut = {x.full_name: x for x in dsdl_defs}  # type: dict[str, ReadableDSDLFile]
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
        assert t.file_path == root / "123.Qwerty.123.234.dsdl"
        assert t.has_fixed_port_id
        assert t.fixed_port_id == 123
        assert t.text == "# TEST A"
        assert t.version.major == 123
        assert t.version.minor == 234
        assert t.name_components == ["foo", "Qwerty"]
        assert t.short_name == "Qwerty"
        assert t.root_namespace == "foo"
        assert t.full_namespace == "foo"

        t = lut["foo.nested.Asd"]
        assert t.file_path == root / "nested" / "2.Asd.21.32.dsdl"
        assert t.has_fixed_port_id
        assert t.fixed_port_id == 2
        assert t.text == "# TEST B"
        assert t.version.major == 21
        assert t.version.minor == 32
        assert t.name_components == ["foo", "nested", "Asd"]
        assert t.short_name == "Asd"
        assert t.root_namespace == "foo"
        assert t.full_namespace == "foo.nested"

        t = lut["foo.nested.Foo"]
        assert t.file_path == root / "nested" / "Foo.32.43.dsdl"
        assert not t.has_fixed_port_id
        assert t.fixed_port_id is None
        assert t.text == "# TEST C"
        assert t.version.major == 32
        assert t.version.minor == 43
        assert t.name_components == ["foo", "nested", "Foo"]
        assert t.short_name == "Foo"
        assert t.root_namespace == "foo"
        assert t.full_namespace == "foo.nested"

        (root / "nested/Malformed.MAJOR.MINOR.dsdl").touch()
        try:
            _construct_dsdl_definitions_from_namespaces([root])
        except FileNameFormatError as ex:
            print(ex)
            (root / "nested/Malformed.MAJOR.MINOR.dsdl").unlink()
        else:  # pragma: no cover
            assert False

        (root / "nested/NOT_A_NUMBER.Malformed.1.0.dsdl").touch()
        try:
            _construct_dsdl_definitions_from_namespaces([root])
        except FileNameFormatError as ex:
            print(ex)
            (root / "nested/NOT_A_NUMBER.Malformed.1.0.dsdl").unlink()
        else:  # pragma: no cover
            assert False

        (root / "nested/Malformed.dsdl").touch()
        try:
            _construct_dsdl_definitions_from_namespaces([root])
        except FileNameFormatError as ex:
            print(ex)
            (root / "nested/Malformed.dsdl").unlink()
        else:  # pragma: no cover
            assert False

        _construct_dsdl_definitions_from_namespaces([root])  # making sure all errors are cleared

        (root / "nested/super.bad").mkdir()
        (root / "nested/super.bad/Unreachable.1.0.dsdl").touch()
        try:
            _construct_dsdl_definitions_from_namespaces([root])
        except FileNameFormatError as ex:
            print(ex)
        else:  # pragma: no cover
            assert False

        try:
            _construct_dsdl_definitions_from_namespaces([root / "nested/super.bad"])
        except FileNameFormatError as ex:
            print(ex)
        else:  # pragma: no cover
            assert False

        (root / "nested/super.bad/Unreachable.1.0.dsdl").unlink()


def _unittest_dsdl_definition_constructor_legacy() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        di = Path(directory).resolve()
        root = di / "foo"
        root.mkdir()
        (root / "123.Qwerty.123.234.uavcan").write_text("# TEST A")
        dsdl_defs = _construct_dsdl_definitions_from_namespaces([root])
        print(dsdl_defs)
        lut = {x.full_name: x for x in dsdl_defs}  # type: dict[str, ReadableDSDLFile]
        assert len(lut) == 1
        t = lut["foo.Qwerty"]
        assert t.file_path == root / "123.Qwerty.123.234.uavcan"
        assert t.has_fixed_port_id
        assert t.fixed_port_id == 123
        assert t.text == "# TEST A"
        assert t.version.major == 123
        assert t.version.minor == 234
        assert t.name_components == ["foo", "Qwerty"]
        assert t.short_name == "Qwerty"
        assert t.root_namespace == "foo"
        assert t.full_namespace == "foo"


def _unittest_common_usage_errors() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        di = Path(directory)
        root_ns_dir = di / "foo"
        root_ns_dir.mkdir()

        reports = []  # type: list[str]

        _ensure_no_common_usage_errors([root_ns_dir], [], reports.append)
        assert not reports
        _ensure_no_common_usage_errors([root_ns_dir], [di / "baz"], reports.append)
        assert not reports

        dir_dsdl = root_ns_dir / "dsdl"
        dir_dsdl.mkdir()
        _ensure_no_common_usage_errors([dir_dsdl], [di / "baz"], reports.append)
        assert not reports  # Because empty.

        dir_dsdl_vscode = dir_dsdl / ".vscode"
        dir_dsdl_vscode.mkdir()
        _ensure_no_common_usage_errors([dir_dsdl], [di / "baz"], reports.append)
        assert not reports  # Because the name is not valid.

        dir_dsdl_uavcan = dir_dsdl / "uavcan"
        dir_dsdl_uavcan.mkdir()
        _ensure_no_common_usage_errors([dir_dsdl], [di / "baz"], reports.append)
        (rep,) = reports
        reports.clear()
        assert str(dir_dsdl_uavcan.resolve()).lower() in rep.lower()


def _unittest_nested_roots() -> None:
    import tempfile

    from pytest import raises

    with tempfile.TemporaryDirectory() as directory:
        di = Path(directory)
        (di / "a").mkdir()
        (di / "aa").mkdir()
        (di / "a/b").mkdir()
        (di / "a/c").mkdir()
        (di / "aa/b").mkdir()
        _ensure_no_namespace_name_collisions_or_nested_root_namespaces([], True)
        _ensure_no_namespace_name_collisions_or_nested_root_namespaces([di / "a"], True)
        _ensure_no_namespace_name_collisions_or_nested_root_namespaces([di / "a/b", di / "a/c"], True)
        with raises(NestedRootNamespaceError):
            _ensure_no_namespace_name_collisions_or_nested_root_namespaces([di / "a/b", di / "a"], True)
        _ensure_no_namespace_name_collisions_or_nested_root_namespaces([di / "aa/b", di / "a"], True)
        _ensure_no_namespace_name_collisions_or_nested_root_namespaces([di / "a/b", di / "aa"], True)


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


def _unittest_type_read_files_example(temp_dsdl_factory) -> None:  # type: ignore
    # let's test the comments for the read function
    dsdl_files = [
        Path("workspace/project/types/animals/felines/Tabby.1.0.uavcan"),  # keep .uavcan to cover the warning
        Path("workspace/project/types/animals/canines/Boxer.1.0.dsdl"),
        Path("workspace/project/types/plants/trees/DouglasFir.1.0.dsdl"),
    ]

    dsdl_files_abs = []
    root_namespace_paths = set()
    for dsdl_file in dsdl_files:
        dsdl_files_abs.append(temp_dsdl_factory.new_file(dsdl_file, "@sealed"))
        root_namespace_paths.add(temp_dsdl_factory.base_dir / dsdl_file.parent.parent)
    root_namespace_directories_or_names_simple = ["animals", "plants"]

    direct, transitive = read_files(dsdl_files_abs, root_namespace_directories_or_names_simple)

    assert len(direct) == len(dsdl_files)
    assert len(transitive) == 0

    for direct_type in direct:
        assert direct_type.root_namespace in root_namespace_directories_or_names_simple
        assert direct_type.source_file_path_to_root in root_namespace_paths

    direct, _ = read_files(dsdl_files_abs, root_namespace_paths)

    assert len(direct) == len(dsdl_files)

    for direct_type in direct:
        assert direct_type.root_namespace in root_namespace_directories_or_names_simple
        assert direct_type.source_file_path_to_root in root_namespace_paths


def _unittest_targets_found_in_lookup_namespaces(temp_dsdl_factory) -> None:  # type: ignore

    # call read_files with a list of dsdl files which are also located in the provided lookup namespaces

    plant_1_0 = Path("types/plants/Plant.1.0.dsdl")
    tree_1_0 = Path("types/plants/trees/Tree.1.0.dsdl")
    douglas_fir_1_0 = Path("types/plants/trees/DouglasFir.1.0.dsdl")

    plant_file = temp_dsdl_factory.new_file(plant_1_0, "@sealed\n")
    test_files = [
        temp_dsdl_factory.new_file(tree_1_0, "@sealed\nplants.Plant.1.0 plt\n"),
        temp_dsdl_factory.new_file(douglas_fir_1_0, "@sealed\nplants.trees.Tree.1.0 tree\n"),
    ]
    lookup_dirs = [plant_file.parent]

    direct, transitive = read_files(test_files, lookup_dirs)

    assert len(direct) == len(test_files)
    assert len(transitive) == 1


def _unittest_read_files_empty_args() -> None:
    direct, transitive = read_files([], [])

    assert len(direct) == 0
    assert len(transitive) == 0


def _unittest_ensure_no_collisions(temp_dsdl_factory) -> None:  # type: ignore
    from pytest import raises as expect_raises

    _ = temp_dsdl_factory

    # gratuitous coverage of the collision check where other tests don't cover some edge cases
    _ensure_no_namespace_name_collisions_or_nested_root_namespaces([], False)

    with expect_raises(DataTypeNameCollisionError):
        _ensure_no_collisions(
            [_dsdl_definition.DSDLDefinition(Path("a/b.1.0.dsdl"), Path("a"))],
            [_dsdl_definition.DSDLDefinition(Path("a/B.1.0.dsdl"), Path("a"))],
        )

    with expect_raises(DataTypeNameCollisionError):
        _ensure_no_collisions(
            [_dsdl_definition.DSDLDefinition(Path("a/b/c.1.0.dsdl"), Path("a"))],
            [_dsdl_definition.DSDLDefinition(Path("a/b.1.0.dsdl"), Path("a"))],
        )
