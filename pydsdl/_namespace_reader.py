# Copyright (C) OpenCyphal Development Team  <opencyphal.org>
# Copyright Amazon.com Inc. or its affiliates.
# SPDX-License-Identifier: MIT

from __future__ import annotations
import functools
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ._dsdl import DefinitionVisitor, DSDLFile, ReadableDSDLFile, PrintOutputHandler, SortedFileList
from ._dsdl import file_sort as dsdl_file_sort
from ._error import FrontendError, InternalError
from ._serializable._composite import CompositeType


# pylint: disable=too-many-arguments
def _read_definitions(
    target_definitions: SortedFileList[ReadableDSDLFile],
    lookup_definitions: SortedFileList[ReadableDSDLFile],
    print_output_handler: PrintOutputHandler | None,
    allow_unregulated_fixed_port_id: bool,
    direct: set[CompositeType],
    transitive: set[CompositeType],
    file_pool: dict[Path, ReadableDSDLFile],
    level: int,
) -> None:
    """
    Don't look at me! I'm hideous!
    (recursive method with a lot of arguments. See read_definitions for documentation)
    """

    _pending_definitions: set[ReadableDSDLFile] = set()

    class _Callback(DefinitionVisitor):
        def on_definition(self, _: DSDLFile, dependency_dsdl_file: ReadableDSDLFile) -> None:
            if dependency_dsdl_file.file_path not in file_pool:
                _pending_definitions.add(dependency_dsdl_file)

    def print_handler(file: Path, line: int, message: str) -> None:
        if print_output_handler is not None:
            print_output_handler(file, line, message)

    for target_definition in target_definitions:

        if not isinstance(target_definition, ReadableDSDLFile):
            raise TypeError("Expected ReadableDSDLFile, got: " + type(target_definition).__name__)

        target_definition = file_pool.setdefault(target_definition.file_path, target_definition)
        # make sure we are working with the same object for a given file path

        if target_definition.composite_type is not None and (
            target_definition.composite_type in direct or target_definition.composite_type in transitive
        ):
            logging.debug("Skipping target file %s because it has already been processed", target_definition.file_path)
            if level == 0 and target_definition.composite_type in transitive:
                # promote to direct
                transitive.remove(target_definition.composite_type)
                direct.add(target_definition.composite_type)
            continue

        try:
            new_composite_type = target_definition.read(
                lookup_definitions,
                [_Callback()],
                functools.partial(print_handler, target_definition.file_path),
                allow_unregulated_fixed_port_id,
            )
        except FrontendError as ex:  # pragma: no cover
            ex.set_error_location_if_unknown(path=target_definition.file_path)
            raise ex
        except Exception as ex:  # pragma: no cover
            raise InternalError(culprit=ex, path=target_definition.file_path) from ex

        if level == 0:

            direct.add(new_composite_type)
            try:
                transitive.remove(new_composite_type)
            except KeyError:
                pass
        else:
            transitive.add(new_composite_type)

        if len(_pending_definitions) > 0:
            _read_definitions(
                dsdl_file_sort(_pending_definitions),
                lookup_definitions,
                print_output_handler,
                allow_unregulated_fixed_port_id,
                direct,
                transitive,
                file_pool,
                level + 1,
            )
            _pending_definitions.clear()


# +---[FILE: PUBLIC]--------------------------------------------------------------------------------------------------+


@dataclass(frozen=True)
class DSDLDefinitions:
    """
    Common DSDL definition set including the direct dependencies requested and the transitive dependencies found.
    The former and latter sets will be disjoint.
    """

    direct: SortedFileList[CompositeType]
    transitive: SortedFileList[CompositeType]


def read_definitions(
    target_definitions: SortedFileList[ReadableDSDLFile],
    lookup_definitions: SortedFileList[ReadableDSDLFile],
    print_output_handler: PrintOutputHandler | None,
    allow_unregulated_fixed_port_id: bool,
) -> DSDLDefinitions:
    """
    Given a set of DSDL files, this method reads the text and invokes the parser for each and for any files found in the
    lookup set where these are used by the target set.

    :param target_definitions:              List of definitions to read.
    :param lookup_definitions:              List of definitions available for referring to.
    :param print_output_handler:            Used for @print and for diagnostics: (line_number, text) -> None.
    :param allow_unregulated_fixed_port_id: Do not complain about fixed unregulated port IDs.
    :return: The data type representation.
    :raises InvalidDefinitionError: If a dependency is missing.
    :raises InternalError: If an unexpected error occurs.
    """
    _direct: set[CompositeType] = set()
    _transitive: set[CompositeType] = set()
    _file_pool: dict[Path, ReadableDSDLFile] = {}
    _read_definitions(
        target_definitions,
        lookup_definitions,
        print_output_handler,
        allow_unregulated_fixed_port_id,
        _direct,
        _transitive,
        _file_pool,
        0,
    )
    return DSDLDefinitions(
        dsdl_file_sort(_direct),
        dsdl_file_sort(_transitive),
    )


# +-[UNIT TESTS]------------------------------------------------------------------------------------------------------+


def _unittest_namespace_reader_read_definitions(temp_dsdl_factory) -> None:  # type: ignore
    from . import _dsdl_definition

    target = temp_dsdl_factory.new_file(Path("root", "ns", "Target.1.1.dsdl"), "@sealed")
    target_definitions = [cast(ReadableDSDLFile, _dsdl_definition.DSDLDefinition(target, target.parent))]
    lookup_definitions: list[ReadableDSDLFile] = []

    read_definitions(target_definitions, lookup_definitions, None, True)


def _unittest_namespace_reader_read_definitions_multiple(temp_dsdl_factory) -> None:  # type: ignore
    from . import _dsdl_definition

    targets = [
        temp_dsdl_factory.new_file(Path("root", "ns", "Target.1.1.dsdl"), "@sealed\nns.Aisle.1.0 paper_goods\n"),
        temp_dsdl_factory.new_file(Path("root", "ns", "Target.2.0.dsdl"), "@sealed\nns.Aisle.2.0 paper_goods\n"),
        temp_dsdl_factory.new_file(Path("root", "ns", "Walmart.2.4.dsdl"), "@sealed\nns.Aisle.1.0 paper_goods\n"),
    ]
    aisles = [
        temp_dsdl_factory.new_file(Path("root", "ns", "Aisle.1.0.dsdl"), "@sealed"),
        temp_dsdl_factory.new_file(Path("root", "ns", "Aisle.2.0.dsdl"), "@sealed"),
        temp_dsdl_factory.new_file(Path("root", "ns", "Aisle.3.0.dsdl"), "@sealed"),
    ]

    definitions = read_definitions(
        [_dsdl_definition.DSDLDefinition(t, t.parent) for t in targets],
        [_dsdl_definition.DSDLDefinition(a, a.parent) for a in aisles],
        None,
        True,
    )

    assert len(definitions.direct) == 3
    assert len(definitions.transitive) == 2


def _unittest_namespace_reader_read_definitions_multiple_no_load(temp_dsdl_factory) -> None:  # type: ignore
    """
    Ensure that the loader does not load files that are not in the transitive closure of the target files.
    """
    from . import _dsdl_definition

    targets = [
        temp_dsdl_factory.new_file(Path("root", "ns", "Adams.1.0.dsdl"), "@sealed\nns.Tacoma.1.0 volcano\n"),
        temp_dsdl_factory.new_file(Path("root", "ns", "Hood.1.0.dsdl"), "@sealed\nns.Rainer.1.0 volcano\n"),
        temp_dsdl_factory.new_file(Path("root", "ns", "StHelens.2.1.dsdl"), "@sealed\nns.Baker.1.0 volcano\n"),
    ]
    dependencies = [
        temp_dsdl_factory.new_file(Path("root", "ns", "Tacoma.1.0.dsdl"), "@sealed"),
        temp_dsdl_factory.new_file(Path("root", "ns", "Rainer.1.0.dsdl"), "@sealed"),
        temp_dsdl_factory.new_file(Path("root", "ns", "Baker.1.0.dsdl"), "@sealed"),
        Path(
            "root", "ns", "Shasta.1.0.dsdl"
        ),  # since this isn't in the transitive closure of target dependencies it will
        # never be read thus it will not be an error that it does not exist.
    ]

    target_definitions = [cast(ReadableDSDLFile, _dsdl_definition.DSDLDefinition(t, t.parent)) for t in targets]
    lookup_definitions = [cast(ReadableDSDLFile, _dsdl_definition.DSDLDefinition(a, a.parent)) for a in dependencies]
    _ = read_definitions(
        target_definitions,
        lookup_definitions,
        None,
        True,
    )

    # make sure Shasta.1.0 was never accessed but Tacoma 1.0 was
    last_item = lookup_definitions[-1]
    assert isinstance(last_item, _dsdl_definition.DSDLDefinition)
    assert last_item._text is None  # pylint: disable=protected-access
    assert lookup_definitions[0].composite_type is not None

    # Make sure text is cached.
    assert lookup_definitions[0].text == lookup_definitions[0].text


def _unittest_namespace_reader_read_definitions_promotion(temp_dsdl_factory) -> None:  # type: ignore
    from . import _dsdl_definition

    user_1_0 = temp_dsdl_factory.new_file(Path("root", "ns", "User.1.0.dsdl"), "@sealed\n")
    targets = [
        temp_dsdl_factory.new_file(Path("root", "ns", "User.2.0.dsdl"), "@sealed\nns.User.1.0 old_guy\n"),
        user_1_0,
    ]
    lookups = [user_1_0]

    definitions = read_definitions(
        [_dsdl_definition.DSDLDefinition(t, t.parent) for t in targets],
        [_dsdl_definition.DSDLDefinition(l, l.parent) for l in lookups],
        None,
        True,
    )

    assert len(definitions.direct) == 2
    assert len(definitions.transitive) == 0


def _unittest_namespace_reader_read_definitions_no_demote(temp_dsdl_factory) -> None:  # type: ignore
    from . import _dsdl_definition

    user_1_0 = temp_dsdl_factory.new_file(Path("root", "ns", "User.1.0.dsdl"), "@sealed\n")
    targets = [
        user_1_0,
        temp_dsdl_factory.new_file(Path("root", "ns", "User.2.0.dsdl"), "@sealed\nns.User.1.0 old_guy\n"),
    ]
    lookups = [user_1_0]

    definitions = read_definitions(
        [_dsdl_definition.DSDLDefinition(t, t.parent) for t in targets],
        [_dsdl_definition.DSDLDefinition(l, l.parent) for l in lookups],
        None,
        True,
    )

    assert len(definitions.direct) == 2
    assert len(definitions.transitive) == 0


def _unittest_namespace_reader_read_definitions_no_promote(temp_dsdl_factory) -> None:  # type: ignore
    from . import _dsdl_definition

    targets = [
        temp_dsdl_factory.new_file(Path("root", "ns", "User.2.0.dsdl"), "@sealed\nns.User.1.0 old_guy\n"),
        temp_dsdl_factory.new_file(Path("root", "ns", "User.3.0.dsdl"), "@sealed\nns.User.1.0 old_guy\n"),
    ]
    lookups = [temp_dsdl_factory.new_file(Path("root", "ns", "User.1.0.dsdl"), "@sealed\n")]

    definitions = read_definitions(
        [_dsdl_definition.DSDLDefinition(t, t.parent) for t in targets],
        [_dsdl_definition.DSDLDefinition(l, l.parent) for l in lookups],
        None,
        True,
    )

    assert len(definitions.direct) == 2
    assert len(definitions.transitive) == 1


def _unittest_namespace_reader_read_definitions_twice(temp_dsdl_factory) -> None:  # type: ignore
    from . import _dsdl_definition

    targets = [
        temp_dsdl_factory.new_file(Path("root", "ns", "User.2.0.dsdl"), "@sealed\nns.User.1.0 old_guy\n"),
        temp_dsdl_factory.new_file(Path("root", "ns", "User.2.0.dsdl"), "@sealed\nns.User.1.0 old_guy\n"),
    ]
    lookups = [temp_dsdl_factory.new_file(Path("root", "ns", "User.1.0.dsdl"), "@sealed\n")]

    definitions = read_definitions(
        [_dsdl_definition.DSDLDefinition(t, t.parent) for t in targets],
        [_dsdl_definition.DSDLDefinition(l, l.parent) for l in lookups],
        None,
        True,
    )

    assert len(definitions.direct) == 1
    assert len(definitions.transitive) == 1


def _unittest_namespace_reader_read_definitions_missing_dependency(temp_dsdl_factory) -> None:  # type: ignore
    """
    Verify that an error is raised when a dependency is missing.
    """
    from pytest import raises as assert_raises

    from . import _dsdl_definition
    from ._data_type_builder import UndefinedDataTypeError

    with assert_raises(UndefinedDataTypeError):
        read_definitions(
            [
                _dsdl_definition.DSDLDefinition(
                    f := temp_dsdl_factory.new_file(
                        Path("root", "ns", "Cat.1.0.dsdl"), "@sealed\nns.Birman.1.0 fluffy\n"
                    ),
                    f.parent,
                )
            ],
            [],
            None,
            True,
        )


def _unittest_namespace_reader_read_definitions_target_in_lookup(temp_dsdl_factory) -> None:  # type: ignore
    """
    Ensure the direct and transitive sets are disjoint.
    """
    from . import _dsdl_definition

    targets = [
        temp_dsdl_factory.new_file(Path("root", "ns", "Ontario.1.0.dsdl"), "@sealed\nns.NewBrunswick.1.0 place\n"),
        temp_dsdl_factory.new_file(Path("root", "ns", "NewBrunswick.1.0.dsdl"), "@sealed"),
    ]
    lookup = [
        temp_dsdl_factory.new_file(Path("root", "ns", "NewBrunswick.1.0.dsdl"), "@sealed"),
    ]

    definitions = read_definitions(
        [_dsdl_definition.DSDLDefinition(t, t.parent) for t in targets],
        [_dsdl_definition.DSDLDefinition(l, l.parent) for l in lookup],
        None,
        True,
    )

    assert len(definitions.direct) == 2
    assert len(definitions.transitive) == 0


def _unittest_namespace_reader_read_defs_target_dont_allow_unregulated(temp_dsdl_factory) -> None:  # type: ignore
    """
    Ensure that an error is raised when an invalid, fixed port ID is used without an override.
    """
    from pytest import raises as assert_raises

    from . import _dsdl_definition
    from ._data_type_builder import UnregulatedFixedPortIDError

    targets = [
        temp_dsdl_factory.new_file(Path("root", "ns", "845.Lice.1.0.dsdl"), "@sealed\n"),
    ]

    with assert_raises(UnregulatedFixedPortIDError):
        read_definitions(
            [_dsdl_definition.DSDLDefinition(t, t.parent) for t in targets],
            [],
            None,
            False,
        )


def _unittest_namespace_reader_type_error() -> None:
    from pytest import raises as assert_raises

    with assert_raises(TypeError):
        read_definitions(
            [""],  # type: ignore
            [],
            None,
            True,
        )
