# Copyright (c) 2018 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>

import abc
import math
import typing
import itertools
from .. import _expression
from .. import _port_id_ranges
from .._bit_length_set import BitLengthSet
from ._serializable import SerializableType, TypeParameterError
from ._attribute import Attribute, Field, PaddingField, Constant
from ._name import check_name, InvalidNameError
from ._void import VoidType
from ._primitive import PrimitiveType, UnsignedIntegerType


Version = typing.NamedTuple("Version", [("major", int), ("minor", int)])


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

    MAX_NAME_LENGTH = 255
    MAX_VERSION_NUMBER = 255
    NAME_COMPONENT_SEPARATOR = "."

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        version: Version,
        attributes: typing.Iterable[Attribute],
        deprecated: bool,
        fixed_port_id: typing.Optional[int],
        source_file_path: str,
        has_parent_service: bool,
        doc: str = "",
    ):
        super().__init__()

        self._name = str(name).strip()
        self._version = version
        self._attributes = list(attributes)
        self._attributes_by_name = {a.name: a for a in self._attributes if not isinstance(a, PaddingField)}
        self._deprecated = bool(deprecated)
        self._fixed_port_id = None if fixed_port_id is None else int(fixed_port_id)
        self._source_file_path = str(source_file_path)
        self._has_parent_service = bool(has_parent_service)

        self._doc = doc

        # Name check
        if not self._name:
            raise InvalidNameError("Composite type name cannot be empty")

        if self.NAME_COMPONENT_SEPARATOR not in self._name:
            raise InvalidNameError("Root namespace is not specified")

        if len(self._name) > self.MAX_NAME_LENGTH:
            # TODO
            # Notice that per the Specification, service request/response types are unnamed,
            # but we actually name them the same as the parent service plus the ".Request"/".Response" suffix.
            # This may trigger a name length error for long-named service types where per the Specification
            # no such error may occur. We expect the Specification to catch up with this behavior in a later
            # revision where the names for the request and response parts are actually properly specified.
            raise InvalidNameError(
                "Name is too long: %r is longer than %d characters" % (self._name, self.MAX_NAME_LENGTH)
            )

        for component in self._name.split(self.NAME_COMPONENT_SEPARATOR):
            check_name(component)

        # Version check
        version_valid = (
            (0 <= self._version.major <= self.MAX_VERSION_NUMBER)
            and (0 <= self._version.minor <= self.MAX_VERSION_NUMBER)
            and ((self._version.major + self._version.minor) > 0)
        )

        if not version_valid:
            raise InvalidVersionError("Invalid version numbers: %s.%s" % (self._version.major, self._version.minor))

        # Attribute check
        used_names = set()  # type: typing.Set[str]
        for a in self._attributes:
            if a.name and a.name in used_names:
                raise AttributeNameCollisionError("Multiple attributes under the same name: %r" % a.name)
            used_names.add(a.name)

        # Port ID check
        port_id = self._fixed_port_id
        if port_id is not None:
            assert port_id is not None
            if isinstance(self, ServiceType):
                if not (0 <= port_id <= _port_id_ranges.MAX_SERVICE_ID):
                    raise InvalidFixedPortIDError("Fixed service ID %r is not valid" % port_id)
            else:
                if not (0 <= port_id <= _port_id_ranges.MAX_SUBJECT_ID):
                    raise InvalidFixedPortIDError("Fixed subject ID %r is not valid" % port_id)

        # Consistent deprecation check.
        # A non-deprecated type cannot be dependent on deprecated types.
        # A deprecated type can be dependent on anything.
        if not self.deprecated:
            for a in self._attributes:
                t = a.data_type
                if isinstance(t, CompositeType):
                    if t.deprecated:
                        raise DeprecatedDependencyError(
                            "A type cannot depend on deprecated types " "unless it is also deprecated."
                        )

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
    def doc(self) -> str:
        """The DSDL header comment provided for this data type without the leading #."""
        return self._doc

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
        If the type is sealed, its extent equals ``bit_length_set.max``.
        """
        return self.bit_length_set.max

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
    def inner_type(self) -> "CompositeType":
        """
        If the concrete type is a decorator over another Composite (such as :class:`DelimitedType`),
        this property provides access to the decorated instance.
        Otherwise, returns the current instance reference unchanged.
        This is intended for use in scenarios where the decoration is irrelevant and the user needs to know
        the concrete type of the decorated instance.
        """
        return self

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
    def has_parent_service(self) -> bool:
        """
        :class:`pydsdl.ServiceType` contains two special fields of this type: ``request`` and ``response``.
        This property is True if this type is a service request/response type.
        The version and deprecation status are shared with that of the parent service.
        The name of the parent service equals the full namespace name of this type.
        For example: ``ns.Service.Request.2.3`` --> ``ns.Service.2.3``.
        """
        return self._has_parent_service

    @abc.abstractmethod
    def iterate_fields_with_offsets(
        self, base_offset: BitLengthSet = BitLengthSet(0)
    ) -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
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
        """
        raise NotImplementedError

    def _attribute(self, name: _expression.String) -> _expression.Any:
        """This is the handler for DSDL expressions like ``uavcan.node.Heartbeat.1.0.MODE_OPERATIONAL``."""
        for c in self.constants:
            if c.name == name.native_value:
                assert isinstance(c.value, _expression.Any)
                return c.value

        if name.native_value == "_extent_":  # Experimental non-standard extension
            return _expression.Rational(self.extent)

        return super()._attribute(name)  # Hand over up the inheritance chain, this is important

    def __getitem__(self, attribute_name: str) -> Attribute:
        """
        Allows the caller to retrieve an attribute by name.
        Padding fields are not accessible via this interface because they don't have names.
        Raises :class:`KeyError` if there is no such attribute.
        """
        return self._attributes_by_name[attribute_name]

    def __str__(self) -> str:
        """Returns a string like ``uavcan.node.Heartbeat.1.0``."""
        return "%s.%d.%d" % (self.full_name, self.version.major, self.version.minor)

    def __repr__(self) -> str:
        return (
            "%s(name=%r, version=%r, fields=%r, constants=%r, alignment_requirement=%r, "
            "deprecated=%r, fixed_port_id=%r)"
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

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        version: Version,
        attributes: typing.Iterable[Attribute],
        deprecated: bool,
        fixed_port_id: typing.Optional[int],
        source_file_path: str,
        has_parent_service: bool,
        doc: str = "",
    ):
        # Proxy all parameters directly to the base type - I wish we could do that
        # with kwargs while preserving the type information
        super().__init__(
            name=name,
            version=version,
            attributes=attributes,
            deprecated=deprecated,
            fixed_port_id=fixed_port_id,
            source_file_path=source_file_path,
            has_parent_service=has_parent_service,
            doc=doc,
        )

        if self.number_of_variants < self.MIN_NUMBER_OF_VARIANTS:
            raise MalformedUnionError(
                "A tagged union cannot contain fewer than %d variants" % self.MIN_NUMBER_OF_VARIANTS
            )

        for a in attributes:
            if isinstance(a, PaddingField) or not a.name or isinstance(a.data_type, VoidType):
                raise MalformedUnionError("Padding fields not allowed in unions")

        self._tag_field_type = UnsignedIntegerType(
            self._compute_tag_bit_length([x.data_type for x in self.fields]), PrimitiveType.CastMode.TRUNCATED
        )

        self._bls = self.aggregate_bit_length_sets(
            [f.data_type for f in self.fields],
        ).pad_to_alignment(self.alignment_requirement)

    @property
    def bit_length_set(self) -> BitLengthSet:
        return self._bls

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

    def iterate_fields_with_offsets(
        self, base_offset: BitLengthSet = BitLengthSet(0)
    ) -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """See the base class."""
        offset = base_offset.pad_to_alignment(self.alignment_requirement) + self.tag_field_type.bit_length
        for f in self.fields:  # Same offset for every field, because it's a tagged union, not a struct
            assert offset.is_aligned_at(f.data_type.alignment_requirement)
            yield f, offset

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
        return tbl + BitLengthSet.unite(ms)

    @staticmethod
    def _compute_tag_bit_length(field_types: typing.Sequence[SerializableType]) -> int:
        assert len(field_types) > 1, "Internal API misuse"
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

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        version: Version,
        attributes: typing.Iterable[Attribute],
        deprecated: bool,
        fixed_port_id: typing.Optional[int],
        source_file_path: str,
        has_parent_service: bool,
        doc: str = "",
    ):
        super().__init__(
            name=name,
            version=version,
            attributes=attributes,
            deprecated=deprecated,
            fixed_port_id=fixed_port_id,
            source_file_path=source_file_path,
            has_parent_service=has_parent_service,
            doc=doc,
        )
        self._bls = self.aggregate_bit_length_sets(
            [f.data_type for f in self.fields],
        ).pad_to_alignment(self.alignment_requirement)

    def iterate_fields_with_offsets(
        self, base_offset: BitLengthSet = BitLengthSet(0)
    ) -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """See the base class."""
        offset = base_offset.pad_to_alignment(self.alignment_requirement)
        for f in self.fields:
            offset = offset.pad_to_alignment(f.data_type.alignment_requirement)
            yield f, offset
            offset = offset + f.data_type.bit_length_set

    @property
    def bit_length_set(self) -> BitLengthSet:
        return self._bls

    @staticmethod
    def aggregate_bit_length_sets(field_types: typing.Sequence[SerializableType]) -> BitLengthSet:
        """
        Computes the bit length set for a structure type given the type of each of its fields.
        The final padding is not applied (but inter-field padding obviously is).
        """
        bls = field_types[0].bit_length_set if len(field_types) > 0 else BitLengthSet(0)
        for t in field_types[1:]:
            bls = bls.pad_to_alignment(t.alignment_requirement) + t.bit_length_set
        return bls


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

    _DEFAULT_DELIMITER_HEADER_BIT_LENGTH = 32

    def __init__(self, inner: CompositeType, extent: int):
        self._inner = inner
        super().__init__(
            name=inner.full_name,
            version=inner.version,
            attributes=inner.attributes,
            deprecated=inner.deprecated,
            fixed_port_id=inner.fixed_port_id,
            source_file_path=inner.source_file_path,
            has_parent_service=inner.has_parent_service,
            doc=inner.doc,
        )
        self._extent = int(extent)
        if self._extent % self.alignment_requirement != 0:
            raise InvalidExtentError(
                "The specified extent of %d bits is not a multiple of %d bits"
                % (self._extent, self.alignment_requirement)
            )
        if self._extent < inner.extent:
            raise InvalidExtentError(
                "The specified extent of %d bits is too small for this data type. "
                "Either compactify the data type or increase the extent at least to %d bits. "
                "Beware that the latter option may break wire compatibility." % (self._extent, inner.extent)
            )

        delimiter_header_bit_length = self._DEFAULT_DELIMITER_HEADER_BIT_LENGTH  # This may be made configurable later.
        # This is to prevent the delimiter header from breaking the alignment of the following composite.
        delimiter_header_bit_length = max(delimiter_header_bit_length, self.alignment_requirement)
        self._delimiter_header_type = UnsignedIntegerType(
            delimiter_header_bit_length, UnsignedIntegerType.CastMode.TRUNCATED
        )

        self._bls = self.delimiter_header_type.bit_length + BitLengthSet(self.alignment_requirement).repeat_range(
            self._extent // self.alignment_requirement
        )

        assert self.extent % self.BITS_PER_BYTE == 0
        assert self.extent % self.alignment_requirement == 0
        assert self.extent >= self.inner_type.extent
        assert self.bit_length_set.is_aligned_at_byte()
        assert self.bit_length_set.is_aligned_at(self.alignment_requirement)
        assert self.extent >= (self.bit_length_set.max - self.delimiter_header_type.bit_length)
        assert self.has_parent_service == inner.has_parent_service

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
        The extent of a delimited type is specified explicitly via ``@extent EXPRESSION``,
        where the expression shall yield an integer multiple of 8.

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
        return self._bls

    @property
    def delimiter_header_type(self) -> UnsignedIntegerType:
        """
        The type of the integer prefix field that encodes the size of the serialized representation [in bytes]
        of the :attr:`inner_type`.
        """
        return self._delimiter_header_type

    def iterate_fields_with_offsets(
        self, base_offset: BitLengthSet = BitLengthSet(0)
    ) -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """
        Delegates the call to the inner type, but with the base offset increased by the size of the delimiter header.
        """
        base_offset = base_offset + self.delimiter_header_type.bit_length_set
        return self.inner_type.iterate_fields_with_offsets(base_offset)

    def __repr__(self) -> str:
        return "%s(inner=%r, extent=%r)" % (self.__class__.__name__, self.inner_type, self.extent)


class ServiceType(CompositeType):
    """
    A service (not message) type.
    Unlike message types, it can't be serialized directly.

    There are exactly two pseudo-fields: ``request`` and ``response``,
    which contain the request and the response structure of the service type, respectively.
    """

    def __init__(self, request: CompositeType, response: CompositeType, fixed_port_id: typing.Optional[int]):
        name = request.full_namespace
        consistent = (
            request.full_name.startswith(name)
            and response.full_name.startswith(name)
            and request.version == response.version
            and not isinstance(request, ServiceType)
            and not isinstance(response, ServiceType)
            and request.deprecated == response.deprecated
            and request.source_file_path == response.source_file_path
            and request.fixed_port_id is None
            and response.fixed_port_id is None
            and request.has_parent_service
            and response.has_parent_service
        )
        if not consistent:
            raise ValueError("Internal error: service request/response type consistency error")

        self._request_type = request
        self._response_type = response
        container_attributes = [
            Field(data_type=self._request_type, name="request"),
            Field(data_type=self._response_type, name="response"),
        ]
        super().__init__(
            name=name,
            version=request.version,
            attributes=container_attributes,
            deprecated=request.deprecated,
            fixed_port_id=fixed_port_id,
            source_file_path=request.source_file_path,
            has_parent_service=False,
            doc=request.doc,
        )

    @property
    def bit_length_set(self) -> BitLengthSet:
        raise TypeError("Service types are not directly serializable. Use either request or response.")

    @property
    def request_type(self) -> CompositeType:
        assert self._request_type.has_parent_service
        return self._request_type

    @property
    def response_type(self) -> CompositeType:
        assert self._response_type.has_parent_service
        return self._response_type

    def iterate_fields_with_offsets(
        self, base_offset: BitLengthSet = BitLengthSet(0)
    ) -> typing.Iterator[typing.Tuple[Field, BitLengthSet]]:
        """Always raises a :class:`TypeError`."""
        raise TypeError("Service types do not have serializable fields. Use either request or response.")


def _unittest_composite_types() -> None:  # pylint: disable=too-many-statements
    from pytest import raises
    from ._primitive import SignedIntegerType, FloatType
    from ._array import FixedLengthArrayType, VariableLengthArrayType

    def try_name(name: str) -> CompositeType:
        return StructureType(
            name=name,
            version=Version(0, 1),
            attributes=[],
            deprecated=False,
            fixed_port_id=None,
            source_file_path="",
            has_parent_service=False,
        )

    with raises(InvalidNameError, match="(?i).*empty.*"):
        try_name("")

    with raises(InvalidNameError, match="(?i).*root namespace.*"):
        try_name("T")

    with raises(InvalidNameError, match="(?i).*long.*"):
        try_name("namespace.another.deeper." * 10 + "LongTypeName")

    with raises(InvalidNameError, match="(?i).*component.*empty.*"):
        try_name("namespace.ns..T")

    with raises(InvalidNameError, match="(?i).*component.*empty.*"):
        try_name(".namespace.ns.T")

    with raises(InvalidNameError, match="(?i).*cannot start with.*"):
        try_name("namespace.0ns.T")

    with raises(InvalidNameError, match="(?i).*cannot start with.*"):
        try_name("namespace.ns.0T")

    with raises(InvalidNameError, match="(?i).*cannot contain.*"):
        try_name("namespace.n-s.T")

    assert try_name("root.nested.T").full_name == "root.nested.T"
    assert try_name("root.nested.T").full_namespace == "root.nested"
    assert try_name("root.nested.T").root_namespace == "root"
    assert try_name("root.nested.T").short_name == "T"

    with raises(MalformedUnionError, match=".*variants.*"):
        UnionType(
            name="a.A",
            version=Version(0, 1),
            attributes=[],
            deprecated=False,
            fixed_port_id=None,
            source_file_path="",
            has_parent_service=False,
        )

    with raises(MalformedUnionError, match="(?i).*padding.*"):
        UnionType(
            name="a.A",
            version=Version(0, 1),
            attributes=[
                Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), "a"),
                Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), "b"),
                PaddingField(VoidType(16)),
            ],
            deprecated=False,
            fixed_port_id=None,
            source_file_path="",
            has_parent_service=False,
        )

    u = UnionType(
        name="uavcan.node.Heartbeat",
        version=Version(42, 123),
        attributes=[
            Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), "a"),
            Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), "b"),
            Constant(FloatType(32, PrimitiveType.CastMode.SATURATED), "A", _expression.Rational(123)),
        ],
        deprecated=False,
        fixed_port_id=None,
        source_file_path="",
        has_parent_service=False,
    )
    assert u["a"].name == "a"
    assert u["b"].name == "b"
    assert u["A"].name == "A"
    assert u.fields == u.fields_except_padding
    with raises(KeyError):
        assert u["c"]
    assert hash(u) == hash(u)
    assert not u.has_parent_service
    del u

    s = StructureType(
        name="a.A",
        version=Version(0, 1),
        attributes=[
            PaddingField(VoidType(8)),
            Field(UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED), "a"),
            PaddingField(VoidType(64)),
            Field(SignedIntegerType(16, PrimitiveType.CastMode.SATURATED), "b"),
            PaddingField(VoidType(2)),
            Constant(FloatType(32, PrimitiveType.CastMode.SATURATED), "A", _expression.Rational(123)),
        ],
        deprecated=False,
        fixed_port_id=None,
        source_file_path="",
        has_parent_service=False,
    )
    assert s["a"].name == "a"
    assert s["b"].name == "b"
    assert s["A"].name == "A"
    assert len(s.constants) == 1
    assert len(s.fields) == 5
    assert len(s.fields_except_padding) == 2
    with raises(KeyError):
        assert s["c"]
    with raises(KeyError):
        assert s[""]  # Padding fields are not accessible
    assert hash(s) == hash(s)
    assert not s.has_parent_service
    assert s.inner_type is s
    assert s.inner_type.inner_type is s

    d = DelimitedType(s, 2048)
    assert d.inner_type is s
    assert d.inner_type.inner_type is s
    assert d.attributes == d.inner_type.attributes
    with raises(KeyError):
        assert d["c"]
    assert hash(d) == hash(d)
    assert d.delimiter_header_type.bit_length == 32
    assert isinstance(d.delimiter_header_type, UnsignedIntegerType)
    assert d.delimiter_header_type.cast_mode == PrimitiveType.CastMode.TRUNCATED
    assert d.extent == 2048

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
            atr.append(Field(t, "_%d" % i))

        return UnionType(
            name="a.A",
            version=Version(0, 1),
            attributes=atr,
            deprecated=False,
            fixed_port_id=None,
            source_file_path="",
            has_parent_service=False,
        )

    u = try_union_fields(
        [
            UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
            SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
        ]
    )
    assert u.inner_type is u
    assert u.inner_type.inner_type is u
    assert u.bit_length_set == {24}
    assert u.extent == 24
    assert DelimitedType(u, 40).extent == 40
    assert set(DelimitedType(u, 40).bit_length_set) == {32, 40, 48, 56, 64, 72}
    assert DelimitedType(u, 40).bit_length_set == {32, 40, 48, 56, 64, 72}
    assert DelimitedType(u, 24).extent == 24
    assert DelimitedType(u, 24).bit_length_set == {32, 40, 48, 56}
    assert DelimitedType(u, 32).extent == 32
    assert DelimitedType(u, 32).bit_length_set == {32, 40, 48, 56, 64}
    assert DelimitedType(u, 800).extent == 800
    assert DelimitedType(u, 800).inner_type is u
    assert DelimitedType(u, 800).inner_type.inner_type is u

    assert (
        try_union_fields(
            [
                UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
                SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
            ]
            * 257
        ).bit_length_set
        == {16 + 16}
    )

    assert (
        try_union_fields(
            [
                UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
                SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
            ]
            * 32769
        ).bit_length_set
        == {32 + 16}
    )

    # The reference values for the following test are explained in the array tests above
    tu8 = UnsignedIntegerType(8, cast_mode=PrimitiveType.CastMode.TRUNCATED)
    small = VariableLengthArrayType(tu8, 2)
    outer = FixedLengthArrayType(small, 2)  # unpadded bit length values: {4, 12, 20, 28, 36}

    # Above plus one bit to each, plus 16-bit for the unsigned integer field
    assert (
        try_union_fields(
            [
                outer,
                SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
            ]
        ).bit_length_set
        == {24, 32, 40, 48, 56}
    )

    def try_struct_fields(field_types: typing.List[SerializableType]) -> StructureType:
        atr = []
        for i, t in enumerate(field_types):
            atr.append(Field(t, "_%d" % i))

        return StructureType(
            name="a.A",
            version=Version(0, 1),
            attributes=atr,
            deprecated=False,
            fixed_port_id=None,
            source_file_path="",
            has_parent_service=False,
        )

    s = try_struct_fields(
        [
            UnsignedIntegerType(16, PrimitiveType.CastMode.TRUNCATED),
            SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
        ]
    )
    assert s.bit_length_set == {32}
    assert s.extent == 32
    assert DelimitedType(s, 48).extent == 48
    assert DelimitedType(s, 48).bit_length_set == {32, 40, 48, 56, 64, 72, 80}
    assert DelimitedType(s, 32).extent == 32
    assert DelimitedType(s, 32).bit_length_set == {32, 40, 48, 56, 64}
    assert DelimitedType(s, 40).extent == 40
    assert DelimitedType(s, 40).bit_length_set == {32, 40, 48, 56, 64, 72}

    assert try_struct_fields([]).bit_length_set == {0}  # Empty sets forbidden

    assert (
        try_struct_fields(
            [
                outer,
                SignedIntegerType(16, PrimitiveType.CastMode.SATURATED),
            ]
        ).bit_length_set
        == {16 + 16, 24 + 16, 32 + 16, 40 + 16, 48 + 16}
    )

    assert try_struct_fields([outer]).bit_length_set == {16, 24, 32, 40, 48}


def _unittest_field_iterators() -> None:  # pylint: disable=too-many-locals
    from pytest import raises
    from ._primitive import BooleanType, FloatType
    from ._array import FixedLengthArrayType, VariableLengthArrayType

    saturated = PrimitiveType.CastMode.SATURATED
    _seq_no = 0

    def make_type(meta: typing.Type[CompositeType], attributes: typing.Iterable[Attribute]) -> CompositeType:
        nonlocal _seq_no
        _seq_no += 1
        return meta(
            "ns.Type" + str(_seq_no),
            version=Version(1, 0),
            attributes=attributes,
            deprecated=False,
            fixed_port_id=None,
            source_file_path="",
            has_parent_service=False,
        )

    def validate_iterator(
        t: CompositeType,
        reference: typing.Iterable[typing.Tuple[str, typing.Set[int]]],
        base_offset: BitLengthSet = BitLengthSet(0),
    ) -> None:
        for (name, ref_set), (field, real_set) in itertools.zip_longest(
            reference, t.iterate_fields_with_offsets(base_offset)
        ):
            assert field.name == name
            assert real_set == ref_set, field.name + ": " + str(real_set)

    a = make_type(
        StructureType,
        [
            Field(UnsignedIntegerType(10, saturated), "a"),
            Field(BooleanType(saturated), "b"),
            Field(VariableLengthArrayType(FloatType(32, saturated), 2), "c"),
            Field(FixedLengthArrayType(FloatType(32, saturated), 7), "d"),
            PaddingField(VoidType(3)),
        ],
    )

    validate_iterator(
        a,
        [
            ("a", {0}),
            ("b", {10}),
            ("c", {11}),
            (
                "d",
                {
                    11 + 8 + 32 * 0,
                    11 + 8 + 32 * 1,
                    11 + 8 + 32 * 2,
                },
            ),
            (
                "",
                {
                    11 + 8 + 32 * 0 + 32 * 7,
                    11 + 8 + 32 * 1 + 32 * 7,
                    11 + 8 + 32 * 2 + 32 * 7,
                },
            ),
        ],
    )

    d = DelimitedType(a, 472)
    validate_iterator(
        d,
        [
            ("a", {32 + 0}),
            ("b", {32 + 10}),
            ("c", {32 + 11}),
            (
                "d",
                {
                    32 + 11 + 8 + 32 * 0,
                    32 + 11 + 8 + 32 * 1,
                    32 + 11 + 8 + 32 * 2,
                },
            ),
            (
                "",
                {
                    32 + 11 + 8 + 32 * 0 + 32 * 7,
                    32 + 11 + 8 + 32 * 1 + 32 * 7,
                    32 + 11 + 8 + 32 * 2 + 32 * 7,
                },
            ),
        ],
    )
    print("d.bit_length_set", d.bit_length_set)
    assert d.bit_length_set == BitLengthSet(
        {32 + x for x in range(((11 + 8 + 32 * 2 + 32 * 7) + 7) // 8 * 8 * 3 // 2 + 1)}
    ).pad_to_alignment(8)

    a_bls_options = [
        11 + 8 + 32 * 0 + 32 * 7 + 3,
        11 + 8 + 32 * 1 + 32 * 7 + 3,
        11 + 8 + 32 * 2 + 32 * 7 + 3,
    ]
    assert a.bit_length_set == BitLengthSet(a_bls_options).pad_to_alignment(8)

    # Testing "a" again, this time with non-zero base offset.
    # The first base offset element is one, but it is padded to byte, so it becomes 8.
    validate_iterator(
        a,
        [
            ("a", {8, 16}),
            ("b", {8 + 10, 16 + 10}),
            ("c", {8 + 11, 16 + 11}),
            (
                "d",
                {
                    8 + 11 + 8 + 32 * 0,
                    8 + 11 + 8 + 32 * 1,
                    8 + 11 + 8 + 32 * 2,
                    16 + 11 + 8 + 32 * 0,
                    16 + 11 + 8 + 32 * 1,
                    16 + 11 + 8 + 32 * 2,
                },
            ),
            (
                "",
                {
                    8 + 11 + 8 + 32 * 0 + 32 * 7,
                    8 + 11 + 8 + 32 * 1 + 32 * 7,
                    8 + 11 + 8 + 32 * 2 + 32 * 7,
                    16 + 11 + 8 + 32 * 0 + 32 * 7,
                    16 + 11 + 8 + 32 * 1 + 32 * 7,
                    16 + 11 + 8 + 32 * 2 + 32 * 7,
                },
            ),
        ],
        BitLengthSet({1, 16}),
    )  # 1 becomes 8 due to padding.

    # Wrap the above into a delimited type with a manually specified extent.
    d = DelimitedType(a, 400)
    validate_iterator(
        d,
        [
            ("a", {32 + 8, 32 + 16}),
            ("b", {32 + 8 + 10, 32 + 16 + 10}),
            ("c", {32 + 8 + 11, 32 + 16 + 11}),
            (
                "d",
                {
                    32 + 8 + 11 + 8 + 32 * 0,
                    32 + 8 + 11 + 8 + 32 * 1,
                    32 + 8 + 11 + 8 + 32 * 2,
                    32 + 16 + 11 + 8 + 32 * 0,
                    32 + 16 + 11 + 8 + 32 * 1,
                    32 + 16 + 11 + 8 + 32 * 2,
                },
            ),
            (
                "",
                {
                    32 + 8 + 11 + 8 + 32 * 0 + 32 * 7,
                    32 + 8 + 11 + 8 + 32 * 1 + 32 * 7,
                    32 + 8 + 11 + 8 + 32 * 2 + 32 * 7,
                    32 + 16 + 11 + 8 + 32 * 0 + 32 * 7,
                    32 + 16 + 11 + 8 + 32 * 1 + 32 * 7,
                    32 + 16 + 11 + 8 + 32 * 2 + 32 * 7,
                },
            ),
        ],
        BitLengthSet({1, 16}),
    )  # 1 becomes 8 due to padding.
    assert d.bit_length_set == BitLengthSet({(32 + x + 7) // 8 * 8 for x in range(400 + 1)})

    b = make_type(
        StructureType,
        [
            Field(a, "z"),
            Field(VariableLengthArrayType(a, 2), "y"),
            Field(UnsignedIntegerType(6, saturated), "x"),
        ],
    )

    a_bls_padded = [((x + 7) // 8) * 8 for x in a_bls_options]
    validate_iterator(
        b,
        [
            ("z", {0}),
            (
                "y",
                {
                    a_bls_padded[0],
                    a_bls_padded[1],
                    a_bls_padded[2],
                },
            ),
            (
                "x",
                {  # The lone "+8" is for the variable-length array's implicit length field
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
                },
            ),
        ],
    )

    # Ensuring the equivalency between bit length and aligned bit offset
    b_offset = BitLengthSet(0)
    for f in b.fields:
        b_offset = b_offset + f.data_type.bit_length_set
    print("b_offset:", b_offset)
    assert b_offset.pad_to_alignment(8) == b.bit_length_set
    assert not b_offset.is_aligned_at_byte()
    assert not b_offset.is_aligned_at(32)

    c = make_type(
        UnionType,
        [
            Field(a, "foo"),
            Field(b, "bar"),
        ],
    )

    validate_iterator(
        c,
        [
            ("foo", {8}),  # The offset is the same because it's a union
            ("bar", {8}),
        ],
    )

    validate_iterator(
        c,
        [
            ("foo", {8 + 8}),
            ("bar", {8 + 8}),
        ],
        BitLengthSet(8),
    )

    validate_iterator(
        c,
        [
            ("foo", {0 + 8, 8 + 8}),
            ("bar", {0 + 8, 8 + 8}),
        ],
        BitLengthSet({0, 4, 8}),
    )  # The option 4 is eliminated due to padding to byte, so we're left with {0, 8}.

    with raises(TypeError, match=".*request or response.*"):
        ServiceType(
            request=StructureType(
                name="ns.S.Request",
                version=Version(1, 0),
                attributes=[],
                deprecated=False,
                fixed_port_id=None,
                source_file_path="",
                has_parent_service=True,
            ),
            response=StructureType(
                name="ns.S.Response",
                version=Version(1, 0),
                attributes=[],
                deprecated=False,
                fixed_port_id=None,
                source_file_path="",
                has_parent_service=True,
            ),
            fixed_port_id=None,
        ).iterate_fields_with_offsets()

    with raises(ValueError):  # Request/response consistency error (internal failure)
        ServiceType(
            request=StructureType(
                name="ns.XX.Request",
                version=Version(2, 0),
                attributes=[],
                deprecated=False,
                fixed_port_id=None,
                source_file_path="",
                has_parent_service=True,
            ),
            response=StructureType(
                name="ns.YY.Response",
                version=Version(3, 0),
                attributes=[],
                deprecated=True,
                fixed_port_id=None,
                source_file_path="",
                has_parent_service=False,
            ),
            fixed_port_id=None,
        )

    # Check the auto-padding logic.
    e = StructureType(
        name="e.E",
        version=Version(0, 1),
        attributes=[],
        deprecated=False,
        fixed_port_id=None,
        source_file_path="",
        has_parent_service=False,
    )
    validate_iterator(e, [])
    a = make_type(
        StructureType,
        [
            Field(UnsignedIntegerType(3, PrimitiveType.CastMode.TRUNCATED), "x"),
            Field(e, "y"),
            Field(UnsignedIntegerType(2, PrimitiveType.CastMode.TRUNCATED), "z"),
        ],
    )
    assert a.bit_length_set == {16}
    validate_iterator(
        a,
        [
            ("x", {0}),
            ("y", {8}),  # Padded out!
            ("z", {8}),
        ],
    )
