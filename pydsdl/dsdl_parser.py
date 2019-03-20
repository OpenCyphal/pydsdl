#
# Copyright (C) 2018-2019  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import typing
import logging

import parsimonious

from . import data_type
from .frontend_error import InvalidDefinitionError, FrontendError, InternalError
from .dsdl_definition import DSDLDefinition
from .parse_tree_transformer import ParseTreeTransformer, StatementStreamProcessor
from . import expression


# Arguments: emitting definition, line number, value to print
# The lines are numbered starting from one
PrintDirectiveOutputHandler = typing.Callable[[DSDLDefinition, int, typing.Any], None]


class ConfigurationOptions:
    def __init__(self) -> None:
        self.print_handler = None                       # type: typing.Optional[PrintDirectiveOutputHandler]
        self.allow_unregulated_fixed_port_id = False
        self.skip_assertion_checks = False


class DSDLSyntaxError(InvalidDefinitionError):
    pass


class SemanticError(InvalidDefinitionError):
    pass


class UndefinedDataTypeError(SemanticError):
    pass


class AssertionCheckFailureError(SemanticError):
    pass


class UndefinedIdentifierError(SemanticError):
    pass


_logger = logging.getLogger(__name__)


def parse_definition(definition:            DSDLDefinition,
                     lookup_definitions:    typing.Sequence[DSDLDefinition],
                     configuration_options: ConfigurationOptions) -> data_type.CompoundType:
    _logger.info('Parsing definition %r', definition)

    try:
        # Remove the target definition from the lookup list in order to prevent
        # infinite recursion on self-referential definitions.
        lookup_definitions = list(filter(lambda d: d != definition, lookup_definitions))

        proc = _Processor(definition,
                          lookup_definitions,
                          configuration_options)

        transformer = ParseTreeTransformer(proc)

        with open(definition.file_path) as f:
            transformer.parse(f.read())

        raise KeyboardInterrupt     # TODO
    except parsimonious.ParseError as ex:
        raise DSDLSyntaxError('Syntax error', path=definition.file_path, line=ex.line())
    except data_type.TypeParameterError as ex:
        raise SemanticError(str(ex), path=definition.file_path)
    except FrontendError as ex:       # pragma: no cover
        ex.set_error_location_if_unknown(path=definition.file_path)
        raise
    except parsimonious.VisitationError as ex:  # pragma: no cover
        try:
            line = int(ex.original_class.line())    # type: typing.Optional[int]
        except AttributeError:
            line = None
        # Treat as internal because all intentional errors are not wrapped into VisitationError.
        raise InternalError(str(ex), path=definition.file_path, line=line)
    except Exception as ex:        # pragma: no cover
        raise InternalError(culprit=ex, path=definition.file_path)


class _Processor(StatementStreamProcessor):
    def __init__(self,
                 definition:            DSDLDefinition,
                 lookup_definitions:    typing.Sequence[DSDLDefinition],
                 configuration_options: ConfigurationOptions):
        self._definition = definition
        self._lookup_definitions = lookup_definitions
        self._configuration = configuration_options

    def on_constant(self,
                    constant_type: data_type.DataType,
                    name: str,
                    initialization_expression: expression.Any) -> None:
        print('CONSTANT', constant_type, name, initialization_expression)

    def on_field(self, field_type: data_type.DataType, name: str) -> None:
        print('FIELD', field_type, name)

    def on_padding_field(self, padding_field_type: data_type.VoidType) -> None:
        print('PADDING', padding_field_type)

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
            (self._configuration.print_handler or (lambda *_: None))(self._definition,
                                                                     line_number,
                                                                     associated_expression_value)

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

    def resolve_top_level_identifier(self, name: str) -> expression.Any:
        # TODO: handling of special identifiers such as _offset_.
        raise UndefinedIdentifierError

    def resolve_versioned_data_type(self, name: str, version: data_type.Version) -> data_type.CompoundType:
        if data_type.CompoundType.NAME_COMPONENT_SEPARATOR in name:
            full_name = name
        else:
            full_name = data_type.CompoundType.NAME_COMPONENT_SEPARATOR.join([self._definition.full_namespace, name])
            _logger.info('The full name of a relatively referred type %r is reconstructed as %r', name, full_name)

        del name
        found = list(filter(lambda d: d.full_name == full_name and d.version == version, self._lookup_definitions))
        if not found:
            raise UndefinedDataTypeError('Data type %r version %r could be found' % (full_name, version))
        if len(found) > 1:
            raise InternalError('Conflicting definitions: %r' % found)

        target_definition = found[0]
        assert isinstance(target_definition, DSDLDefinition)
        assert target_definition.full_name == full_name
        assert target_definition.version == version

        # TODO: this is highly inefficient, we need caching.
        return parse_definition(target_definition,
                                lookup_definitions=self._lookup_definitions,
                                configuration_options=self._configuration)
