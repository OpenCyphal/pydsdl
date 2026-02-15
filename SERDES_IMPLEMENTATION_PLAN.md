# Binary Serialization/Deserialization Plan for PyDSDL

## Objective
Add a small built-in runtime module to serialize and deserialize binary blobs using a pre-parsed `pydsdl.CompositeType` schema, without introducing external dependencies.

The implementation must conform to the Cyphal DSDL Specification available at `/home/pavel/cyphal/specification/specification/dsdl/`.

## Agreed Constraints and Decisions
- No new external dependencies.
- Runtime value mapping:
  - DSDL primitives -> Python scalar (`bool`, `int`, `float`)
  - DSDL arrays -> `list`
  - DSDL structures -> `dict[str, object]`
  - DSDL unions -> `dict[str, object]` with exactly one key (selected variant name)
- Serialization input acceptance policy is intentionally relaxed and coercive where unambiguous:
  - Arrays accept both `list` and `tuple`.
  - `utf8` arrays accept `str` and `bytes` input (`bytes` decoded as UTF-8).
  - `byte` arrays accept `bytes`, `bytearray`, and `str` input (`str` encoded as UTF-8).
  - Primitive inputs are coerced among `bool`/`int`/`float`.
  - Non-numeric primitive input values raise `ValueError`.
  - When coercing to integer targets from floating inputs, values are rounded (`round`) before DSDL cast-mode handling.
- Missing structure fields are recursively default-initialized:
  - Scalars default to zero-equivalent values.
  - Fixed-length arrays default to full-capacity elementwise defaults.
  - Variable-length arrays default to empty.
  - Unions default to the first variant (tag index 0), with that variant value recursively default-initialized.
  - Composite nesting applies the same rules recursively.
  - Unknown input fields in structure objects raise `ValueError`.
- Deserialization output policy is strict and canonical:
  - `utf8[]` -> `str`
  - `byte[]` -> `bytes`
  - Other arrays -> `list`
  - Structures/unions remain `dict`.
- Floats are represented with Python `float` for all DSDL float widths.
- Delimiter header strategy for nested delimited composites:
  - Use a temporary inner buffer.
  - Serialize the inner composite first.
  - Compute byte length.
  - Serialize delimiter header into outer buffer.
  - Append inner bytes to outer buffer.
  - This avoids bit-writer backpatching and remains spec-compliant.

## Public API
Implement in a new internal module `pydsdl/_serdes.py`:
- `serialize(schema: CompositeType, obj: dict[str, object], *, with_delimiter_header: bool = False) -> bytes`
- `deserialize(schema: CompositeType, data: bytes | bytearray | memoryview, *, with_delimiter_header: bool = False) -> dict[str, object]`

Export both at top level through `pydsdl/__init__.py`.

## Serialization/Deserialization Semantics to Implement
- Bit order: least-significant-bit first within byte; multi-byte values little-endian.
- Alignment/padding: emit zero padding on serialization; ignore padding bits on deserialization.
- Implicit truncation on decode: extra trailing bits are ignored.
- Implicit zero extension on decode: out-of-bounds reads yield zeros.
- Variable-length arrays:
  - Read/write implicit length field.
  - Reject serialized lengths above capacity.
- Tagged unions:
  - Read/write implicit tag field.
  - Reject tag values outside valid variant index range.
- Delimited composites:
  - Nested delimited composites include delimiter header.
  - Top-level delimited composites exclude delimiter header by default.
  - Optional `with_delimiter_header=True` allows explicit top-level container encoding/decoding when needed.
  - Delimiter header width is taken from `DelimitedType.delimiter_header_type.bit_length` (not hardcoded).
  - Leftover payload/trailing data is not an error (implicit truncation rule).
- Service types are not directly serializable/deserializable and should raise a clear error.

## Detailed Implementation Steps

### Step 1: Create Module Skeleton and Error Types
1. Add `pydsdl/_serdes.py`.
2. Define explicit runtime error types under public base `SerDesError(Exception)` for at least:
   - `ArrayLengthError` (serialize and deserialize)
   - `UnionFieldError` (unknown/malformed union field during serialization)
   - `UnionTagError` (out-of-range tag during deserialization)
   - `DelimiterHeaderError` (invalid delimiter header cases)
3. Use standard Python errors where appropriate instead of custom wrappers:
   - `ValueError` for non-numeric/invalid coercions and malformed relaxed input forms.
   - Built-in Unicode errors for UTF-8 codec failures.
   - Propagate built-in numeric conversion/runtime errors as-is where they naturally arise (Pythonic behavior).
4. Keep error diagnostics minimal and concise (no mandatory deep field-path/bit-offset reporting).
5. Define the two public functions and private recursive helpers.
6. Add type aliases for runtime values to keep signatures readable.

Deliverable:
- Importable module with API stubs and basic argument validation.

### Step 2: Build Bit-Level Infrastructure
1. Implement `_BitWriter`:
   - Internal `bytearray` buffer.
   - Current bit offset.
   - `write_bits(value: int, bit_length: int)` with LSB-first ordering.
   - `align_to(bit_alignment: int)` writing zero pad bits.
   - `finish() -> bytes`.
2. Implement `_BitReader`:
   - View over input bytes with bit position and optional bit limit.
   - `read_bits(bit_length: int) -> int` returning zero for out-of-bounds region.
   - `align_to(bit_alignment: int)` by skipping bits.
   - `remaining_bits` and bounded-subreader creation for delimited payloads.

Deliverable:
- Unit tests proving correct cross-byte behavior and alignment behavior.

### Step 3: Primitive Codec Layer
1. Implement primitive serialization/deserialization:
   - `bool`: one bit.
   - unsigned/signed integers: arbitrary widths up to 64.
   - floats: `float16/32/64` via `struct` (`<e`, `<f`, `<d`), including special values.
   - `void`: write zeros, read-and-discard.
2. Implement cast-mode handling for serialization inputs:
   - saturated/truncated behavior per schema primitive cast mode.
3. Validate Python input types and ranges before writing.
4. Implement permissive primitive coercion for serialization where unambiguous:
   - Accept numeric inputs (`bool`, `int`, `float`) only.
   - bool target: numeric coercion only; non-finite float inputs are explicitly rejected.
   - int target: accept `bool`, `int`, finite `float`; apply `round()` first, then DSDL cast-mode behavior.
   - float target: accept `bool`, `int`, `float`.
   - non-numeric inputs raise `ValueError`.

Deliverable:
- Primitive round-trip tests and cast-mode edge tests.

### Step 4: Array Codec Layer
1. Fixed-length arrays:
   - Accept input sequence as `list` or `tuple`.
   - Validate exact input length.
   - Serialize each element recursively.
   - Deserialize exact element count.
2. Variable-length arrays:
   - Serialize length field first.
   - Validate `0 <= n <= capacity`.
   - Serialize `n` elements.
   - Deserialize length and validate against capacity.
3. Special-cases for textual/byte arrays:
   - `UTF8Type` arrays:
     - serialization accepts `str` directly, or `bytes`/`bytearray` decoded with UTF-8.
     - deserialization returns `str` decoded with UTF-8.
   - `ByteType` arrays:
     - serialization accepts `bytes`/`bytearray` directly, or `str` encoded with UTF-8.
     - deserialization returns immutable `bytes`.
   - Favor implementation simplicity over extra coercion permutations.

Deliverable:
- Tests for empty/max lengths, capacity violations, nested element types.

### Step 5: Composite Codec Layer (Structure + Union)
1. Structures:
   - Iterate fields in declaration order.
   - Apply field alignment before each field.
   - Unknown input fields raise `ValueError`.
   - Serialize/deserialize each field recursively.
   - For padding fields (`void`), treat as normal field codec behavior.
2. Unions:
   - Expect input dict with exactly one key.
   - Empty/multi-key/non-dict union inputs raise `ValueError`.
   - Resolve selected variant index by field order.
   - Write implicit union tag, then selected value.
   - On decode, read tag and decode exactly one variant.

Deliverable:
- Tests for alignment-heavy layouts, malformed union objects, invalid tag values.

### Step 6: Delimited Composite Handling (Temporary Buffer Strategy)
1. For nested `DelimitedType` serialization:
   - Serialize `inner_type` into a temporary `bytes` payload (as sealed layout).
   - Ensure payload length is byte-aligned and within declared extent.
   - Write delimiter header as payload byte length using the schema-provided delimiter header type width.
   - Append payload bytes to outer writer.
2. For nested `DelimitedType` deserialization:
   - Read delimiter header.
   - Validate header length does not exceed outer remaining bytes.
   - Create bounded subreader for payload bytes and decode `inner_type`.
   - Skip any remaining payload bits in bounded subreader (implicit truncation behavior inside bounded container).
   - Raise a dedicated delimiter-related error for malformed header scenarios.
3. For top-level wrappers:
   - Default behavior: do not emit/expect delimiter for top-level delimited schema.
   - Honor `with_delimiter_header=True` by wrapping top-level behavior in same container logic.
   - Do not require exact payload consumption beyond the delimited payload; trailing data is acceptable per implicit truncation.

Deliverable:
- Nested delimited round-trip tests and invalid-header tests.

### Step 7: Top-Level Glue and API Export
1. Implement top-level `serialize()`:
   - Reject `ServiceType`.
   - If `with_delimiter_header=True` is supplied for a non-delimited top-level schema, raise `ValueError`.
   - Select top-level delimited behavior based on flag.
   - Return immutable `bytes`.
2. Implement top-level `deserialize()`:
   - Reject `ServiceType`.
   - If `with_delimiter_header=True` is supplied for a non-delimited top-level schema, raise `ValueError`.
   - Accept `bytes | bytearray | memoryview`.
   - Return decoded dict.
3. Export functions and public custom error types from `pydsdl/__init__.py`.

Deliverable:
- Public API available as `pydsdl.serialize` and `pydsdl.deserialize`.

### Step 8: Tests in Project Style
Add `_unittest_...` tests in `pydsdl/_serdes.py` covering:
1. Bit packing/unpacking across byte boundaries.
2. Primitive edge cases, including float special values.
3. Arrays (fixed/variable), bounds checks.
4. Structures with non-trivial alignment.
5. Unions (valid/invalid tag and variant selection).
6. Delimited nested behavior with temporary-buffer strategy.
7. Top-level delimited encode/decode with and without header flag.
8. Implicit truncation and zero extension behavior.
9. Relaxed input acceptance/coercion behavior:
   - tuple/list acceptance for arrays
   - UTF-8 string/bytes cross-acceptance
   - byte array string/bytes cross-acceptance
   - scalar coercion among bool/int/float
   - float-to-int uses `round()`
   - non-numeric coercion raises `ValueError`
10. Error taxonomy assertions:
   - array length out of range in both directions
   - union unknown field and out-of-range tag
   - delimiter malformed header cases
   - `with_delimiter_header=True` on non-delimited schemas raises `ValueError`.
11. Default initialization behavior:
   - missing fields default recursively
   - fixed arrays default elementwise
   - unions default to first variant.
12. Structure validation behavior:
   - unknown fields raise `ValueError`.
13. Numeric coercion behavior:
   - non-finite float to bool/int is explicitly rejected
   - built-in conversion/runtime errors are propagated as-is.

## Validation and Quality Gates
1. Run module tests and existing suite to ensure no regressions.
2. Run static checks used by project (`mypy`, `pylint`) if practical in this environment.
3. Keep implementation internal and minimal: no changes to parser/type model semantics.

## Notes on Future Optimization
- If needed later, the nested-delimited temporary-buffer approach can be replaced with an in-place patching writer without changing public API.
- The first version should favor correctness and clarity over micro-optimization.
