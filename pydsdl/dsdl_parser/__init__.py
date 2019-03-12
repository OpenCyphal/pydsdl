#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
import logging

from ..dsdl_definition import DSDLDefinition
from ..data_type import CompoundType

from .options import ConfigurationOptions, PrintDirectiveOutputHandler
from .exceptions import DSDLSyntaxError, SemanticError, UndefinedDataTypeError, AssertionCheckFailureError, \
    ExpressionError, InvalidOperandError, InvalidDefinitionError


_GRAMMAR_DEFINITION_FILE_PATH = os.path.join(os.path.dirname(__file__), 'grammar.parsimonious')

_FULL_BIT_WIDTH_SET = list(range(1, 65))


_logger = logging.getLogger(__name__)


def parse_definition(definition:            DSDLDefinition,
                     lookup_definitions:    typing.Sequence[DSDLDefinition],
                     configuration_options: ConfigurationOptions) -> CompoundType:
    from ..parse_error import ParseError, InternalError
    from ..data_type import TypeParameterError
    from parsimonious import VisitationError, ParseError as ParsimoniousParseError  # Oops?

    _logger.info('Parsing definition %r', definition)

    try:
        from .ast_transformer import ASTTransformer

        transformer = ASTTransformer(lookup_definitions,
                                     configuration_options)

        with open(definition.file_path) as f:
            transformer.parse(f.read())

        raise KeyboardInterrupt
    except ParsimoniousParseError as ex:
        raise DSDLSyntaxError('Syntax error', path=definition.file_path, line=ex.line())
    except VisitationError as ex:
        raise DSDLSyntaxError(str(ex), path=definition.file_path)
    except TypeParameterError as ex:
        raise SemanticError(str(ex), path=definition.file_path)
    except ParseError as ex:  # pragma: no cover
        ex.set_error_location_if_unknown(path=definition.file_path)
        raise
    except Exception as ex:  # pragma: no cover
        raise InternalError(culprit=ex, path=definition.file_path)
