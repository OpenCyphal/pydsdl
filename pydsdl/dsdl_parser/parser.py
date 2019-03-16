#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import logging

from parsimonious import VisitationError, ParseError as ParsimoniousParseError  # Oops?

from ..parse_error import InvalidDefinitionError, ParseError, InternalError
from ..dsdl_definition import DSDLDefinition
from ..data_type import CompoundType, TypeParameterError

from .options import ConfigurationOptions
from .parse_tree_transformer import ParseTreeTransformer, StatementStreamProcessor
from . import expression


class DSDLSyntaxError(InvalidDefinitionError):
    pass


class UndefinedDataTypeError(InvalidDefinitionError):
    pass


class SemanticError(InvalidDefinitionError):
    pass


class AssertionCheckFailureError(SemanticError):
    pass


_logger = logging.getLogger(__name__)


def parse_definition(definition:            DSDLDefinition,
                     lookup_definitions:    typing.Sequence[DSDLDefinition],
                     configuration_options: ConfigurationOptions) -> CompoundType:
    _logger.info('Parsing definition %r', definition)

    try:
        parser = _Parser(definition, configuration_options)

        transformer = ParseTreeTransformer(parser)

        with open(definition.file_path) as f:
            transformer.parse(f.read())

        raise KeyboardInterrupt     # TODO
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


class _Parser(StatementStreamProcessor):
    def __init__(self,
                 definition: DSDLDefinition,
                 configuration_options: ConfigurationOptions):
        self._definition = definition
        self._configuration = configuration_options

    def on_directive(self,
                     line_number: int,
                     directive_name: str,
                     associated_expression_value: typing.Optional[expression.Any]) -> None:
        if directive_name == 'print':
            _logger.info('Print directive at %s:%d%s',
                         self._definition.file_path,
                         line_number,
                         (': %s' % associated_expression_value)
                         if associated_expression_value is not None else
                         ' (no value to print)')
            ph = self._configuration.print_handler
            if ph:
                ph(self._definition, line_number, associated_expression_value)

        elif directive_name == 'assert':
            if isinstance(associated_expression_value, expression.Boolean):
                if not associated_expression_value.native_value:
                    raise AssertionCheckFailureError('Assertion check has failed',
                                                     path=self._definition.file_path,
                                                     line=line_number)
                else:
                    _logger.debug('Assertion check successful at %s:%d', self._definition.file_path, line_number)
            elif associated_expression_value is None:
                raise SemanticError('Assert directive requires an expression')
            else:
                raise SemanticError('The assertion check expression must yield a boolean, not %s' %
                                    associated_expression_value.TYPE_NAME)

        elif directive_name == 'deprecated':
            pass  # TODO

        elif directive_name == 'union':
            pass  # TODO

        else:
            raise SemanticError('Unknown directive %r' % directive_name)

    def on_service_response_marker(self) -> None:
        print('SERVICE RESPONSE MARKER')        # TODO: IMPLEMENT
