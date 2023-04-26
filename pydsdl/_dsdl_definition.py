# Copyright (c) 2018 OpenCyphal
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@opencyphal.org>

import time
from typing import Iterable, Callable, Optional, List
import logging
from pathlib import Path
from ._error import FrontendError, InvalidDefinitionError, InternalError
from ._serializable import CompositeType, Version
from . import _parser


_logger = logging.getLogger(__name__)


class FileNameFormatError(InvalidDefinitionError):
    """
    Raised when a DSDL definition file is named incorrectly.
    """

    def __init__(self, text: str, path: Path):
        super().__init__(text=text, path=Path(path))


class DSDLDefinition:
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
        with open(self._file_path) as f:
            self._text = str(f.read())

        # Checking the sanity of the root directory path - can't contain separators
        if CompositeType.NAME_COMPONENT_SEPARATOR in self._root_namespace_path.name:
            raise FileNameFormatError("Invalid namespace name", path=self._root_namespace_path)

        # Determining the relative path within the root namespace directory
        relative_path = self._root_namespace_path.name / self._file_path.relative_to(self._root_namespace_path)

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

    def read(
        self,
        lookup_definitions: Iterable["DSDLDefinition"],
        print_output_handler: Callable[[int, str], None],
        allow_unregulated_fixed_port_id: bool,
    ) -> CompositeType:
        """
        Reads the data type definition and returns its high-level data type representation.
        The output is cached; all following invocations will read from the cache.
        Caching is very important, because it is expected that the same definition may be referred to multiple
        times (e.g., for composition or when accessing external constants). Re-processing a definition every time
        it is accessed would be a huge waste of time.
        Note, however, that this may lead to unexpected complications if one is attempting to re-read a definition
        with different inputs (e.g., different lookup paths) expecting to get a different result: caching would
        get in the way. That issue is easy to avoid by creating a new instance of the object.
        :param lookup_definitions:              List of definitions available for referring to.
        :param print_output_handler:            Used for @print and for diagnostics: (line_number, text) -> None.
        :param allow_unregulated_fixed_port_id: Do not complain about fixed unregulated port IDs.
        :return: The data type representation.
        """
        log_prefix = "%s.%d.%d" % (self.full_name, self.version.major, self.version.minor)
        if self._cached_type is not None:
            _logger.debug("%s: Cache hit", log_prefix)
            return self._cached_type

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
            builder = _data_type_builder.DataTypeBuilder(
                definition=self,
                lookup_definitions=lookup_definitions,
                print_output_handler=print_output_handler,
                allow_unregulated_fixed_port_id=allow_unregulated_fixed_port_id,
            )
            with open(self.file_path) as f:
                _parser.parse(f.read(), builder)

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

    @property
    def full_name(self) -> str:
        """The full name, e.g., uavcan.node.Heartbeat"""
        return self._name

    @property
    def name_components(self) -> List[str]:
        """Components of the full name as a list, e.g., ['uavcan', 'node', 'Heartbeat']"""
        return self._name.split(CompositeType.NAME_COMPONENT_SEPARATOR)

    @property
    def short_name(self) -> str:
        """The last component of the full name, e.g., Heartbeat of uavcan.node.Heartbeat"""
        return self.name_components[-1]

    @property
    def full_namespace(self) -> str:
        """The full name without the short name, e.g., uavcan.node for uavcan.node.Heartbeat"""
        return str(CompositeType.NAME_COMPONENT_SEPARATOR.join(self.name_components[:-1]))

    @property
    def root_namespace(self) -> str:
        """The first component of the full name, e.g., uavcan of uavcan.node.Heartbeat"""
        return self.name_components[0]

    @property
    def text(self) -> str:
        """The source text in its raw unprocessed form (with comments, formatting intact, and everything)"""
        return self._text

    @property
    def version(self) -> Version:
        return self._version

    @property
    def fixed_port_id(self) -> Optional[int]:
        """Either the fixed port ID as integer, or None if not defined for this type."""
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


# Moved this import here to break recursive dependency.
# Maybe I have messed up the architecture? Should think about it later.
from . import _data_type_builder  # pylint: disable=wrong-import-position
