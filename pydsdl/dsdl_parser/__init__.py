#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import os
import typing
import logging

from ..parse_error import InvalidDefinitionError
from ..dsdl_definition import DSDLDefinition
from ..data_type import CompoundType

from .options import ConfigurationOptions, PrintDirectiveOutputHandler


class DSDLSyntaxError(InvalidDefinitionError):
    pass


class UndefinedDataTypeError(InvalidDefinitionError):
    pass


class SemanticError(InvalidDefinitionError):
    pass


class AssertionCheckFailureError(SemanticError):
    pass


_GRAMMAR_DEFINITION_FILE_PATH = os.path.join(os.path.dirname(__file__), 'grammar.parsimonious')

_FULL_BIT_WIDTH_SET = list(range(1, 65))


_logger = logging.getLogger(__name__)


def parse_definition(definition:            DSDLDefinition,
                     lookup_definitions:    typing.Sequence[DSDLDefinition],
                     configuration_options: ConfigurationOptions) -> CompoundType:
    from ..parse_error import ParseError, InternalError
    from ..data_type import TypeParameterError
    from parsimonious import VisitationError, ParseError as ParsimoniousParseError  # Oops?
    from .ast_transformer import ASTTransformer
    from . import expression

    _logger.info('Parsing definition %r', definition)

    def on_directive(line_number: int, name: str, value: expression.Any) -> None:
        if name == 'print':
            _logger.info('Print directive at %s:%d%s',
                         definition.file_path,
                         line_number,
                         (': %s' % value) if value is not None else ' (no value to print)')
            ph = configuration_options.print_handler
            if ph:
                ph(definition, line_number, value)

        elif name == 'assert':
            if isinstance(value, expression.Boolean):
                if not value.native_value:
                    raise AssertionCheckFailureError('Assertion check has failed',
                                                     path=definition.file_path,
                                                     line=line_number)
                else:
                    _logger.debug('Assertion check successful at %s:%d', definition.file_path, line_number)
            elif value is None:
                raise SemanticError('Assert directive requires an expression')
            else:
                raise SemanticError('The assertion check expression must yield a boolean, not %s' % value.TYPE_NAME)

        elif name == 'deprecated':
            pass    # TODO

        elif name == 'union':
            pass    # TODO

        else:
            raise SemanticError('Unknown directive %r' % name)

    try:
        transformer = ASTTransformer()

        with open(definition.file_path) as f:
            transformer.parse(f.read())

        raise KeyboardInterrupt
    except ParsimoniousParseError as ex:
        raise DSDLSyntaxError('Syntax error', path=definition.file_path, line=ex.line())
    except TypeParameterError as ex:
        raise SemanticError(str(ex), path=definition.file_path)
    except ParseError as ex:       # pragma: no cover
        ex.set_error_location_if_unknown(path=definition.file_path)
        raise
    except VisitationError as ex:  # pragma: no cover
        try:
            line = int(ex.original_class.line())    # type: typing.Optional[int]
        except AttributeError:
            line = None
        # Treat as internal because all intentional errors are not wrapped into VisitationError.
        raise InternalError(str(ex), path=definition.file_path, line=line)
    except Exception as ex:        # pragma: no cover
        raise InternalError(culprit=ex, path=definition.file_path)
