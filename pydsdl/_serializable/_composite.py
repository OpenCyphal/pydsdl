#
# Copyright (C) 2018-2020  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import abc
import math
import typing
import itertools
import fractions
from .. import _expression
from .. import _port_id_ranges
from .._bit_length_set import BitLengthSet
from ._serializable import SerializableType, TypeParameterError
from ._attribute import Attribute, Field, PaddingField, Constant
from ._name import check_name, InvalidNameError
from ._void import VoidType
from ._primitive import PrimitiveType, UnsignedIntegerType


Version = typing.NamedTuple('Version', [('major', int), ('minor', int)])


class InvalidVersionError(TypeParameterError):
    pass


class AttributeNameCollisionError(TypeParameterError):
    pass


class InvalidExtentError(TypeParameterError):
    pass


class InvalidFixedPortIDError(TypeParameterError):
    pass


class MalformedUnionError(TypeParameterError):
    pass


class DeprecatedDependencyError(TypeParameterError):
    pass


class CompositeType(SerializableType):
    """
    This is the most interesting type in the library because it represents an actual DSDL definition upon its
    interpretation.
    This is an abstract class with several specializations.
    """

    MAX_NAME_LENGTH = 50
    MAX_VERSION_NUMBER = 255
    NAME_COMPONENT_SEPARATOR = '.'

    def __init__(self,
                 name:             str,
                 version:          Version,
                 attributes:       typing.Iterable[Attribute],
                 deprecated:       bool,
                 fixed_port_id:    typing.Optional[int],
                 source_file_path: str,
                 parent_service:   typing.Optional['ServiceType'] = None):
        super(CompositeType, self).__init__()

        self._name = str(name).strip()
        self._version = version
        self._attributes = list(attributes)
        self._attributes_by_name = {a.name: a for a in self._attributes if not isinstance(a, PaddingField)}
        self._deprecated = bool(deprecated)
        self._fixed_port_id = None if fixed_port_id is None else int(fixed_port_id)
        self._source_file_path = str(source_file_path)
        self._parent_service = parent_service

        if self._parent_service is not None:
            assert self._name.endswith('.Request') or self._name.endswith('.Response')
            if not isinstance(self._parent_service, ServiceType):  # pragma: no cover
                raise ValueError('The parent service reference is invalid: %s' % type(parent_service).__name__)

        # Name check
        if not self._name:
            raise InvalidNameError('Composite type name cannot be empty')

        if self.NAME_COMPONENT_SEPARATOR not in self._name:
            raise InvalidNameError('Root namespace is not specified')

        # Do not check name length for synthesized types.
        if len(self._name) > self.MAX_NAME_LENGTH and parent_service is None:
            raise InvalidNameError('Name is too long: %r is longer than %d characters' %
                                   (self._name, self.MAX_NAME_LENGTH))

        for component in self._name.split(self.NAME_COMPONENT_SEPARATOR):
            check_name(component)

        # Version check
        version_valid = (0 <= self._version.major <= self.MAX_VERSION_NUMBER) and\
                        (0 <= self._version.minor <= self.MAX_VERSION_NUMBER) and\
                        ((self._version.major + self._version.minor) > 0)

        if not version_valid:
            raise InvalidVersionError('Invalid version numbers: %s.%s' % (self._version.major, self._version.minor))

        # Attribute check
        used_names = set()      # type: typing.Set[str]
        for a in self._attributes:
            if a.name and a.name in used_names:
                raise AttributeNameCollisionError('Multiple attributes under the same name: %r' % a.name)
            else:
                used_names.add(a.name)

        # Port ID check
        port_id = self._fixed_port_id
        if port_id is not None:
            assert port_id is not None
            if isinstance(self, ServiceType):
                if not (0 <= port_id <= _port_id_ranges.MAX_SERVICE_ID):
                    raise InvalidFixedPortIDError('Fixed service ID %r is not valid' % port_id)
            else:
                if not (0 <= port_id <= _port_id_ranges.MAX_SUBJECT_ID):
                    raise InvalidFixedPortIDError('Fixed subject ID %r is not valid' % port_id)

        # Consistent deprecation check.
        # A non-deprecated type cannot be dependent on deprecated types.
        # A deprecated type can be dependent on anything.
        if not self.deprecated:
            for a in self._attributes:
                t = a.data_type
                if isinstance(t, CompositeType):
                    if t.deprecated:
                        raise DeprecatedDependencyError('A type cannot depend on deprecated types '
                                                        'unless it is also deprecated.')

    @property
    def full_name(self) -> str:
        """The full name, e.g., ``uavcan.node.Heartbeat``."""
        return self._name

    @property
    def name_components(self) -> typing.List[str]:
        """Components of the full name as a list, e.g., ``['uavcan', 'node', 'Heartbeat']``."""
        return self._name.split(CompositeType.NAME_COMPONENT_SEPARATOR)

    @property
    def short_name(self) -> str:
        """The last component of the full name, e.g., ``Heartbeat`` of ``uavcan.node.Heartbeat``."""
        return self.name_components[-1]

    @property
    def full_namespace(self) -> str:
        """The full name without the short name, e.g., ``uavcan.node`` for ``uavcan.node.Heartbeat``."""
        return str(CompositeType.NAME_COMPONENT_SEPARATOR.join(self.name_components[:-1]))

    @property
    def root_namespace(self) -> str:
        """The first component of the full name, e.g., ``uavcan`` of ``uavcan.node.Heartbeat``."""
        return self.name_components[0]

    @property
    def version(self) -> Version:
        """The version numbers of the type, e.g., ``(1, 0)`` of ``uavcan.node.Heartbeat.1.0``."""
        return self._version

    @property
    def extent(self) -> int:
        """
        The amount of memory, in bits, that needs to be allocated in order to store a serialized representation of
        this type or any of its minor versions under the same major version.
        This value is always at least as large as the sum of maximum bit lengths of all fields padded to one byte.
        If the type is sealed, its extent equals ``max(bit_length_set)``.
        """
        return max(self.bit_length_set or {0})

    @property
    def bit_length_set(self) -> BitLengthSet:
        """
        The bit length set of a composite is always aligned at :attr:`alignment_requirement`.
        For a sealed type this is the true bit length set computed by aggregating the fields and
        padding the result to :attr:`alignment_requirement`.
        That is, sealed types expose their internal structure; for example, a type that contains a single field
        of type ``uint32[2]`` would have a single entry in the bit length set: ``{64}``.
        """
        raise NotImplementedError

    @property
    def deprecated(self) -> bool:
        """Whether the definition is marked ``@deprecated``."""
        return self._deprecated

    @property
    def attributes(self) -> typing.List[Attribute]:
        return self._attributes[:]  # Return copy to prevent mutation

    @property
    def fields(self) -> typing.List[Field]:
        return [a for a in self.attributes if isinstance(a, Field)]

    @property
    def fields_except_padding(self) -> typing.List[Field]:
        return [a for a in self.attributes if isinstance(a, Field) and not isinstance(a, PaddingField)]

    @property
    def constants(self) -> typing.List[Constant]:
        return [a for a in self.attributes if isinstance(a, Constant)]

    @property
    def fixed_port_id(self) -> typing.Optional[int]:
        return self._fixed_port_id

    @property
    def has_fixed_port_id(self) -> bool:
        return self.fixed_port_id is not None

    @property
    def source_file_path(self) -> str:
        """
        For synthesized types such as service request/response sections, this property is defined as an empty string.
        """
        return self._source_file_path

    @property
    def alignment_requirement(self) -> int:
        # This is more general than required by the Specification, but it is done this way in case if we decided
        # to support greater alignment requirements in the future.
        return max([self.BITS_PER_BYTE] + [x.data_type.alignment_requirement for x in self.fields])

    @property
    def parent_service(self) -> typing.Optional['ServiceType']:
        """
        :class:`pydsdl.ServiceType` contains two special fields of this type: ``request`` and ``response``.
        For them this property points to the parent service instance; otherwise it's None.
        """
        return self._parent_service

    @abc.abstractmethod
    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """
        Iterates over every field (not attribute -- constants are excluded) of the data type,
        yielding it together with its offset, where the offset is represented as :class:`pydsdl.BitLengthSet`.
        The offset of each field is added to the base offset, which may be specified by the caller;
        if not specified, the base offset is assumed to be ``{0}``.

        The objective of this method is to allow code generators to easily implement fully unrolled serialization and
        deserialization routines, where "unrolled" means that upon encountering another (nested) composite type, the
        serialization routine would not delegate its serialization to the serialization routine of the encountered type,
        but instead would serialize it in-place, as if the field of that type was replaced with its own fields in-place.
        The lack of delegation has very important performance implications: when the serialization routine does
        not delegate serialization of the nested types, it can perform infinitely deep field alignment analysis,
        thus being able to reliably statically determine whether each field of the type, including nested types
        at arbitrarily deep levels of nesting, is aligned relative to the origin of the serialized representation
        of the outermost type. As a result, the code generator will be able to avoid unnecessary reliance on slow
        bit-level copy routines replacing them instead with much faster byte-level copy (like ``memcpy()``) or even
        plain memory aliasing.

        When invoked on a tagged union type, the method yields the same offset for every field (since that's how
        tagged unions are serialized), where the offset equals the bit length of the implicit union tag (plus the
        base offset, of course, if provided).

        Please refer to the usage examples to see how this feature can be used.

        :param base_offset: Assume the specified base offset; assume zero offset if the parameter is not provided.
            The base offset will be implicitly padded out to :attr:`alignment_requirement`.

        :return: A generator of ``(Field, BitLengthSet)``.
            Each instance of :class:`pydsdl.BitLengthSet` yielded by the generator is a dedicated copy,
            meaning that the consumer can mutate the returned instances arbitrarily without affecting future values.
            It is guaranteed that each yielded instance is non-empty.
        """
        raise NotImplementedError

    def _attribute(self, name: _expression.String) -> _expression.Any:
        """This is the handler for DSDL expressions like ``uavcan.node.Heartbeat.1.0.MODE_OPERATIONAL``."""
        for c in self.constants:
            if c.name == name.native_value:
                assert isinstance(c.value, _expression.Any)
                return c.value

        if name.native_value == '_extent_':  # Experimental non-standard extension
            return _expression.Rational(self.extent)

        return super(CompositeType, self)._attribute(name)  # Hand over up the inheritance chain, this is important

    def __getitem__(self, attribute_name: str) -> Attribute:
        """
        Allows the caller to retrieve an attribute by name.
        Padding fields are not accessible via this interface because they don't have names.
        Raises :class:`KeyError` if there is no such attribute.
        """
        return self._attributes_by_name[attribute_name]

    def __str__(self) -> str:
        """Returns a string like ``uavcan.node.Heartbeat.1.0``."""
        return '%s.%d.%d' % (self.full_name, self.version.major, self.version.minor)

    def __repr__(self) -> str:
        return (
            '%s(name=%r, version=%r, fields=%r, constants=%r, alignment_requirement=%r, '
            'deprecated=%r, fixed_port_id=%r)'
        ) % (
            self.__class__.__name__,
            self.full_name,
            self.version,
            self.fields,
            self.constants,
            self.alignment_requirement,
            self.deprecated,
            self.fixed_port_id,
        )


class UnionType(CompositeType):
    """
    A message type that is marked ``@union``.
    """

    MIN_NUMBER_OF_VARIANTS = 2

    def __init__(self,
                 name:             str,
                 version:          Version,
                 attributes:       typing.Iterable[Attribute],
                 deprecated:       bool,
                 fixed_port_id:    typing.Optional[int],
                 source_file_path: str,
                 parent_service:   typing.Optional['ServiceType'] = None):
        # Proxy all parameters directly to the base type - I wish we could do that
        # with kwargs while preserving the type information
        super(UnionType, self).__init__(name=name,
                                        version=version,
                                        attributes=attributes,
                                        deprecated=deprecated,
                                        fixed_port_id=fixed_port_id,
                                        source_file_path=source_file_path,
                                        parent_service=parent_service)

        if self.number_of_variants < self.MIN_NUMBER_OF_VARIANTS:
            raise MalformedUnionError('A tagged union cannot contain fewer than %d variants' %
                                      self.MIN_NUMBER_OF_VARIANTS)

        for a in attributes:
            if isinstance(a, PaddingField) or not a.name or isinstance(a.data_type, VoidType):
                raise MalformedUnionError('Padding fields not allowed in unions')

        self._tag_field_type = UnsignedIntegerType(self._compute_tag_bit_length([x.data_type for x in self.fields]),
                                                   PrimitiveType.CastMode.TRUNCATED)

    @property
    def bit_length_set(self) -> BitLengthSet:
        # Can't use @cached_property because it is unavailable before Python 3.8 and it breaks Sphinx and MyPy.
        att = '_8579621435'
        if not hasattr(self, att):
            agr = self.aggregate_bit_length_sets
            setattr(self, att, agr([f.data_type for f in self.fields]).pad_to_alignment(self.alignment_requirement))
        out = getattr(self, att)
        assert isinstance(out, BitLengthSet)
        return out

    @property
    def number_of_variants(self) -> int:
        return len(self.fields)

    @property
    def tag_field_type(self) -> UnsignedIntegerType:
        """
        The unsigned integer type of the implicit union tag field.
        Note that the set of valid tag values is a subset of that of the returned type.
        """
        return self._tag_field_type

    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """See the base class."""
        base_offset = BitLengthSet(base_offset or {0}).pad_to_alignment(self.alignment_requirement)
        base_offset += self.tag_field_type.bit_length
        for f in self.fields:  # Same offset for every field, because it's a tagged union, not a struct
            assert base_offset.is_aligned_at(f.data_type.alignment_requirement)
            yield f, BitLengthSet(base_offset)      # We yield a copy of the offset to prevent mutation

    @staticmethod
    def aggregate_bit_length_sets(field_types: typing.Sequence[SerializableType]) -> BitLengthSet:
        """
        Computes the bit length set for a tagged union type given the type of each of its variants.
        The final padding is not applied.

        Unions are easy to handle because when serialized, a union is essentially just a single field prefixed with
        a fixed-length integer tag. So we just build a full set of combinations and then add the tag length
        to each element.

        Observe that unions are not defined for less than 2 elements;
        however, this function tries to be generic by properly handling those cases as well,
        even though they are not permitted by the specification.
        For zero fields, the function yields ``{0}``; for one field, the function yields the BLS of the field itself.
        """
        ms = [x.bit_length_set for x in field_types]
        if len(ms) == 0:
            return BitLengthSet(0)
        if len(ms) == 1:
            return BitLengthSet(ms[0])

        tbl = UnionType._compute_tag_bit_length(field_types)
        out = BitLengthSet()
        for s in ms:
            out |= s + tbl
        assert len(out) > 0, 'Empty sets forbidden'
        return out

    @staticmethod
    def _compute_tag_bit_length(field_types: typing.Sequence[SerializableType]) -> int:
        assert len(field_types) > 1, 'Internal API misuse'
        unaligned_tag_bit_length = (len(field_types) - 1).bit_length()
        tag_bit_length = 2 ** math.ceil(math.log2(max(SerializableType.BITS_PER_BYTE, unaligned_tag_bit_length)))
        # This is to prevent the tag from breaking the alignment of the following variant.
        tag_bit_length = max([tag_bit_length] + [x.alignment_requirement for x in field_types])
        assert isinstance(tag_bit_length, int)
        assert tag_bit_length in {8, 16, 32, 64}
        return tag_bit_length


class StructureType(CompositeType):
    """
    A message type that is NOT marked ``@union``.
    """

    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """See the base class."""
        base_offset = BitLengthSet(base_offset or 0).pad_to_alignment(self.alignment_requirement)
        for f in self.fields:
            base_offset = base_offset.pad_to_alignment(f.data_type.alignment_requirement)
            yield f, BitLengthSet(base_offset)      # We yield a copy of the offset to prevent mutation
            base_offset += f.data_type.bit_length_set

    @property
    def bit_length_set(self) -> BitLengthSet:
        # Can't use @cached_property because it is unavailable before Python 3.8 and it breaks Sphinx and MyPy.
        att = '_7953874601'
        if not hasattr(self, att):
            agr = self.aggregate_bit_length_sets
            setattr(self, att, agr([f.data_type for f in self.fields]).pad_to_alignment(self.alignment_requirement))
        out = getattr(self, att)
        assert isinstance(out, BitLengthSet)
        return out

    @staticmethod
    def aggregate_bit_length_sets(field_types: typing.Sequence[SerializableType]) -> BitLengthSet:
        """
        Computes the bit length set for a structure type given the type of each of its fields.
        The final padding is not applied.
        """
        bls = BitLengthSet()
        for t in field_types:
            bls = bls.pad_to_alignment(t.alignment_requirement)
            bls += t.bit_length_set
        return bls or BitLengthSet(0)  # Empty bit length sets are forbidden


class DelimitedType(CompositeType):
    """
    Composites that are not sealed are wrapped into this container.
    It is a decorator over a composite type instance that injects the extent, bit length set, and field iteration
    logic that is specific to delimited (appendable, non-sealed) types.

    Most of the attributes are copied from the wrapped type (e.g., name, fixed port-ID, attributes, etc.),
    except for those that relate to the bit layout.

    Non-sealed composites are serialized into delimited opaque containers like ``uint8[<=(extent + 7) // 8]``,
    where the implicit length prefix is of type :attr:`delimiter_header_type`.
    Their bit length set is also computed as if it was an array as declared above,
    in order to prevent the containing definitions from making assumptions about the offsets of the following fields
    that might not survive the evolution of the type (e.g., version 1 may be 64 bits long, version 2 might be
    56 bits long, then version 3 could grow to 96 bits, unpredictable).
    """

    DEFAULT_EXTENT_MULTIPLIER = fractions.Fraction(3, 2)
    """
    If the extent is not specified explicitly, it is computed by multiplying the extent of the inner type by this.
    """

    _DEFAULT_DELIMITER_HEADER_BIT_LENGTH = 32

    def __init__(self, inner: CompositeType, extent: typing.Optional[int]):
        self._inner = inner
        super(DelimitedType, self).__init__(name=inner.full_name,
                                            version=inner.version,
                                            attributes=inner.attributes,
                                            deprecated=inner.deprecated,
                                            fixed_port_id=inner.fixed_port_id,
                                            source_file_path=inner.source_file_path,
                                            parent_service=inner.parent_service)
        if extent is None:
            unaligned = math.floor(inner.extent * self.DEFAULT_EXTENT_MULTIPLIER)
            self._extent = max(BitLengthSet(unaligned).pad_to_alignment(self.alignment_requirement))
        else:
            self._extent = int(extent)

        if self._extent % self.alignment_requirement != 0:
            raise InvalidExtentError('The specified extent of %d bits is not a multiple of %d bits' %
                                     (self._extent, self.alignment_requirement))
        if self._extent < inner.extent:
            raise InvalidExtentError(
                'The specified extent of %d bits is too small for this data type. '
                'Either compactify the data type or increase the extent at least to %d bits. '
                'Beware that the latter option may break wire compatibility.' %
                (self._extent, inner.extent)
            )

        # Invariant checks.
        assert self.extent % self.BITS_PER_BYTE == 0
        assert self.extent % self.alignment_requirement == 0
        assert self.extent >= self.inner_type.extent
        assert len(self.bit_length_set) > 0
        assert self.bit_length_set.is_aligned_at_byte()
        assert self.bit_length_set.is_aligned_at(self.alignment_requirement)
        assert not self.bit_length_set or \
            self.extent >= max(self.bit_length_set) - self.delimiter_header_type.bit_length

    @property
    def inner_type(self) -> CompositeType:
        """
        The appendable type that is serialized inside this delimited container.
        Its bit length set, extent, and other layout-specific entities are computed as if it was a sealed type.
        """
        return self._inner

    @property
    def extent(self) -> int:
        """
        The extent of a delimited type can be specified explicitly via ``@extent`` (provided that it is not less
        than the minimum); otherwise, it defaults to ``floor(inner_type.extent * 3/2)`` padded to byte.

        Optional optimization hint: if the objective is to allocate buffer memory for constructing a new
        serialized representation locally, then it may be beneficial to use the extent of the inner type
        rather than this one because it may be smaller. This is not safe for deserialization, of course.
        """
        return self._extent

    @property
    def bit_length_set(self) -> BitLengthSet:
        """
        For a non-sealed type, not many guarantees about the bit length set can be provided,
        because the type may be mutated in the next minor revision.
        Therefore, a synthetic bit length set is constructed that is merely a list of all possible bit lengths
        plus the delimiter header.
        For example, a type that contains a single field of type ``uint32[2]`` would have the bit length set of
        ``{h, h+8, h+16, ..., h+56, h+64}`` where ``h`` is the length of the delimiter header.
        """
        # Can't use @cached_property because it is unavailable before Python 3.8 and it breaks Sphinx and MyPy.
        att = '_3476583631'
        if not hasattr(self, att):
            x = BitLengthSet(range(self.extent + 1)).pad_to_alignment(self.alignment_requirement) + \
                self.delimiter_header_type.bit_length
            setattr(self, att, x)
        out = getattr(self, att)
        assert isinstance(out, BitLengthSet)
        return out

    @property
    def delimiter_header_type(self) -> UnsignedIntegerType:
        """
        The type of the integer prefix field that encodes the size of the serialized representation [in bytes]
        of the :attr:`inner_type`.
        """
        bit_length = self._DEFAULT_DELIMITER_HEADER_BIT_LENGTH  # This may be made configurable later.
        # This is to prevent the delimiter header from breaking the alignment of the following composite.
        bit_length = max(bit_length, self.alignment_requirement)
        return UnsignedIntegerType(bit_length, UnsignedIntegerType.CastMode.SATURATED)

    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """
        Delegates the call to the inner type, but with the base offset increased by the size of the delimiter header.
        """
        base_offset = (base_offset or BitLengthSet(0)) + self.delimiter_header_type.bit_length_set
        return self.inner_type.iterate_fields_with_offsets(base_offset)

    def __repr__(self) -> str:
        return '%s(inner=%r, extent=%r)' % (self.__class__.__name__, self.inner_type, self.extent)


class ServiceType(CompositeType):
    """
    A service (not message) type.
    Unlike message types, it can't be serialized directly.

    There are exactly two pseudo-fields: ``request`` and ``response``,
    which contain the request and the response structure of the service type, respectively.
    """

    class SchemaParams:
        """A trivial helper dataclass used for constructing new instances."""
        def __init__(self,
                     attributes: typing.Iterable[Attribute],
                     extent:     typing.Optional[int],
                     is_sealed:  bool,
                     is_union:   bool):
            self.attributes = list(attributes)
            self.extent = int(extent) if extent is not None else None
            self.is_sealed = bool(is_sealed)
            self.is_union = bool(is_union)
            if self.is_sealed and self.extent is not None:  # pragma: no cover
                raise ValueError('API misuse: cannot set the extent on a sealed type')

        def construct_composite(self,
                                name: str,
                                version: Version,
                                deprecated: bool,
                                parent_service: 'ServiceType',
                                source_file_path: str) -> CompositeType:
            request_meta_type = UnionType if self.is_union else StructureType  # type: type
            ty = request_meta_type(name=name,
                                   version=version,
                                   attributes=self.attributes,
                                   deprecated=deprecated,
                                   fixed_port_id=None,
                                   source_file_path=source_file_path,
                                   parent_service=parent_service)
            assert isinstance(ty, CompositeType)
            if self.is_sealed:
                assert self.extent is None
                return ty
            else:
                return DelimitedType(ty, extent=self.extent)

    def __init__(self,
                 name:             str,
                 version:          Version,
                 request_params:   SchemaParams,
                 response_params:  SchemaParams,
                 deprecated:       bool,
                 fixed_port_id:    typing.Optional[int],
                 source_file_path: str):
        self._request_type = request_params.construct_composite(name=name + '.Request',
                                                                version=version,
                                                                deprecated=deprecated,
                                                                parent_service=self,
                                                                source_file_path=source_file_path)
        self._response_type = response_params.construct_composite(name=name + '.Response',
                                                                  version=version,
                                                                  deprecated=deprecated,
                                                                  parent_service=self,
                                                                  source_file_path=source_file_path)
        container_attributes = [
            Field(data_type=self._request_type,  name='request'),
            Field(data_type=self._response_type, name='response'),
        ]
        super(ServiceType, self).__init__(name=name,
                                          version=version,
                                          attributes=container_attributes,
                                          deprecated=deprecated,
                                          fixed_port_id=fixed_port_id,
                                          source_file_path=source_file_path)
        assert self.request_type.parent_service is self
        assert self.response_type.parent_service is self

    @property
    def bit_length_set(self) -> BitLengthSet:
        raise TypeError('Service types are not directly serializable. Use either request or response.')

    @property
    def request_type(self) -> CompositeType:
        """The type of the request schema."""
        return self._request_type

    @property
    def response_type(self) -> CompositeType:
        """The type of the response schema."""
        return self._response_type

    def iterate_fields_with_offsets(self, base_offset: typing.Optional[BitLengthSet] = None) \
            -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """Always raises a :class:`TypeError`."""
        raise TypeError('Service types do not have serializable fields. Use either request or response.')


def _unittest_composite_types() -> None:
    from pytest import raises
    from ._primitive import SignedIntegerType, FloatType
    from ._array import FixedLengthArrayType, VariableLengthArrayType

    def try_name(name: str) -> CompositeType:
        return StructureType(name=name,
                             version=Version(0, 1),
                             attributes=[],
                             deprecated=False,
                             fixed_port_id=None,
                             source_file_path='')

    with raises(InvalidNameError, match='(?i).*empty.*'):
        try_name('')

    with raises(InvalidNameError, match='(?i).*root namespace.*'):
        try_name('T')

    with raises(InvalidNameError, match='(?i).*long.*'):
        try_name('namespace.another.deeper.' * 10 + 'LongTypeName')

    with raises(InvalidNameError, match='(?i).*component.*empty.*'):
        try_name('namespace.ns..T')

    with raises(InvalidNameError, match='(?i).*component.*empty.*'):
        try_name('.namespace.ns.T')

    with raises(InvalidNameError, match='(?i).*cannot start with.*'):
        try_name('namespace.0ns.T')

    with raises(InvalidNameError, match='(?i).*cannot start with.*'):
        try_name('namespace.ns.0T')

    with raises(InvalidNameError, match='(?i).*cannot contain.*'):
        try_name('namespace.n-s.T')

    assert try_name('root.nested.T').full_name == 'root.nested.T'
    assert try_name('root.nested.T').full_namespace == 'root.nested'
    assert try_name('root.nested.T').root_namespace == 'root'
    assert try_name('root.nested.T').short_name == 'T'

    print(ServiceType(name='a' * 48 + '.T',     # No exception raised
                      version=Version(0, 1),
                      request_params=ServiceType.SchemaParams([], None, False, False),
                      response_params=ServiceType.SchemaParams([], None, False, False),
                      deprecated=False,
                      fixed_port_id=None,
                      source_file_path=''))

    with raises(MalformedUnionError, match='.*variants.*'):
        UnionType(name='a.A',
                  version=Version(0, 1),
                  attributes=[],
                  deprecated=False,
                  fixed_port_id=None,
                  source_file_path='')

    with raises(MalformedUnionError, match='(?i).*padding.*'):
        UnionType(name='a.A',
                  version=Version(0, 1),
                  attributes=[
                      Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), 'a'),
                      Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), 'b'),
                      PaddingField(VoidType(16)),
                  ],
                  deprecated=False,
                  fixed_port_id=None,
                  source_file_path='')

    u = UnionType(name='uavcan.node.Heartbeat',
                  version=Version(42, 123),
                  attributes=[
                      Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), 'a'),
                      Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), 'b'),
                      Constant(FloatType(32, PrimitiveType.CastMode.SATURATED), 'A', _expression.Rational(123)),
                  ],
                  deprecated=False,
                  fixed_port_id=None,
                  source_file_path='')
    assert u['a'].name == 'a'
    assert u['b'].name == 'b'
    assert u['A'].name == 'A'
    assert u.fields == u.fields_except_padding
    with raises(KeyError):
        assert u['c']
    assert hash(u) == hash(u)
    del u

    s = StructureType(name='a.A',
                      version=Version(0, 1),
                      attributes=[
                          PaddingField(VoidType(8)),
                          Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), 'a'),
                          PaddingField(VoidType(64)),
                          Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), 'b'),
                          PaddingField(VoidType(2)),
                          Constant(FloatType(32, PrimitiveType.CastMode.SATURATED), 'A', _expression.Rational(123)),
                      ],
                      deprecated=False,
                      fixed_port_id=None,
                      source_file_path='')
    assert s['a'].name == 'a'
    assert s['b'].name == 'b'
    assert s['A'].name == 'A'
    assert len(s.constants) == 1
    assert len(s.fields) == 5
    assert len(s.fields_except_padding) == 2
    with raises(KeyError):
        assert s['c']
    with raises(KeyError):
        assert s['']        # Padding fields are not accessible
    assert hash(s) == hash(s)

    d = DelimitedType(s, None)
    assert d.inner_type is s
    assert d.attributes == d.inner_type.attributes
    with raises(KeyError):
        assert d['c']
    assert hash(d) == hash(d)
    assert d.delimiter_header_type.bit_length == 32
    assert isinstance(d.delimiter_header_type, UnsignedIntegerType)
    assert d.extent == d.inner_type.extent * 3 // 2

    d = DelimitedType(s, 256)
    assert hash(d) == hash(d)
    assert d.delimiter_header_type.bit_length == 32
    assert isinstance(d.delimiter_header_type, UnsignedIntegerType)
    assert d.extent == 256

    d = DelimitedType(s, s.extent)  # Minimal extent
    assert hash(d) == hash(d)
    assert d.delimiter_header_type.bit_length == 32
    assert isinstance(d.delimiter_header_type, UnsignedIntegerType)
    assert d.extent == s.extent == d.inner_type.extent

    with raises(InvalidExtentError):
        assert DelimitedType(s, 255)  # Unaligned extent

    with raises(InvalidExtentError):
        assert DelimitedType(s, 8)  # Extent too small

    def try_union_fields(field_types: typing.List[SerializableType]) -> UnionType:
        atr = []
        for i, t in enumerate(field_types):
            atr.append(Field(t, '_%d' % i))

        return UnionType(name='a.A',
                         version=Version(0, 1),
                         attributes=atr,
                         deprecated=False,
                         fixed_port_id=None,
                         source_file_path='')

    u = try_union_fields([
        UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ])
    assert u.bit_length_set == {24}
    assert u.extent == 24
    assert DelimitedType(u, None).extent == 40
    assert DelimitedType(u, None).bit_length_set == {32, 40, 48, 56, 64, 72}
    assert DelimitedType(u, 24).extent == 24
    assert DelimitedType(u, 24).bit_length_set == {32, 40, 48, 56}
    assert DelimitedType(u, 32).extent == 32
    assert DelimitedType(u, 32).bit_length_set == {32, 40, 48, 56, 64}
    assert DelimitedType(u, 800).extent == 800

    assert try_union_fields(
        [
            UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
            SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
        ] * 257
    ).bit_length_set == {16 + 16}

    assert try_union_fields(
        [
            UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
            SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
        ] * 32769
    ).bit_length_set == {32 + 16}

    # The reference values for the following test are explained in the array tests above
    tu8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    small = VariableLengthArrayType(tu8, 2)
    outer = FixedLengthArrayType(small, 2)   # unpadded bit length values: {4, 12, 20, 28, 36}

    # Above plus one bit to each, plus 16-bit for the unsigned integer field
    assert try_union_fields([
        outer,
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ]).bit_length_set == {24, 32, 40, 48, 56}

    def try_struct_fields(field_types: typing.List[SerializableType]) -> StructureType:
        atr = []
        for i, t in enumerate(field_types):
            atr.append(Field(t, '_%d' % i))

        return StructureType(name='a.A',
                             version=Version(0, 1),
                             attributes=atr,
                             deprecated=False,
                             fixed_port_id=None,
                             source_file_path='')

    s = try_struct_fields([
        UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ])
    assert s.bit_length_set == {32}
    assert s.extent == 32
    assert DelimitedType(s, None).extent == 48
    assert DelimitedType(s, None).bit_length_set == {32, 40, 48, 56, 64, 72, 80}
    assert DelimitedType(s, 32).extent == 32
    assert DelimitedType(s, 32).bit_length_set == {32, 40, 48, 56, 64}
    assert DelimitedType(s, 40).extent == 40
    assert DelimitedType(s, 40).bit_length_set == {32, 40, 48, 56, 64, 72}

    assert try_struct_fields([]).bit_length_set == {0}   # Empty sets forbidden

    assert try_struct_fields([
        outer,
        SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
    ]).bit_length_set == {16 + 16, 24 + 16, 32 + 16, 40 + 16, 48 + 16}

    assert try_struct_fields([outer]).bit_length_set == {16, 24, 32, 40, 48}


def _unittest_field_iterators() -> None:
    from pytest import raises
    from ._primitive import BooleanType, FloatType
    from ._array import FixedLengthArrayType, VariableLengthArrayType

    saturated = PrimitiveType.CastMode.SATURATED
    _seq_no = 0

    def make_type(meta: typing.Type[CompositeType], attributes: typing.Iterable[Attribute]) -> CompositeType:
        nonlocal _seq_no
        _seq_no += 1
        return meta('ns.Type' + str(_seq_no),
                    version=Version(1, 0),
                    attributes=attributes,
                    deprecated=False,
                    fixed_port_id=None,
                    source_file_path='')

    def validate_iterator(t: CompositeType,
                          reference: typing.Iterable[typing.Tuple[str, typing.Set[int]]],
                          base_offset: typing.Optional[BitLengthSet] = None) -> None:
        for (name, ref_set), (field, real_set) in itertools.zip_longest(reference,
                                                                        t.iterate_fields_with_offsets(base_offset)):
            assert field.name == name
            assert real_set == ref_set, field.name + ': ' + str(real_set)

    a = make_type(StructureType, [
        Field(UnsignedIntegerType(10, saturated), 'a'),
        Field(BooleanType(saturated), 'b'),
        Field(VariableLengthArrayType(FloatType(32, saturated), 2), 'c'),
        Field(FixedLengthArrayType(FloatType(32, saturated), 7), 'd'),
        PaddingField(VoidType(3)),
    ])

    validate_iterator(a, [
        ('a', {0}),
        ('b', {10}),
        ('c', {11}),
        ('d', {
            11 + 8 + 32 * 0,
            11 + 8 + 32 * 1,
            11 + 8 + 32 * 2,
        }),
        ('', {
            11 + 8 + 32 * 0 + 32 * 7,
            11 + 8 + 32 * 1 + 32 * 7,
            11 + 8 + 32 * 2 + 32 * 7,
        }),
    ])

    d = DelimitedType(a, None)
    validate_iterator(d, [
        ('a', {32 + 0}),
        ('b', {32 + 10}),
        ('c', {32 + 11}),
        ('d', {
            32 + 11 + 8 + 32 * 0,
            32 + 11 + 8 + 32 * 1,
            32 + 11 + 8 + 32 * 2,
        }),
        ('', {
            32 + 11 + 8 + 32 * 0 + 32 * 7,
            32 + 11 + 8 + 32 * 1 + 32 * 7,
            32 + 11 + 8 + 32 * 2 + 32 * 7,
        }),
    ])
    print('d.bit_length_set', d.bit_length_set)
    assert d.bit_length_set == BitLengthSet({
        32 + x for x in range(((11 + 8 + 32 * 2 + 32 * 7) + 7) // 8 * 8 * 3 // 2 + 1)
    }).pad_to_alignment(8)

    a_bls_options = [
        11 + 8 + 32 * 0 + 32 * 7 + 3,
        11 + 8 + 32 * 1 + 32 * 7 + 3,
        11 + 8 + 32 * 2 + 32 * 7 + 3,
    ]
    assert a.bit_length_set == BitLengthSet(a_bls_options).pad_to_alignment(8)

    # Testing "a" again, this time with non-zero base offset.
    # The first base offset element is one, but it is padded to byte, so it becomes 8.
    validate_iterator(a, [
        ('a', {8, 16}),
        ('b', {8 + 10, 16 + 10}),
        ('c', {8 + 11, 16 + 11}),
        ('d', {
            8 + 11 + 8 + 32 * 0,
            8 + 11 + 8 + 32 * 1,
            8 + 11 + 8 + 32 * 2,
            16 + 11 + 8 + 32 * 0,
            16 + 11 + 8 + 32 * 1,
            16 + 11 + 8 + 32 * 2,
        }),
        ('', {
            8 + 11 + 8 + 32 * 0 + 32 * 7,
            8 + 11 + 8 + 32 * 1 + 32 * 7,
            8 + 11 + 8 + 32 * 2 + 32 * 7,
            16 + 11 + 8 + 32 * 0 + 32 * 7,
            16 + 11 + 8 + 32 * 1 + 32 * 7,
            16 + 11 + 8 + 32 * 2 + 32 * 7,
        }),
    ], BitLengthSet({1, 16}))  # 1 becomes 8 due to padding.

    # Wrap the above into a delimited type with a manually specified extent.
    d = DelimitedType(a, 400)
    validate_iterator(d, [
        ('a', {32 + 8, 32 + 16}),
        ('b', {32 + 8 + 10, 32 + 16 + 10}),
        ('c', {32 + 8 + 11, 32 + 16 + 11}),
        ('d', {
            32 + 8 + 11 + 8 + 32 * 0,
            32 + 8 + 11 + 8 + 32 * 1,
            32 + 8 + 11 + 8 + 32 * 2,
            32 + 16 + 11 + 8 + 32 * 0,
            32 + 16 + 11 + 8 + 32 * 1,
            32 + 16 + 11 + 8 + 32 * 2,
        }),
        ('', {
            32 + 8 + 11 + 8 + 32 * 0 + 32 * 7,
            32 + 8 + 11 + 8 + 32 * 1 + 32 * 7,
            32 + 8 + 11 + 8 + 32 * 2 + 32 * 7,
            32 + 16 + 11 + 8 + 32 * 0 + 32 * 7,
            32 + 16 + 11 + 8 + 32 * 1 + 32 * 7,
            32 + 16 + 11 + 8 + 32 * 2 + 32 * 7,
        }),
    ], BitLengthSet({1, 16}))  # 1 becomes 8 due to padding.
    assert d.bit_length_set == BitLengthSet({(32 + x + 7) // 8 * 8 for x in range(400 + 1)})

    b = make_type(StructureType, [
        Field(a, 'z'),
        Field(VariableLengthArrayType(a, 2), 'y'),
        Field(UnsignedIntegerType(6, saturated), 'x'),
    ])

    a_bls_padded = [((x + 7) // 8) * 8 for x in a_bls_options]
    validate_iterator(b, [
        ('z', {0}),
        ('y', {
            a_bls_padded[0],
            a_bls_padded[1],
            a_bls_padded[2],
        }),
        ('x', {  # The lone "+2" is for the variable-length array's implicit length field
            # First length option of z
            a_bls_padded[0] + 8 + a_bls_padded[0] * 0,  # suka
            a_bls_padded[0] + 8 + a_bls_padded[1] * 0,
            a_bls_padded[0] + 8 + a_bls_padded[2] * 0,
            a_bls_padded[0] + 8 + a_bls_padded[0] * 1,
            a_bls_padded[0] + 8 + a_bls_padded[1] * 1,
            a_bls_padded[0] + 8 + a_bls_padded[2] * 1,
            a_bls_padded[0] + 8 + a_bls_padded[0] * 2,
            a_bls_padded[0] + 8 + a_bls_padded[1] * 2,
            a_bls_padded[0] + 8 + a_bls_padded[2] * 2,
            # Second length option of z
            a_bls_padded[1] + 8 + a_bls_padded[0] * 0,
            a_bls_padded[1] + 8 + a_bls_padded[1] * 0,
            a_bls_padded[1] + 8 + a_bls_padded[2] * 0,
            a_bls_padded[1] + 8 + a_bls_padded[0] * 1,
            a_bls_padded[1] + 8 + a_bls_padded[1] * 1,
            a_bls_padded[1] + 8 + a_bls_padded[2] * 1,
            a_bls_padded[1] + 8 + a_bls_padded[0] * 2,
            a_bls_padded[1] + 8 + a_bls_padded[1] * 2,
            a_bls_padded[1] + 8 + a_bls_padded[2] * 2,
            # Third length option of z
            a_bls_padded[2] + 8 + a_bls_padded[0] * 0,
            a_bls_padded[2] + 8 + a_bls_padded[1] * 0,
            a_bls_padded[2] + 8 + a_bls_padded[2] * 0,
            a_bls_padded[2] + 8 + a_bls_padded[0] * 1,
            a_bls_padded[2] + 8 + a_bls_padded[1] * 1,
            a_bls_padded[2] + 8 + a_bls_padded[2] * 1,
            a_bls_padded[2] + 8 + a_bls_padded[0] * 2,
            a_bls_padded[2] + 8 + a_bls_padded[1] * 2,
            a_bls_padded[2] + 8 + a_bls_padded[2] * 2,
        }),
    ])

    # Ensuring the equivalency between bit length and aligned bit offset
    b_offset = BitLengthSet()
    for f in b.fields:
        b_offset += f.data_type.bit_length_set
    print('b_offset:', b_offset)
    assert b_offset.pad_to_alignment(8) == b.bit_length_set
    assert not b_offset.is_aligned_at_byte()
    assert not b_offset.is_aligned_at(32)

    c = make_type(UnionType, [
        Field(a, 'foo'),
        Field(b, 'bar'),
    ])

    validate_iterator(c, [
        ('foo', {8}),       # The offset is the same because it's a union
        ('bar', {8}),
    ])

    validate_iterator(c, [
        ('foo', {8 + 8}),
        ('bar', {8 + 8}),
    ], BitLengthSet(8))

    validate_iterator(c, [
        ('foo', {0 + 8, 8 + 8}),
        ('bar', {0 + 8, 8 + 8}),
    ], BitLengthSet({0, 4, 8}))  # The option 4 is eliminated due to padding to byte, so we're left with {0, 8}.

    with raises(TypeError, match='.*request or response.*'):
        ServiceType(name='ns.S',
                    version=Version(1, 0),
                    request_params=ServiceType.SchemaParams([], None, False, False),
                    response_params=ServiceType.SchemaParams([], None, False, False),
                    deprecated=False,
                    fixed_port_id=None,
                    source_file_path='').iterate_fields_with_offsets()

    # Check the auto-padding logic.
    e = StructureType(name='e.E',
                      version=Version(0, 1),
                      attributes=[],
                      deprecated=False,
                      fixed_port_id=None,
                      source_file_path='')
    validate_iterator(e, [])
    a = make_type(StructureType, [
        Field(UnsignedIntegerType(3, PrimitiveType.CastMode.TRUNCATED), 'x'),
        Field(e, 'y'),
        Field(UnsignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED), 'z'),
    ])
    assert a.bit_length_set == {16}
    validate_iterator(a, [
        ('x', {0}),
        ('y', {8}),  # Padded out!
        ('z', {8}),
    ])
