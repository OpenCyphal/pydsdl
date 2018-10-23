#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
from .error import FileNameFormatError
from .data_type import Version


NAMESPACE_SEPARATOR = '.'


class DSDLDefinition:
    """
    A DSDL type definition source abstracts the filesystem level details away, presenting a higher-level
    interface that operates solely on the level of type names, namespaces, regulated identifiers, and so on.
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

        # Determining the relative path within the root namespace directory
        relative_path = str(os.path.relpath(self._file_path, root_namespace_path))
        relative_directory, basename = [str(x) for x in os.path.split(relative_path)]   # type: str, str
        assert os.path.join(root_namespace_path, relative_directory, basename) == self._file_path

        # Parsing the basename, e.g., 434.GetTransportStatistics.0.1.uavcan
        basename_components = basename.split('.')[:-1]
        str_regulated_port_id = None    # type: typing.Optional[str]
        if len(basename_components) == 4:
            str_regulated_port_id, short_name, str_major_version, str_minor_version = basename_components
        elif len(basename_components) == 3:
            short_name, str_major_version, str_minor_version = basename_components
        else:
            raise FileNameFormatError('Invalid file name', path=self._file_path)

        # Parsing the regulated port ID, if specified; None if not
        if str_regulated_port_id is not None:
            try:
                self._regulated_port_id = int(str_regulated_port_id)    # type: typing.Optional[int]
            except ValueError:
                raise FileNameFormatError('Could not parse the regulated port number', path=self._file_path) from None
        else:
            self._regulated_port_id = None

        # Parsing the version numbers
        try:
            self._version = Version(major=int(str_major_version),
                                    minor=int(str_minor_version))
        except ValueError:
                raise FileNameFormatError('Could not parse the version numbers', path=self._file_path) from None

        # Finally, constructing the name
        namespace_components = list(relative_directory.strip(os.sep).split(os.sep))
        self._name = NAMESPACE_SEPARATOR.join(namespace_components + [str(short_name)])

    @property
    def name(self) -> str:
        """The full name, e.g., uavcan.node.Heartbeat"""
        return self._name

    @property
    def name_components(self) -> typing.List[str]:
        """Components of the full name as a list, e.g., ['uavcan', 'node', 'Heartbeat']"""
        return self._name.split(NAMESPACE_SEPARATOR)

    @property
    def short_name(self) -> str:
        """The last component of the full name, e.g., Heartbeat of uavcan.node.Heartbeat"""
        return self.name_components[-1]

    @property
    def namespace(self) -> str:
        """The full name without the short name, e.g., uavcan.node for uavcan.node.Heartbeat"""
        return NAMESPACE_SEPARATOR.join(self.name_components[:-1])

    @property
    def root_namespace(self) -> str:
        """The first component of the full name, e.g., uavcan of uavcan.node.Heartbeat"""
        return self.name_components[-1]

    @property
    def text(self) -> str:
        """The source text in its raw unprocessed form (with comments, formatting intact, and everything)"""
        return self._text

    @property
    def version(self) -> Version:
        return self.version

    @property
    def regulated_port_id(self) -> typing.Optional[int]:
        """Either the regulated port ID as integer, or None if not defined for this type."""
        return self._regulated_port_id

    @property
    def has_regulated_port_id(self) -> bool:
        return self.regulated_port_id is not None

    @property
    def file_path(self) -> str:
        return self._file_path

    def __str__(self) -> str:
        return 'DSDLDefinition(name=%r, version=%r, regulated_port_id=%r, file_path=%r)' % \
            (self.name, self.version, self.regulated_port_id, self.file_path)

    __repr__ = __str__