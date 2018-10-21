#
# Copyright (C) 2018  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import enum
from .data_type import CompoundType


MAX_NAME_LENGTH = 63        # Defined by the specification

MAX_VERSION_NUMBER = 255    # Defined by the specification

STANDARD_NAMESPACE_NAME = 'uavcan'
NAMESPACE_SEPARATOR = '.'


Version = typing.NamedTuple('Version', [('minor', int), ('major', int)])


class CommunicationPrimitiveOrigin(enum.Enum):
    STANDARD = 0
    VENDOR   = 1


class CommunicationPrimitiveKind(enum.Enum):
    SERVICE = 0
    MESSAGE = 1


class CommunicationPrimitiveDefinition:
    def __init__(self,
                 name: str,
                 version: Version,
                 static_port_id: typing.Optional[int],
                 deprecated: bool,
                 source_text: str):
        self._name = str(name).strip()
        self._version = version
        self._static_port_id = None if static_port_id is None else int(static_port_id)
        self._deprecated = bool(deprecated)
        self._source_text = str(source_text)

        if not self._name:
            raise ValueError('Name cannot be empty')

        if len(self._name) > MAX_NAME_LENGTH:
            raise ValueError('Name is too long: %r is longer than %d characters' %
                             (self._name, MAX_NAME_LENGTH))

        version_valid = (0 <= self._version.major <= MAX_VERSION_NUMBER) and\
                        (0 <= self._version.minor <= MAX_VERSION_NUMBER) and\
                        ((self._version.major + self._version.minor) > 0)

        if not version_valid:
            raise ValueError('Invalid version numbers: %r', self._version)

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> Version:
        return self._version

    @property
    def static_port_id(self) -> typing.Optional[int]:
        return self._static_port_id

    @property
    def deprecated(self) -> bool:
        return self._deprecated

    @property
    def source_text(self) -> str:
        return self._source_text

    @property
    def origin(self) -> CommunicationPrimitiveOrigin:
        if self._name.startswith(STANDARD_NAMESPACE_NAME + NAMESPACE_SEPARATOR):
            return CommunicationPrimitiveOrigin.STANDARD
        else:
            return CommunicationPrimitiveOrigin.VENDOR

    @property
    def kind(self) -> CommunicationPrimitiveKind:
        raise NotImplementedError


class MessageDefinition(CommunicationPrimitiveDefinition):
    def __init__(self, name: str, compound_type: CompoundType):
        super(MessageDefinition, self).__init__(name)

    @property
    def kind(self) -> CommunicationPrimitiveKind:
        return CommunicationPrimitiveKind.MESSAGE


class ServiceDefinition(CommunicationPrimitiveDefinition):
    def __init__(self, name: str, request_type: CompoundType, response_type: CompoundType):
        super(ServiceDefinition, self).__init__(name)

    @property
    def kind(self) -> CommunicationPrimitiveKind:
        return CommunicationPrimitiveKind.SERVICE
