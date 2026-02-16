#!/usr/bin/env python3
"""
Self-contained demo of PyDSDL serialization.
"""

import pydsdl
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DSDL_FILE = SCRIPT_DIR / "DemoMessage.1.0.dsdl"


def main() -> None:
    print("Loading DSDL type from:", DSDL_FILE.name)
    types, _ = pydsdl.read_files(
        dsdl_files=DSDL_FILE,
        root_namespace_directories_or_names=SCRIPT_DIR,
        lookup_directories=[],
    )
    schema = types[0]
    print(f"✓ Loaded type: {schema.full_name} v{schema.version.major}.{schema.version.minor}")
    print(f"  Fields: {[f.name for f in schema.fields_except_padding]}")

    print("Creating example object:")
    obj = {
        "flag": True,
        "counter": 42,
        "temperature": 23.5,
        "numeric_data": [1.0, 2.0, 3, 4],
        "text_data": "Hello, SerDes!",
        "binary_data": b"\x00\x01\x02\x03",
    }
    for key, value in obj.items():
        value_repr = repr(value)
        if len(value_repr) > 50:
            value_repr = value_repr[:47] + "..."
        print(f"    {key:15} = {value_repr} ({type(value).__name__})")

    print("Serializing object to bytes")
    serialized_data = pydsdl.serialize(schema, obj)
    print(f"✓ Serialized to {len(serialized_data)} bytes:")
    print(f"  {serialized_data.hex()}")

    print("Deserializing bytes back to object")
    deserialized = pydsdl.deserialize(schema, serialized_data)
    print("✓ Deserialized successfully:")
    for key, value in deserialized.items():
        value_repr = repr(value)
        if len(value_repr) > 50:
            value_repr = value_repr[:47] + "..."
        print(f"    {key:15} = {value_repr} ({type(value).__name__})")

    print("Verifying roundtrip equality")
    assert obj == deserialized, "Roundtrip failed! Objects don't match."
    print("✓ Roundtrip verification passed: Original == Deserialized")


if __name__ == "__main__":
    main()
