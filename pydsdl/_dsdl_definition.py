# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

import logging
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from . import _parser
from ._data_type_builder import DataTypeBuilder
from ._dsdl import DefinitionVisitor, DsdlFileBuildable
from ._error import FrontendError, InternalError, InvalidDefinitionError
from ._serializable import CompositeType, Version

_logger = logging.getLogger(__name__)


class FileNameFormatError(InvalidDefinitionError):
    """
    Raised when a DSDL definition file is named incorrectly.
    """

    def __init__(self, text: str, path: Path):
        super().__init__(text=text, path=Path(path))


class DSDLDefinition(DsdlFileBuildable):
    """
    A DSDL type definition source abstracts the filesystem level details away, presenting a higher-level
    interface that operates solely on the level of type names, namespaces, fixed identifiers, and so on.
    Upper layers that operate on top of this abstraction do not concern themselves with the file system at all.
    """

    def __init__(self, file_path: Path, root_namespace_path: Path):
        # Normalizing the path and reading the definition text
        self._file_path = Path(file_path)
        del file_path
        self._root_namespace_path = Path(root_namespace_path)
        del root_namespace_path
        self._text: Optional[str] = None

        # Checking the sanity of the root directory path - can't contain separators
        if CompositeType.NAME_COMPONENT_SEPARATOR in self._root_namespace_path.name:
            raise FileNameFormatError("Invalid namespace name", path=self._root_namespace_path)

        # Determining the relative path within the root namespace directory
        try:
            relative_path = self._root_namespace_path.name / self._file_path.relative_to(self._root_namespace_path)
        except ValueError:
            # the file is not under the same root path so we'll have to make an assumption that the
            relative_path = Path(self._root_namespace_path.name) / self._file_path.name

        # Parsing the basename, e.g., 434.GetTransportStatistics.0.1.dsdl
        basename_components = relative_path.name.split(".")[:-1]
        str_fixed_port_id: Optional[str] = None
        if len(basename_components) == 4:
            str_fixed_port_id, short_name, str_major_version, str_minor_version = basename_components
        elif len(basename_components) == 3:
            short_name, str_major_version, str_minor_version = basename_components
        else:
            raise FileNameFormatError("Invalid file name", path=self._file_path)

        # Parsing the fixed port ID, if specified; None if not
        if str_fixed_port_id is not None:
            try:
                self._fixed_port_id: Optional[int] = int(str_fixed_port_id)
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

        self._cached_type: Optional[CompositeType] = None

    # +-----------------------------------------------------------------------+
    # | DsdlFileBuildable :: INTERFACE                                        |
    # +-----------------------------------------------------------------------+
    def read(
        self,
        lookup_definitions: Iterable[DsdlFileBuildable],
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
    # | DsdlFile :: INTERFACE                                                 |
    # +-----------------------------------------------------------------------+
    @property
    def composite_type(self) -> Optional[CompositeType]:
        return self._cached_type

    @property
    def full_name(self) -> str:
        return self._name

    @property
    def name_components(self) -> List[str]:
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
    def fixed_port_id(self) -> Optional[int]:
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

    def get_composite_type(self) -> CompositeType:
        if self._cached_type is None:
            raise InvalidDefinitionError("The definition has not been read yet", self.file_path)
        return self._cached_type

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


def _unittest_dsdl_definition_read_non_existant() -> None:
    from pytest import raises as expect_raises

    target = Path("root", "ns", "Target.1.1.dsdl")
    target_definition = DSDLDefinition(target, target.parent)

    def print_output(line_number: int, text: str) -> None:
        pass

    with expect_raises(InvalidDefinitionError):
        target_definition.read([], [], print_output, True)


def _unittest_dsdl_definition_read_text(temp_dsdl_factory) -> None:  # type: ignore
    target_root = Path("root", "ns")
    target_file_path = Path(target_root / "Target.1.1.dsdl")
    dsdl_file = temp_dsdl_factory.new_file(target_root / target_file_path, "@sealed")
    target_definition = DSDLDefinition(dsdl_file, target_root)
    assert "@sealed" == target_definition.text
