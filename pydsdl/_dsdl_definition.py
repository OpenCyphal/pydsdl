# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

from __future__ import annotations
import logging
import time
from pathlib import Path
from typing import Callable, Iterable, Type

from . import _parser
from ._data_type_builder import DataTypeBuilder, UndefinedDataTypeError
from ._dsdl import DefinitionVisitor, ReadableDSDLFile
from ._error import FrontendError, InternalError, InvalidDefinitionError
from ._serializable import CompositeType, Version

_logger = logging.getLogger(__name__)


class FileNameFormatError(InvalidDefinitionError):
    """
    Raised when a DSDL definition file is named incorrectly.
    """

    def __init__(self, text: str, path: Path):
        super().__init__(text=text, path=Path(path))


class PathInferenceError(UndefinedDataTypeError):
    """
    Raised when the namespace, type, fixed port ID, or version cannot be inferred from a file path.
    """

    def __init__(self, text: str, dsdl_path: Path, valid_dsdl_roots: list[Path]):
        super().__init__(text=text, path=Path(dsdl_path))
        self.valid_dsdl_roots = valid_dsdl_roots[:] if valid_dsdl_roots is not None else None


class DSDLDefinition(ReadableDSDLFile):
    """
    A DSDL type definition source abstracts the filesystem level details away, presenting a higher-level
    interface that operates solely on the level of type names, namespaces, fixed identifiers, and so on.
    Upper layers that operate on top of this abstraction do not concern themselves with the file system at all.

    :param file_path: The path to the DSDL file.
    :param root_namespace_path: The path to the root namespace directory. `file_path` must be a descendant of this path.
                                See `from_first_in` for a more flexible way to create a DSDLDefinition object.
    """

    @classmethod
    def _infer_path_to_root_from_first_found(cls, dsdl_path: Path, valid_dsdl_roots: list[Path]) -> Path:
        """
        See `from_first_in` for documentation on this logic.
        :return The path to the root namespace directory.
        """
        if valid_dsdl_roots is None:
            raise ValueError("valid_dsdl_roots was None")

        if dsdl_path.is_absolute() and len(valid_dsdl_roots) == 0:
            raise PathInferenceError(
                f"dsdl_path ({dsdl_path}) is absolute and the provided valid root names are empty. The DSDL root of "
                "an absolute path cannot be inferred without this information.",
                dsdl_path,
                valid_dsdl_roots,
            )

        if len(valid_dsdl_roots) == 0:
            # if we have no valid roots we can only infer the root of the path. We require the path to be relative
            # to avoid accidental inferences given that dsdl file trees starting from a filesystem root are rare.
            return Path(dsdl_path.parts[0])

        # INFERENCE 1: The strongest inference is when the path is relative to a known root.
        resolved_dsdl_path = dsdl_path.resolve(strict=False) if dsdl_path.is_absolute() else None
        for path_to_root in valid_dsdl_roots:
            # First we try the paths as-is...
            try:
                _ = dsdl_path.relative_to(path_to_root)
            except ValueError:
                pass
            else:
                return path_to_root
            # then we try resolving the root path if it is absolute
            if path_to_root.is_absolute() and resolved_dsdl_path is not None:
                path_to_root_resolved = path_to_root.resolve(strict=False)
                try:
                    _ = resolved_dsdl_path.relative_to(path_to_root_resolved).parent
                except ValueError:
                    pass
                else:
                    return path_to_root_resolved

        # INFERENCE 2: A weaker, but valid inference is when the path is a child of a known root folder name.
        root_parts = [x.parts[-1] for x in valid_dsdl_roots if len(x.parts) == 1]
        parts = list(dsdl_path.parent.parts)
        for i, part in list(enumerate(parts)):
            if part in root_parts:
                return Path().joinpath(*parts[: i + 1])
                # +1 to include the root folder
        raise PathInferenceError(f"No valid root found in path {str(dsdl_path)}", dsdl_path, valid_dsdl_roots)

    @classmethod
    def from_first_in(cls: Type["DSDLDefinition"], dsdl_path: Path, valid_dsdl_roots: list[Path]) -> "DSDLDefinition":
        """
        Creates a DSDLDefinition object by inferring the path to the namespace root of a DSDL file given a set
        of valid roots. The logic used prefers an instance of dsdl_path found to exist under a valid root but
        will degrade to pure-path string matching if no file is found. Because this logic uses the first root path
        that passes one of these two inferences the order of the valid_dsdl_roots list matters.

        :param dsdl_path:           The path to the alleged DSDL file.
        :param valid_dsdl_roots:    The ordered set of valid root names or paths under which the type must reside.
                                    This argument is accepted as a list for ordering but no de-duplication is performed
                                    as the caller is expected to provide a correct set of paths.
        :return A new DSDLDefinition object
        :raises PathInferenceError: If the namespace root cannot be inferred from the provided information.
        """
        return cls(dsdl_path, cls._infer_path_to_root_from_first_found(dsdl_path, valid_dsdl_roots))

    def __init__(self, file_path: Path, root_namespace_path: Path):
        """ """
        # Normalizing the path and reading the definition text
        self._file_path = Path(file_path)
        del file_path
        self._root_namespace_path = Path(root_namespace_path)
        del root_namespace_path
        self._text: str | None = None

        # Checking the sanity of the root directory path - can't contain separators
        if CompositeType.NAME_COMPONENT_SEPARATOR in self._root_namespace_path.name:
            raise FileNameFormatError("Invalid namespace name", path=self._root_namespace_path)

        relative_path = self._root_namespace_path.name / self._file_path.relative_to(self._root_namespace_path)

        # Parsing the basename, e.g., 434.GetTransportStatistics.0.1.dsdl
        basename_components = relative_path.name.split(".")[:-1]
        str_fixed_port_id: str | None = None
        if len(basename_components) == 4:
            str_fixed_port_id, short_name, str_major_version, str_minor_version = basename_components
        elif len(basename_components) == 3:
            short_name, str_major_version, str_minor_version = basename_components
        else:
            raise FileNameFormatError("Invalid file name", path=self._file_path)

        # Parsing the fixed port ID, if specified; None if not
        if str_fixed_port_id is not None:
            try:
                self._fixed_port_id: int | None = int(str_fixed_port_id)
            except ValueError:
                raise FileNameFormatError(
                    "Not a valid fixed port-ID: %s. "
                    "Namespaces are defined as directories; putting the namespace name in the file name will not work. "
                    'For example: "foo/Bar.1.0.dsdl" is OK (where "foo" is a directory); "foo.Bar.1.0.dsdl" is not.'
                    % str_fixed_port_id,
                    path=self._file_path,
                ) from None
        else:
            self._fixed_port_id = None

        # Parsing the version numbers
        try:
            self._version = Version(major=int(str_major_version), minor=int(str_minor_version))
        except ValueError:
            raise FileNameFormatError("Could not parse the version numbers", path=self._file_path) from None

        # Finally, constructing the name
        namespace_components = list(relative_path.parent.parts)
        for nc in namespace_components:
            if CompositeType.NAME_COMPONENT_SEPARATOR in nc:
                raise FileNameFormatError(f"Invalid name for namespace component: {nc!r}", path=self._file_path)
        self._name: str = CompositeType.NAME_COMPONENT_SEPARATOR.join(namespace_components + [str(short_name)])

        self._cached_type: CompositeType | None = None

    # +-----------------------------------------------------------------------+
    # | ReadableDSDLFile :: INTERFACE                                        |
    # +-----------------------------------------------------------------------+
    def read(
        self,
        lookup_definitions: Iterable[ReadableDSDLFile],
        definition_visitors: Iterable[DefinitionVisitor],
        print_output_handler: Callable[[int, str], None],
        allow_unregulated_fixed_port_id: bool,
    ) -> CompositeType:
        log_prefix = "%s.%d.%d" % (self.full_name, self.version.major, self.version.minor)
        if self._cached_type is not None:
            _logger.debug("%s: Cache hit", log_prefix)
            return self._cached_type

        if not self._file_path.exists():
            raise InvalidDefinitionError("Attempt to read DSDL file that doesn't exist.", self._file_path)

        started_at = time.monotonic()

        # Remove the target definition from the lookup list in order to prevent
        # infinite recursion on self-referential definitions.
        lookup_definitions = list(filter(lambda d: d != self, lookup_definitions))

        _logger.debug(
            "%s: Starting processing with %d lookup definitions located in root namespaces: %s",
            log_prefix,
            len(lookup_definitions),
            ", ".join(set(sorted(map(lambda x: x.root_namespace, lookup_definitions)))),
        )
        try:
            builder = DataTypeBuilder(
                definition=self,
                lookup_definitions=lookup_definitions,
                definition_visitors=definition_visitors,
                print_output_handler=print_output_handler,
                allow_unregulated_fixed_port_id=allow_unregulated_fixed_port_id,
            )

            _parser.parse(self.text, builder)

            self._cached_type = builder.finalize()
            _logger.info(
                "%s: Processed in %.0f ms; category: %s, fixed port ID: %s",
                log_prefix,
                (time.monotonic() - started_at) * 1e3,
                type(self._cached_type).__name__,
                self._cached_type.fixed_port_id,
            )
            return self._cached_type
        except FrontendError as ex:  # pragma: no cover
            ex.set_error_location_if_unknown(path=self.file_path)
            raise ex
        except (MemoryError, SystemError):  # pragma: no cover
            raise
        except Exception as ex:  # pragma: no cover
            raise InternalError(culprit=ex, path=self.file_path) from ex

    # +-----------------------------------------------------------------------+
    # | DSDLFile :: INTERFACE                                                 |
    # +-----------------------------------------------------------------------+
    @property
    def composite_type(self) -> CompositeType | None:
        return self._cached_type

    @property
    def full_name(self) -> str:
        return self._name

    @property
    def name_components(self) -> list[str]:
        return self._name.split(CompositeType.NAME_COMPONENT_SEPARATOR)

    @property
    def short_name(self) -> str:
        return self.name_components[-1]

    @property
    def full_namespace(self) -> str:
        return str(CompositeType.NAME_COMPONENT_SEPARATOR.join(self.name_components[:-1]))

    @property
    def root_namespace(self) -> str:
        return self.name_components[0]

    @property
    def text(self) -> str:
        if self._text is None:
            with open(self._file_path) as f:
                self._text = str(f.read())
        return self._text

    @property
    def version(self) -> Version:
        return self._version

    @property
    def fixed_port_id(self) -> int | None:
        return self._fixed_port_id

    @property
    def has_fixed_port_id(self) -> bool:
        return self.fixed_port_id is not None

    @property
    def file_path(self) -> Path:
        return self._file_path

    @property
    def root_namespace_path(self) -> Path:
        return self._root_namespace_path

    # +-----------------------------------------------------------------------+
    # | Python :: SPECIAL FUNCTIONS                                           |
    # +-----------------------------------------------------------------------+
    def __hash__(self) -> int:
        return hash((self.full_name, self.version))

    def __eq__(self, other: object) -> bool:
        """
        Two definitions will compare equal if they share the same name AND version number.
        Definitions of the same name but different versions are not considered equal.
        """
        if isinstance(other, DSDLDefinition):
            return self.full_name == other.full_name and self.version == other.version
        return NotImplemented  # pragma: no cover

    def __str__(self) -> str:
        return "DSDLDefinition(full_name=%r, version=%r, fixed_port_id=%r, file_path=%s)" % (
            self.full_name,
            self.version,
            self.fixed_port_id,
            self.file_path,
        )

    __repr__ = __str__


# +-[UNIT TESTS]------------------------------------------------------------------------------------------------------+


def _unittest_dsdl_definition_read_non_existent() -> None:
    from pytest import raises as expect_raises

    target = Path("root", "ns", "Target.1.1.dsdl")
    target_definition = DSDLDefinition(target, target.parent)

    def print_output(line_number: int, text: str) -> None:  # pragma: no cover
        _ = line_number, text

    with expect_raises(InvalidDefinitionError):
        target_definition.read([], [], print_output, True)


def _unittest_dsdl_definition_read_text(temp_dsdl_factory) -> None:  # type: ignore
    from pytest import raises as expect_raises

    target_root = Path("root", "ns")
    target_file_path = Path(target_root / "Target.1.1.dsdl")
    dsdl_file = temp_dsdl_factory.new_file(target_root / target_file_path, "@sealed")
    with expect_raises(ValueError):
        _target_definition = DSDLDefinition(dsdl_file, target_root)
        # we test first that we can't create the object until we have a target_root that contains the dsdl_file

    target_definition = DSDLDefinition(dsdl_file, dsdl_file.parent.parent)
    assert "@sealed" == target_definition.text


def _unittest_type_from_path_inference() -> None:
    from pytest import raises as expect_raises

    # pylint: disable=protected-access

    dsdl_file = Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl").resolve()
    path_to_root = DSDLDefinition._infer_path_to_root_from_first_found(dsdl_file, [Path("/repo/uavcan").resolve()])
    namespace_parts = dsdl_file.parent.relative_to(path_to_root.parent).parts

    assert path_to_root == Path("/repo/uavcan").resolve()
    assert namespace_parts == ("uavcan", "foo", "bar")

    # The simplest inference made is when relative dsdl paths are provided with no additional information. In this
    # case the method assumes that the relative path is the correct and complete namespace of the type:

    # relative path
    root = DSDLDefinition._infer_path_to_root_from_first_found(Path("uavcan/foo/bar/435.baz.1.0.dsdl"), [])
    assert root == Path("uavcan")

    # The root namespace is not inferred in an absolute path without additional data:

    with expect_raises(PathInferenceError):
        _ = DSDLDefinition._infer_path_to_root_from_first_found(
            Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl").resolve(), []
        )

    with expect_raises(ValueError):
        _ = DSDLDefinition._infer_path_to_root_from_first_found(
            Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl").resolve(), None  # type: ignore
        )

    # If an absolute path is provided along with a path-to-root "hint" then the former must be relative to the
    # latter:

    # dsdl file path is not contained within the root path
    with expect_raises(PathInferenceError):
        _ = DSDLDefinition._infer_path_to_root_from_first_found(
            Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl").resolve(), [Path("/not-a-repo").resolve()]
        )

    root = DSDLDefinition._infer_path_to_root_from_first_found(
        Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl").resolve(), [Path("/repo/uavcan").resolve()]
    )
    assert root == Path("/repo/uavcan").resolve()

    # The priority is given to paths that are relative to the root when both simple root names and paths are provided:
    root = DSDLDefinition._infer_path_to_root_from_first_found(
        Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl").resolve(), [Path("foo"), Path("/repo/uavcan").resolve()]
    )
    assert root == Path("/repo/uavcan").resolve()

    root = DSDLDefinition._infer_path_to_root_from_first_found(
        Path("repo/uavcan/foo/bar/435.baz.1.0.dsdl"), [Path("foo"), Path("repo/uavcan")]
    )
    assert root == Path("repo/uavcan")

    # Finally, the method will infer the root namespace from simple folder names if no additional information is
    # provided:

    valid_roots = [Path("uavcan"), Path("cyphal")]

    # absolute dsdl path using valid roots
    root = DSDLDefinition._infer_path_to_root_from_first_found(
        Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl").resolve(), valid_roots
    )
    assert root == Path("/repo/uavcan").resolve()

    # relative dsdl path using valid roots
    root = DSDLDefinition._infer_path_to_root_from_first_found(
        Path("repo/uavcan/foo/bar/435.baz.1.0.dsdl"), valid_roots
    )
    assert root == Path("repo/uavcan")

    # absolute dsdl path using valid roots but an invalid file path
    with expect_raises(PathInferenceError):
        _ = DSDLDefinition._infer_path_to_root_from_first_found(
            Path("/repo/crap/foo/bar/435.baz.1.0.dsdl").resolve(), valid_roots
        )

    # relative dsdl path using valid roots but an invalid file path
    with expect_raises(PathInferenceError):
        _ = DSDLDefinition._infer_path_to_root_from_first_found(Path("repo/crap/foo/bar/435.baz.1.0.dsdl"), valid_roots)

    # relative dsdl path with invalid root fragments
    invalid_root_fragments = [Path("cyphal", "acme")]
    with expect_raises(PathInferenceError):
        _ = DSDLDefinition._infer_path_to_root_from_first_found(
            Path("repo/crap/foo/bar/435.baz.1.0.dsdl"), invalid_root_fragments
        )

    # In this example, foo/bar might look like a valid root path but it is not relative to repo/uavcan/foo/bar and is
    # not considered after relative path inference has failed because it is not a simple root name.
    root = DSDLDefinition._infer_path_to_root_from_first_found(
        Path("repo/uavcan/foo/bar/435.baz.1.0.dsdl"), [Path("foo/bar"), Path("foo")]
    )
    assert root == Path("repo/uavcan/foo")

    # when foo/bar is placed within the proper, relative path it is considered as a valid root and is preferred over
    # the simple root name "foo":
    root = DSDLDefinition._infer_path_to_root_from_first_found(
        Path("repo/uavcan/foo/bar/435.baz.1.0.dsdl"), [Path("repo/uavcan/foo/bar"), Path("foo")]
    )
    assert root == Path("repo/uavcan/foo/bar")

    # Sometimes the root paths have crap in them and need to be resolved:

    root = DSDLDefinition._infer_path_to_root_from_first_found(
        Path("/path/to/repo/uavcan/foo/bar/435.baz.1.0.dsdl").resolve(),
        [Path("/path/to/repo/uavcan/../uavcan").resolve()],
    )
    assert root == Path("/path/to/repo/uavcan").resolve()

    # Let's ensure ordering here

    root = DSDLDefinition._infer_path_to_root_from_first_found(
        Path("repo/uavcan/foo/bar/435.baz.1.0.dsdl"), [Path("repo/uavcan"), Path("repo/uavcan/foo")]
    )
    assert root == Path("repo/uavcan")


def _unittest_from_first_in() -> None:
    dsdl_def = DSDLDefinition.from_first_in(
        Path("/repo/uavcan/foo/bar/435.baz.1.0.dsdl").resolve(), [Path("/repo/uavcan/foo/..").resolve()]
    )
    assert dsdl_def.full_name == "uavcan.foo.bar.baz"
