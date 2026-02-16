#!/usr/bin/env python3
"""
Self-contained demo of pydsdl serialization and deserialization.

Demonstrates the complete workflow:
1. Load a custom DSDL type using read_files()
2. Create an object using the representation convention (dict, list, str, bytes, primitives)
3. Serialize the object to bytes
4. Deserialize the bytes back to an object
5. Verify roundtrip equality
"""

import pydsdl
from pathlib import Path


def main() -> None:
    SCRIPT_DIR = Path(__file__).parent
    DSDL_FILE = SCRIPT_DIR / "DemoMessage.1.0.dsdl"

    print("=" * 70)
    print("PyDSDL Serialization/Deserialization Demo")
    print("=" * 70)

    print("\n[Step 1] Loading DSDL type from:", DSDL_FILE.name)
    
    types, _ = pydsdl.read_files(
        dsdl_files=DSDL_FILE,
        root_namespace_directories_or_names=SCRIPT_DIR,
        lookup_directories=[]
    )
    
    schema = types[0]
    print(f"✓ Loaded type: {schema.full_name} v{schema.version.major}.{schema.version.minor}")
    print(f"  Fields: {[f.name for f in schema.fields_except_padding]}")

    print("\n[Step 2] Creating example object")
    print("  Representation convention: dict→struct, list→array, primitives as-is")
    obj = {
        "flag": True,
        "counter": 42,
        "temperature": 23.5,
        "numeric_data": [1.0, 2.0, 3.0, 4.0],
        "text_data": list("Hello, SerDes!".encode("utf-8")),
        "binary_data": [0x00, 0x01, 0x02, 0x03]
    }
    
    print("  Object structure:")
    for key, value in obj.items():
        value_repr = repr(value)
        if len(value_repr) > 50:
            value_repr = value_repr[:47] + "..."
        print(f"    {key:15} = {value_repr} ({type(value).__name__})")

    print("\n[Step 3] Serializing object to bytes")
    serialized_data = pydsdl.serialize(schema, obj)
    print(f"✓ Serialized to {len(serialized_data)} bytes")
    print(f"  Hex: {serialized_data.hex()}")

    print("\n[Step 4] Deserializing bytes back to object")
    deserialized = pydsdl.deserialize(schema, serialized_data)
    print("✓ Deserialized successfully")
    print("  Deserialized structure:")
    for key, value in deserialized.items():
        value_repr = repr(value)
        if len(value_repr) > 50:
            value_repr = value_repr[:47] + "..."
        print(f"    {key:15} = {value_repr} ({type(value).__name__})")

    print("\n[Step 5] Verifying roundtrip equality")
    assert obj == deserialized, "Roundtrip failed! Objects don't match."
    print("✓ Roundtrip verification passed: Original == Deserialized")

    print("\n" + "=" * 70)
    print("Demo completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
