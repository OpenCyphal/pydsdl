# Copyright (C) OpenCyphal Development Team  <opencyphal.org>
# Copyright Amazon.com Inc. or its affiliates.
# SPDX-License-Identifier: MIT

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Set, Tuple, TypeVar, Union

from ._serializable import CompositeType, Version

PrintOutputHandler = Callable[[Path, int, str], None]
"""Invoked when the frontend encounters a print directive or needs to output a generic diagnostic."""


class DsdlFile(ABC):
    """
    Interface for DSDL files. This interface is used by the parser to abstract DSDL type details inferred from the
    filesystem. Where properties are duplicated between the composite type and this file the composite type is to be
    considered canonical. The properties directly on this class are inferred from the dsdl file path before the
    composite type has been parsed.
    """

    @property
    @abstractmethod
    def composite_type(self) -> Optional[CompositeType]:
        """The composite type that was read from the DSDL file or None if the type has not been parsed yet."""
        raise NotImplementedError()

    @property
    @abstractmethod
    def full_name(self) -> str:
        """The full name, e.g., uavcan.node.Heartbeat"""
        raise NotImplementedError()

    @property
    def name_components(self) -> List[str]:
        """Components of the full name as a list, e.g., ['uavcan', 'node', 'Heartbeat']"""
        raise NotImplementedError()

    @property
    @abstractmethod
    def short_name(self) -> str:
        """The last component of the full name, e.g., Heartbeat of uavcan.node.Heartbeat"""
        raise NotImplementedError()

    @property
    @abstractmethod
    def full_namespace(self) -> str:
        """The full name without the short name, e.g., uavcan.node for uavcan.node.Heartbeat"""
        raise NotImplementedError()

    @property
    @abstractmethod
    def root_namespace(self) -> str:
        """The first component of the full name, e.g., uavcan of uavcan.node.Heartbeat"""
        raise NotImplementedError()

    @property
    @abstractmethod
    def text(self) -> str:
        """The source text in its raw unprocessed form (with comments, formatting intact, and everything)"""
        raise NotImplementedError()

    @property
    @abstractmethod
    def version(self) -> Version:
        """
        The version of the DSDL definition.
        """
        raise NotImplementedError()

    @property
    @abstractmethod
    def fixed_port_id(self) -> Optional[int]:
        """Either the fixed port ID as integer, or None if not defined for this type."""
        raise NotImplementedError()

    @property
    @abstractmethod
    def has_fixed_port_id(self) -> bool:
        """
        If the type has a fixed port ID defined, this method returns True. Equivalent to ``fixed_port_id is not None``.
        """
        raise NotImplementedError()

    @property
    @abstractmethod
    def file_path(self) -> Path:
        """The path to the DSDL file on the filesystem."""
        raise NotImplementedError()

    @property
    @abstractmethod
    def root_namespace_path(self) -> Path:
        """
        The path to the root namespace directory on the filesystem.
        """
        raise NotImplementedError()


class DefinitionVisitor(ABC):
    """
    An interface that allows visitors to index dependent types of a target DSDL file. This allows visitors to
    build a closure of dependent types while parsing a set of target DSDL files.
    """

    @abstractmethod
    def on_discover_lookup_dependent_file(self, target_dsdl_file: DsdlFile, dependent_type: DsdlFile) -> None:
        """
        Called by the parser after if finds a dependent type but before it parses a file in a lookup namespace.
        :param DsdlFile target_dsdl_file: The target DSDL file that has dependencies the parser is searching for.
        :param DsdlFile dependent_type: The dependency of target_dsdl_file file the parser is about to parse.
        :raises DependentFileError: If the dependent file is not allowed by the visitor.
        """
        raise NotImplementedError()


class DsdlFileBuildable(DsdlFile):
    """
    A DSDL file that can construct a composite type from its contents.
    """

    @abstractmethod
    def read(
        self,
        lookup_definitions: Iterable["DsdlFileBuildable"],
        definition_visitors: Iterable[DefinitionVisitor],
        print_output_handler: Callable[[int, str], None],
        allow_unregulated_fixed_port_id: bool,
    ) -> CompositeType:
        """
        Reads the data type definition and returns its high-level data type representation.
        The output should be cached; all following invocations should read from this cache.
        Caching is very important, because it is expected that the same definition may be referred to multiple
        times (e.g., for composition or when accessing external constants). Re-processing a definition every time
        it is accessed would be a huge waste of time.
        Note, however, that this may lead to unexpected complications if one is attempting to re-read a definition
        with different inputs (e.g., different lookup paths) expecting to get a different result: caching would
        get in the way. That issue is easy to avoid by creating a new instance of the object.
        :param lookup_definitions:              List of definitions available for referring to.
        :param definition_visitors:             Visitors to notify about discovered dependencies.
        :param print_output_handler:            Used for @print and for diagnostics: (line_number, text) -> None.
        :param allow_unregulated_fixed_port_id: Do not complain about fixed unregulated port IDs.
        :return: The data type representation.
        """
        raise NotImplementedError()


SortedFileT = TypeVar("SortedFileT", DsdlFile, DsdlFileBuildable)
SortedFileList = List[SortedFileT]
"""A list of DSDL files sorted by name, newest version first."""

FileSortKey: Callable[[SortedFileT], Tuple[str, int, int]] = lambda d: (
    d.full_name,
    -d.version.major,
    -d.version.minor,
)


def file_sort(file_list: Iterable[SortedFileT]) -> SortedFileList:
    """
    Sorts a list of DSDL files lexicographically by name, newest version first.
    """
    return list(sorted(file_list, key=FileSortKey))


UniformCollectionT = TypeVar("UniformCollectionT", Iterable, Set, List)


def is_uniform_or_raise(collection: UniformCollectionT) -> UniformCollectionT:
    """
    Raises an error if the collection is not uniform.
    """
    first = type(next(iter(collection)))
    if not all(isinstance(x, first) for x in collection):
        raise TypeError(f"Not all items in collection were of type {str(first)}.")
    return collection


PathListT = TypeVar(
    "PathListT", List[Path], Set[Path], List[str], Set[str], Union[List[Path], List[str]], Union[Set[Path], Set[str]]
)


def normalize_paths_argument(
    namespaces_or_namespace: Union[None, Path, str, Iterable[Union[Path, str]]],
    type_cast: Callable[[Iterable], PathListT],
) -> PathListT:
    """
    Normalizes the input argument to a list of paths.
    """
    if namespaces_or_namespace is None:
        return type_cast([])
    if isinstance(namespaces_or_namespace, (Path, str)):
        return type_cast([Path(namespaces_or_namespace)])
    return is_uniform_or_raise(type_cast(namespaces_or_namespace))
