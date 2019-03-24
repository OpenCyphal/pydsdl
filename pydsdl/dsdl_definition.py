#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
from . import error
from . import data_type
from . import parser


class FileNameFormatError(error.InvalidDefinitionError):
    """
    Raised when a DSDL definition file is named incorrectly.
    """
    def __init__(self, text: str, path: str):
        super(FileNameFormatError, self).__init__(text=text, path=str(path))


class DSDLDefinition:
    """
    A DSDL type definition source abstracts the filesystem level details away, presenting a higher-level
    interface that operates solely on the level of type names, namespaces, fixed identifiers, and so on.
    Upper layers that operate on top of this abstraction do not concern themselves with the file system at all.
    """

    def __init__(self,
                 file_path: str,
                 root_namespace_path: str):
        # Normalizing the path and reading the definition text
        self._file_path = os.path.abspath(file_path)
        root_namespace_path = os.path.abspath(root_namespace_path)
        with open(self._file_path) as f:
            self._text = str(f.read())

        # Checking the sanity of the root directory path - can't contain separators
        if data_type.CompoundType.NAME_COMPONENT_SEPARATOR in os.path.split(root_namespace_path)[-1]:
            raise FileNameFormatError('Invalid namespace name', path=root_namespace_path)

        # Determining the relative path within the root namespace directory
        relative_path = str(os.path.join(os.path.split(root_namespace_path)[-1],
                                         os.path.relpath(self._file_path, root_namespace_path)))

        relative_directory, basename = [str(x) for x in os.path.split(relative_path)]   # type: str, str

        # Parsing the basename, e.g., 434.GetTransportStatistics.0.1.uavcan
        basename_components = basename.split('.')[:-1]
        str_fixed_port_id = None    # type: typing.Optional[str]
        if len(basename_components) == 4:
            str_fixed_port_id, short_name, str_major_version, str_minor_version = basename_components
        elif len(basename_components) == 3:
            short_name, str_major_version, str_minor_version = basename_components
        else:
            raise FileNameFormatError('Invalid file name', path=self._file_path)

        # Parsing the fixed port ID, if specified; None if not
        if str_fixed_port_id is not None:
            try:
                self._fixed_port_id = int(str_fixed_port_id)    # type: typing.Optional[int]
            except ValueError:
                raise FileNameFormatError('Could not parse the fixed port ID', path=self._file_path) from None
        else:
            self._fixed_port_id = None

        # Parsing the version numbers
        try:
            self._version = data_type.Version(major=int(str_major_version),
                                              minor=int(str_minor_version))
        except ValueError:
            raise FileNameFormatError('Could not parse the version numbers', path=self._file_path) from None

        # Finally, constructing the name
        namespace_components = list(relative_directory.strip(os.sep).split(os.sep))
        for nc in namespace_components:
            if data_type.CompoundType.NAME_COMPONENT_SEPARATOR in nc:
                raise FileNameFormatError('Invalid name for namespace component', path=self._file_path)

        self._name = data_type.CompoundType.NAME_COMPONENT_SEPARATOR\
            .join(namespace_components + [str(short_name)])  # type: str

        self._cached_type = None    # type: typing.Optional[data_type.CompoundType]

    def read(self,
             lookup_definitions:              typing.Iterable['DSDLDefinition'],
             print_output_handler:            typing.Callable[[int, str], None],
             allow_unregulated_fixed_port_id: bool) -> data_type.CompoundType:
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
        if self._cached_type is not None:
            return self._cached_type

        # Remove the target definition from the lookup list in order to prevent
        # infinite recursion on self-referential definitions.
        lookup_definitions = list(filter(lambda d: d != self, lookup_definitions))
        try:
            # We have to import this class at function level to break recursive dependency.
            # Maybe I have messed up the architecture? Should think about it later.
            from .data_type_builder import DataTypeBuilder
            builder = DataTypeBuilder(definition=self,
                                      lookup_definitions=lookup_definitions,
                                      print_output_handler=print_output_handler,
                                      allow_unregulated_fixed_port_id=allow_unregulated_fixed_port_id)
            with open(self.file_path) as f:
                parser.parse(f.read(), builder)

            self._cached_type = builder.finalize()
            return self._cached_type
        except error.FrontendError as ex:                      # pragma: no cover
            ex.set_error_location_if_unknown(path=self.file_path)
            raise ex
        except Exception as ex:                                         # pragma: no cover
            raise error.InternalError(culprit=ex, path=self.file_path)

    @property
    def full_name(self) -> str:
        """The full name, e.g., uavcan.node.Heartbeat"""
        return self._name

    @property
    def name_components(self) -> typing.List[str]:
        """Components of the full name as a list, e.g., ['uavcan', 'node', 'Heartbeat']"""
        return self._name.split(data_type.CompoundType.NAME_COMPONENT_SEPARATOR)

    @property
    def short_name(self) -> str:
        """The last component of the full name, e.g., Heartbeat of uavcan.node.Heartbeat"""
        return self.name_components[-1]

    @property
    def full_namespace(self) -> str:
        """The full name without the short name, e.g., uavcan.node for uavcan.node.Heartbeat"""
        return str(data_type.CompoundType.NAME_COMPONENT_SEPARATOR.join(self.name_components[:-1]))

    @property
    def root_namespace(self) -> str:
        """The first component of the full name, e.g., uavcan of uavcan.node.Heartbeat"""
        return self.name_components[0]

    @property
    def text(self) -> str:
        """The source text in its raw unprocessed form (with comments, formatting intact, and everything)"""
        return self._text

    @property
    def version(self) -> data_type.Version:
        return self._version

    @property
    def fixed_port_id(self) -> typing.Optional[int]:
        """Either the fixed port ID as integer, or None if not defined for this type."""
        return self._fixed_port_id

    @property
    def has_fixed_port_id(self) -> bool:
        return self.fixed_port_id is not None

    @property
    def file_path(self) -> str:
        return self._file_path

    def __eq__(self, other: object) -> bool:
        """
        Two definitions will compare equal if they share the same name AND version number.
        Definitions of the same name but different versions are not considered equal.
        """
        if isinstance(other, DSDLDefinition):
            return self.full_name == other.full_name and self.version == other.version
        else:  # pragma: no cover
            return NotImplemented

    def __str__(self) -> str:
        return 'DSDLDefinition(full_name=%r, version=%r, fixed_port_id=%r, file_path=%r)' % \
            (self.full_name, self.version, self.fixed_port_id, self.file_path)

    __repr__ = __str__
