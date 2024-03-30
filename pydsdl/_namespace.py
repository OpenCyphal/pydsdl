# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

# pylint: disable=logging-not-lazy

import collections
import logging
from pathlib import Path
from typing import Callable, DefaultDict, Dict, Iterable, List, Optional, Set, Tuple, Union, cast

from . import _dsdl_definition, _error, _serializable
from ._dsdl import DsdlFile, DsdlFileBuildable, PrintOutputHandler, SortedFileList
from ._dsdl import file_sort as dsdl_file_sort
from ._dsdl import normalize_paths_argument as dsdl_normalize_paths_argument
from ._dsdl import is_uniform_or_raise as dsdl_is_uniform_or_raise
from ._namespace_reader import Closure as NamespaceClosureReader


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


class DsdlPathInferenceError(_error.InvalidDefinitionError):
    """
    Raised when the namespace, type, fixed port ID, or version cannot be inferred from a file path.
    """


# +--[PUBLIC API]-----------------------------------------------------------------------------------------------------+


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
    # Normalize paths and remove duplicates. Resolve symlinks to avoid ambiguities.
    root_namespace_directory = Path(root_namespace_directory).resolve()

    lookup_directories_path_list = _construct_lookup_directories_path_list(
        [root_namespace_directory],
        dsdl_normalize_paths_argument(
            lookup_directories, cast(Callable[[Iterable], List[Path]], lambda i: [Path(it) for it in i])
        ),
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
        target_dsdl_definitions,
        lookup_directories_path_list,
        NamespaceClosureReader(allow_unregulated_fixed_port_id, print_output_handler),
    ).direct.types


# pylint: disable=too-many-arguments
def read_files(
    dsdl_files: Union[None, Path, str, Iterable[Union[Path, str]]],
    root_namespace_directories_or_names: Union[None, Path, str, Iterable[Union[Path, str]]],
    lookup_directories: Union[None, Path, str, Iterable[Union[Path, str]]] = None,
    print_output_handler: Optional[PrintOutputHandler] = None,
    allow_unregulated_fixed_port_id: bool = False,
    allow_root_namespace_name_collision: bool = True,
) -> Tuple[List[DsdlFile], List[DsdlFile]]:
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
    # Normalize paths and remove duplicates. Resolve symlinks to avoid ambiguities.
    target_dsdl_definitions = _construct_dsdl_definitions_from_files(
        dsdl_normalize_paths_argument(
            dsdl_files, cast(Callable[[Iterable], List[Path]], lambda i: [Path(it) for it in i])
        ),
        dsdl_normalize_paths_argument(
            root_namespace_directories_or_names,
            cast(Callable[[Iterable], Union[Set[Path], Set[str]]], set),
        ),
    )
    if len(target_dsdl_definitions) == 0:
        _logger.info("No DSDL files found in the specified directories")
        return ([], [])
    _logger.debug("Target DSDL definitions are listed below:")
    for x in target_dsdl_definitions:
        _logger.debug(_LOG_LIST_ITEM_PREFIX + str(x.file_path))

    root_namespaces = dsdl_file_sort({f.root_namespace.resolve() for f in target_dsdl_definitions})
    lookup_directories_path_list = _construct_lookup_directories_path_list(
        root_namespaces,
        dsdl_normalize_paths_argument(lookup_directories, cast(Callable[[Iterable], List[Path]], list)),
        allow_root_namespace_name_collision,
    )

    reader = _complete_read_function(
        target_dsdl_definitions,
        lookup_directories_path_list,
        NamespaceClosureReader(allow_unregulated_fixed_port_id, print_output_handler),
    )

    return (reader.direct.files, reader.transitive.files)


# +--[INTERNAL API::PUBLIC API HELPERS]-------------------------------------------------------------------------------+
# These are functions called by the public API before the actual processing begins.

DSDL_FILE_SUFFIX = ".dsdl"
DSDL_FILE_GLOB = f"*{DSDL_FILE_SUFFIX}"
DSDL_FILE_SUFFIX_LEGACY = ".uavcan"
DSDL_FILE_GLOB_LEGACY = f"*{DSDL_FILE_SUFFIX_LEGACY}"
_LOG_LIST_ITEM_PREFIX = " " * 4


def _complete_read_function(
    target_dsdl_definitions: SortedFileList, lookup_directories_path_list: List[Path], reader: NamespaceClosureReader
) -> NamespaceClosureReader:

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

    # This is the biggie. All the rest of the wranging is just to get to this point. This will take the
    # most time and memory.
    reader.read_definitions(target_dsdl_definitions, lookup_dsdl_definitions)

    # Note that we check for collisions in the read namespace only.
    # We intentionally ignore (do not check for) possible collisions in the lookup directories,
    # because that would exceed the expected scope of responsibility of the frontend, and the lookup
    # directories may contain issues and mistakes that are outside of the control of the user (e.g.,
    # they could be managed by a third party) -- the user shouldn't be affected by mistakes committed
    # by the third party.
    _ensure_no_fixed_port_id_collisions(reader.direct.types)
    _ensure_minor_version_compatibility(reader.all.types)

    return reader


def _construct_lookup_directories_path_list(
    root_namespace_directories: List[Path],
    lookup_directories_path_list: List[Path],
    allow_root_namespace_name_collision: bool,
) -> List[Path]:
    """
    Intermediate transformation and validation of inputs into a list of lookup directories as paths.

    :param root_namespace_directory: The path of the root namespace directory that will be read.
        For example, ``dsdl/uavcan`` to read the ``uavcan`` namespace.

    :param lookup_directories: List of other namespace directories containing data type definitions that are
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

    # Check the namespaces.
    _ensure_no_nested_root_namespaces(lookup_directories_path_list)

    if not allow_root_namespace_name_collision:
        _ensure_no_namespace_name_collisions(lookup_directories_path_list)

    return lookup_directories_path_list


def _construct_dsdl_definitions_from_files(
    dsdl_files: List[Path],
    valid_roots: Union[Set[Path], Set[str]],
) -> SortedFileList:
    """ """
    output = set()  # type:  Set[DsdlFileBuildable]
    for fp in dsdl_files:
        root_namespace_path = _infer_path_to_root(fp, valid_roots)
        if fp.suffix == DSDL_FILE_SUFFIX_LEGACY:
            _logger.warning(
                "File uses deprecated extension %r, please rename to use %r: %s",
                DSDL_FILE_SUFFIX_LEGACY,
                DSDL_FILE_SUFFIX,
                fp,
            )
        output.add(_dsdl_definition.DSDLDefinition(fp, root_namespace_path))

    return dsdl_file_sort(output)


def _construct_dsdl_definitions_from_namespaces(
    root_namespace_paths: List[Path],
) -> SortedFileList:
    """
    Accepts a directory path, returns a sorted list of abstract DSDL file representations. Those can be read later.
    The definitions are sorted by name lexicographically, then by major version (greatest version first),
    then by minor version (same ordering as the major version).
    """
    source_file_paths: Set[Path] = set()
    output = []  # type: List[DsdlFileBuildable]
    for root_namespace_path in root_namespace_paths:
        for p in root_namespace_path.rglob(DSDL_FILE_GLOB):
            source_file_paths.add(p)
        for p in root_namespace_path.rglob(DSDL_FILE_GLOB_LEGACY):
            source_file_paths.add(p)
            _logger.warning(
                "File uses deprecated extension %r, please rename to use %r: %s",
                DSDL_FILE_GLOB_LEGACY,
                DSDL_FILE_GLOB,
                p,
            )

        for fp in sorted(source_file_paths):
            dsdl_def = _dsdl_definition.DSDLDefinition(fp, root_namespace_path)
            output.append(dsdl_def)

    return dsdl_file_sort(output)


def _ensure_no_collisions(
    target_definitions: List[_dsdl_definition.DSDLDefinition],
    lookup_definitions: List[_dsdl_definition.DSDLDefinition],
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
    root_namespace_directories: List[Path], lookup_directories: Iterable[Path], reporter: Callable[[str], None]
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


def _ensure_no_nested_root_namespaces(directories: Iterable[Path]) -> None:
    dirs = {x.resolve() for x in directories}  # normalize the case in case-insensitive filesystems
    for a in dirs:
        for b in dirs:
            if a.samefile(b):
                continue
            try:
                a.relative_to(b)
            except ValueError:
                pass
            else:
                raise NestedRootNamespaceError(
                    "The following namespace is nested inside this one, which is not permitted: %s" % a, path=b
                )


def _ensure_no_namespace_name_collisions(directories: Iterable[Path]) -> None:
    directories = {x.resolve() for x in directories}  # normalize the case in case-insensitive filesystems
    for a in directories:
        for b in directories:
            if a.samefile(b):
                continue
            if a.name.lower() == b.name.lower():
                _logger.info("Collision: %r [%r] == %r [%r]", a, a.name, b, b.name)
                raise RootNamespaceNameCollisionError("The name of this namespace conflicts with %s" % b, path=a)


def _infer_path_to_root(
    dsdl_path: Path, valid_dsdl_roots_or_path_to_root: Optional[Union[Set[Path], Set[str]]] = None
) -> Path:
    """
    Infer the path to the namespace root of a DSDL file path.
    :param dsdl_path: The path to the alleged DSDL file.
    :param valid_dsdl_roots_or_path_to_root: The set of valid root names or paths under which the type must reside.
    :return The path to the root namespace directory.
    :raises DsdlPathInferenceError: If the namespace root cannot be inferred from the provided information.
    """
    if dsdl_path.is_absolute():
        if valid_dsdl_roots_or_path_to_root is None:
            raise DsdlPathInferenceError(
                f"dsdl_path ({dsdl_path}) is absolute and no valid root names or path to root was provided. The "
                "DSDL root of an absolute path cannot be inferred without this information.",
            )
        if len(valid_dsdl_roots_or_path_to_root) == 0:
            raise DsdlPathInferenceError(
                f"dsdl_path ({dsdl_path}) is absolute and the provided valid root names are empty. The DSDL root of "
                "an absolute path cannot be inferred without this information.",
            )
        if isinstance(next(iter(valid_dsdl_roots_or_path_to_root)), Path):
            valid_paths_to_root = cast(Set[Path], valid_dsdl_roots_or_path_to_root)
            for path_to_root in valid_paths_to_root:
                try:
                    _ = dsdl_path.relative_to(path_to_root)
                except ValueError:
                    continue
                return path_to_root
            raise DsdlPathInferenceError(
                f"dsdl_path ({dsdl_path}) is absolute but is not relative to "
                f"any provided path to root {valid_dsdl_roots_or_path_to_root}",
            )

    if (
        valid_dsdl_roots_or_path_to_root is not None
        and len(valid_dsdl_roots_or_path_to_root) > 0
        and isinstance(next(iter(valid_dsdl_roots_or_path_to_root)), str)
    ):
        valid_dsdl_roots = cast(Set[str], valid_dsdl_roots_or_path_to_root)
        parts = list(dsdl_path.parent.parts)
        namespace_parts = None
        for i, part in list(enumerate(parts)):
            if part in valid_dsdl_roots:
                namespace_parts = parts[i:]
                return Path().joinpath(*parts[: i + 1])
                # +1 to include the root folder
        if namespace_parts is None:
            raise DsdlPathInferenceError(f"No valid root found in path {str(dsdl_path)}")

    if not dsdl_path.is_absolute():
        return Path(dsdl_path.parts[0])

    raise DsdlPathInferenceError(f"Could not determine a path to the namespace root of dsdl path {dsdl_path}")


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
        lut = {x.full_name: x for x in dsdl_defs}  # type: Dict[str, _dsdl_definition.DSDLDefinition]
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

        reports = []  # type: List[str]

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
        _ensure_no_nested_root_namespaces([])
        _ensure_no_nested_root_namespaces([di / "a"])
        _ensure_no_nested_root_namespaces([di / "a/b", di / "a/c"])
        with raises(NestedRootNamespaceError):
            _ensure_no_nested_root_namespaces([di / "a/b", di / "a"])
        _ensure_no_nested_root_namespaces([di / "aa/b", di / "a"])
        _ensure_no_nested_root_namespaces([di / "a/b", di / "aa"])


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


def _unittest_type_from_path_inference() -> None:
    from pytest import raises as expect_raises

    # To determine the namespace do

    dsdl_file = Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl")
    path_to_root = _infer_path_to_root(dsdl_file, {"uavcan"})
    namespace_parts = dsdl_file.parent.relative_to(path_to_root.parent).parts

    assert path_to_root == Path("/repo/uavcan")
    assert namespace_parts == ("uavcan", "foo", "bar")

    # The root namespace cannot be inferred in an absolute path without additional data:

    with expect_raises(DsdlPathInferenceError):
        _ = _infer_path_to_root(Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl"))

    # If an absolute path is provided along with a path-to-root "hint" then the former must be relative to the
    # latter:

    # dsdl file path is not contained within the root path
    with expect_raises(DsdlPathInferenceError):
        _ = _infer_path_to_root(Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl"), {Path("/not-a-repo")})

    # This works
    root = _infer_path_to_root(Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl"), {Path("/repo")})
    assert root == Path("/repo")

    # Either relative or absolute paths given a set of valid root names will prefer searching for the root:

    valid_roots = {"uavcan", "cyphal"}

    # absolute dsdl path using valid roots
    root = _infer_path_to_root(Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl"), valid_roots)
    assert root == Path("/repo/uavcan")

    # relative dsdl path using valid roots
    root = _infer_path_to_root(Path("repo/uavcan/foo/bar/435.baz.1.0.dsdl"), valid_roots)
    assert root == Path("repo/uavcan")

    # absolute dsdl path using valid roots but an invalid file path
    with expect_raises(DsdlPathInferenceError):
        _ = _infer_path_to_root(Path("/repo/crap/foo/bar/435.baz.1.0.dsdl"), valid_roots)

    # relative dsdl path using valid roots but an invalid file path
    with expect_raises(DsdlPathInferenceError):
        _ = _infer_path_to_root(Path("repo/crap/foo/bar/435.baz.1.0.dsdl"), valid_roots)

    # The final inference made is when relative dsdl paths are provided with no additional information. In this
    # case the method assumes that the relative path is the correct and complete namespace of the type:

    # relative path
    root = _infer_path_to_root(Path("uavcan/foo/bar/435.baz.1.0.dsdl"))
    assert root == Path("uavcan")
