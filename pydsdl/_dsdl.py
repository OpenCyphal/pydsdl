# Copyright (C) OpenCyphal Development Team  <opencyphal.org>
# Copyright Amazon.com Inc. or its affiliates.
# SPDX-License-Identifier: MIT

from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar, List, Tuple

from ._serializable import CompositeType, Version

PrintOutputHandler = Callable[[Path, int, str], None]
"""Invoked when the frontend encounters a print directive or needs to output a generic diagnostic."""


class DSDLFile(ABC):
    """
    Interface for DSDL files. This interface is used by the parser to abstract DSDL type details inferred from the
    filesystem. Where properties are duplicated between the composite type and this file the composite type is to be
    considered canonical. The properties directly on this class are inferred from the dsdl file path before the
    composite type has been parsed.
    """

    @property
    @abstractmethod
    def composite_type(self) -> CompositeType | None:
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
    def fixed_port_id(self) -> int | None:
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


class ReadableDSDLFile(DSDLFile):
    """
    A DSDL file that can construct a composite type from its contents.
    """

    @abstractmethod
    def read(
        self,
        lookup_definitions: Iterable["ReadableDSDLFile"],
        definition_visitors: Iterable["DefinitionVisitor"],
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


class DefinitionVisitor(ABC):
    """
    A visitor that is notified about discovered dependencies.
    """

    @abstractmethod
    def on_definition(self, target_dsdl_file: DSDLFile, dependency_dsdl_file: ReadableDSDLFile) -> None:
        """
        Called by the parser after if finds a dependent type but before it parses a file in a lookup namespace.
        :param target_dsdl_file: The target DSDL file that has dependencies the parser is searching for.
        :param dependency_dsdl_file: The dependency of target_dsdl_file file the parser is about to parse.
        """
        raise NotImplementedError()


SortedFileT = TypeVar("SortedFileT", DSDLFile, ReadableDSDLFile, CompositeType)
SortedFileList = List[SortedFileT]
"""A list of DSDL files sorted by name, newest version first."""


def get_definition_ordering_rank(d: DSDLFile | CompositeType) -> Tuple[str, int, int]:
    return d.full_name, -d.version.major, -d.version.minor


def file_sort(file_list: Iterable[SortedFileT]) -> SortedFileList[SortedFileT]:
    """
    Sorts a list of DSDL files lexicographically by name, newest version first.
    """
    return list(sorted(file_list, key=get_definition_ordering_rank))


def normalize_paths_argument_to_list(namespaces_or_namespace: None | Path | str | Iterable[Path | str]) -> List[Path]:
    """
    Normalizes the input argument to a list of paths.
    """
    if namespaces_or_namespace is None:
        return []
    if isinstance(namespaces_or_namespace, (Path, str)):
        return [Path(namespaces_or_namespace)]

    def _convert(arg: Any) -> Path:
        if not isinstance(arg, (str, Path)):
            raise TypeError(f"Invalid type: {type(arg)}")
        return Path(arg) if isinstance(arg, str) else arg

    value_set = set()

    def _filter_duplicate_paths(arg: Any) -> bool:
        if arg in value_set:
            return False
        value_set.add(arg)
        return True

    converted = [_convert(arg) for arg in namespaces_or_namespace]
    return list(filter(_filter_duplicate_paths, converted))


# +-[UNIT TESTS]------------------------------------------------------------------------------------------------------+


def _unittest_dsdl_normalize_paths_argument_to_list() -> None:

    from pytest import raises as assert_raises

    # Test with None argument
    result = normalize_paths_argument_to_list(None)
    assert result == []

    # Test with single string argument
    result = normalize_paths_argument_to_list("path/to/namespace")
    assert result == [Path("path/to/namespace")]

    # Test with single Path argument
    result = normalize_paths_argument_to_list(Path("path/to/namespace"))
    assert result == [Path("path/to/namespace")]

    # Test with list of strings argument
    result = normalize_paths_argument_to_list(["path/to/namespace1", "path/to/namespace2"])
    assert result == [Path("path/to/namespace1"), Path("path/to/namespace2")]

    # Test with list of Path arguments
    result = normalize_paths_argument_to_list([Path("path/to/namespace1"), Path("path/to/namespace2")])
    assert result == [Path("path/to/namespace1"), Path("path/to/namespace2")]

    # Test with mixed list of strings and Path arguments
    result = normalize_paths_argument_to_list(["path/to/namespace1", Path("path/to/namespace2")])
    assert result == [Path("path/to/namespace1"), Path("path/to/namespace2")]

    # Test de-duplication
    result = normalize_paths_argument_to_list(["path/to/namespace1", "path/to/namespace1"])
    assert result == [Path("path/to/namespace1")]

    # Test with invalid argument type
    with assert_raises(TypeError):
        normalize_paths_argument_to_list(42)  # type: ignore

    # Test with invalid argument type
    with assert_raises(TypeError):
        normalize_paths_argument_to_list([42])  # type: ignore
