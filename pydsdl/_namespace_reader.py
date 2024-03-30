# Copyright (C) OpenCyphal Development Team  <opencyphal.org>
# Copyright Amazon.com Inc. or its affiliates.
# SPDX-License-Identifier: MIT


import logging
from functools import partial
from pathlib import Path
from typing import List, Optional, Set

from ._dsdl import (
    DefinitionVisitor,
    DsdlFile,
    DsdlFileBuildable,
    PrintOutputHandler,
    SortedFileList,
    file_sort as dsdl_file_sort,
)
from ._error import DependentFileError, FrontendError, InternalError
from ._serializable import CompositeType


class FilesContainer:

    def __init__(self) -> None:
        self._files: SortedFileList = []
        self._files_index: Set[DsdlFile] = set()
        self._types_cache: Optional[List[CompositeType]] = None

    @property
    def files(self) -> SortedFileList:
        return self._files

    @property
    def types(self) -> List[CompositeType]:
        if self._types_cache is None:
            self._types_cache = [f.composite_type for f in self._files if f.composite_type is not None]
        return self._types_cache

    def __contains__(self, file: DsdlFile) -> bool:
        return file in self._files_index


class MutableFilesContainer(FilesContainer):

    def add(self, file: DsdlFile) -> None:
        if file not in self._files_index:
            # TODO: Didn't realize that python 3.8 didn't have the key parameter for bisect
            # I meant to keep this list sorted. I'll have to fix this later.
            self._files.append(file)
            self._files_index.add(file)
            self._types_cache = None

    def append(self, files: Set[DsdlFile]) -> None:
        for file in files:
            self.add(file)

    def clear(self) -> None:
        self._files = []
        self._files_index.clear()
        self._types_cache = None

    def remove_if(self, file: DsdlFile) -> None:
        if file in self._files_index:
            self._files.remove(file)
            self._files_index.remove(file)
            self._types_cache = None

    def union(self, other: FilesContainer) -> FilesContainer:
        union_files = MutableFilesContainer()
        # pylint: disable=protected-access
        union_files._files_index = self._files_index.union(other._files_index)
        union_files._files = dsdl_file_sort(union_files._files_index)
        return union_files


class Closure(DefinitionVisitor):

    @staticmethod
    def print_output_to_debug_logger(logger: logging.Logger, path: Path, line_number: int, text: str) -> None:
        logger.debug("%s:%d – %s", str(path), line_number, text)

    def __init__(
        self,
        allow_unregulated_fixed_port_id: bool,
        print_output_handler: Optional[PrintOutputHandler],
    ):
        self._logger = logging.getLogger(__name__)
        self._allow_unregulated_fixed_port_id = allow_unregulated_fixed_port_id
        self._print_output_handler = print_output_handler or partial(
            logging.getLogger(f"{__name__}.print_output_handler").debug, self.print_output_to_debug_logger
        )

        self._pending_definitions: Set[DsdlFileBuildable] = set()
        self._direct = MutableFilesContainer()
        self._transitive = MutableFilesContainer()

    # +--[DefinitionVisitor]------------------------------------------------------------------------------------------+
    def on_discover_lookup_dependent_file(self, target_dsdl_file: DsdlFile, dependent_type: DsdlFile) -> None:
        if not isinstance(dependent_type, DsdlFileBuildable):
            raise DependentFileError(f"Dependent file is not buildable: {dependent_type.file_path}")
        self._pending_definitions.add(dependent_type)

    # --[PUBLIC]------------------------------------------------------------------------------------------------------+
    @property
    def direct(self) -> FilesContainer:
        return self._direct

    @property
    def transitive(self) -> FilesContainer:
        return self._transitive

    @property
    def all(self) -> FilesContainer:
        return self._direct.union(self._transitive)

    def read_definitions(
        self,
        target_definitions: SortedFileList,
        lookup_definitions: SortedFileList,
    ) -> None:
        self._read_definitions(target_definitions, lookup_definitions, 0)

    # --[PRIVATE]-----------------------------------------------------------------------------------------------------+
    def _read_definitions(
        self, target_definitions: SortedFileList, lookup_definitions: SortedFileList, level: int
    ) -> None:

        for target_definition in target_definitions:
            self._pending_definitions.clear()
            if target_definition in (self._direct, self._transitive):
                self._logger.debug(
                    "Skipping target file %s because it has already been processed", target_definition.file_path
                )
                continue
            if not isinstance(target_definition, DsdlFileBuildable):
                raise TypeError("Expected DsdlFileBuildable, got: " + type(target_definition).__name__)
            try:
                target_definition.read(
                    lookup_definitions,
                    [self],
                    partial(self._print_output_handler, target_definition),
                    self._allow_unregulated_fixed_port_id,
                )
            except DependentFileError:
                self._logger.debug("Skipping target file %s due to dependent file error", target_definition.file_path)
            except FrontendError as ex:  # pragma: no cover
                ex.set_error_location_if_unknown(path=target_definition.file_path)
                raise ex
            except (MemoryError, SystemError):  # pragma: no cover
                raise
            except Exception as ex:  # pragma: no cover
                raise InternalError(culprit=ex, path=target_definition.file_path) from ex
            else:
                if level == 0:
                    self._direct.add(target_definition)
                    self._transitive.remove_if(target_definition)
                elif target_definition not in self._direct:
                    self._transitive.add(target_definition)
                self._read_definitions(dsdl_file_sort(self._pending_definitions), lookup_definitions, level + 1)
