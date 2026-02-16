.. _pydsdl:

PyDSDL usage
============

The entirety of the library API is exposed at the top level as ``pydsdl.*``.
There are no usable submodules.

You can find a practical usage example in the Nunavut code generation library that uses PyDSDL as the frontend.

.. contents:: Contents
   :local:


The main functions
++++++++++++++++++

.. autofunction:: pydsdl.read_namespace
.. autofunction:: pydsdl.read_files


Serialization
+++++++++++++

PyDSDL provides built-in serialization and deserialization functions for binary encoding/decoding
of DSDL types without code generation.

.. autofunction:: pydsdl.serialize
.. autofunction:: pydsdl.deserialize

Object Representation Convention
---------------------------------

Deserialized objects use Python primitives:

- **Composites (StructureType)**: ``dict[str, Any]`` with field names as keys
- **Unions (UnionType)**: ``dict`` with exactly one key (the active variant)
- **Arrays (Fixed/Variable)**: ``list``
- **UTF-8 arrays**: ``str``
- **Byte arrays**: ``bytes``
- **Primitives**: ``bool``, ``int``, ``float``
- **Void**: ``None`` (skipped in output)

Example::

    obj = {"flag": True, "values": [1, 2, 3], "text": "hello"}
    data = pydsdl.serialize(schema, obj)
    reconstructed = pydsdl.deserialize(schema, data)
    assert obj == reconstructed

See ``demo/demo_serdes.py`` for a complete working example.

.. autoexception:: pydsdl.SerDesError
   :show-inheritance:


Type model
++++++++++

.. computron-injection::
    :filename: ../descendant_diagram.py
    :argv: Any

.. computron-injection::
    :filename: ../descendant_autodoc.py
    :argv: Any


Exceptions
++++++++++

.. computron-injection::
    :filename: ../descendant_diagram.py
    :argv: Error

.. autoexception:: pydsdl.Error
   :undoc-members:
   :no-inherited-members:
   :show-inheritance:
   :special-members:

.. note::
   ``FrontendError`` is retained as a backward-compatibility alias for ``Error``.

.. autoexception:: pydsdl.InvalidDefinitionError
   :undoc-members:
   :no-inherited-members:
   :show-inheritance:
   :special-members:

.. autoexception:: pydsdl.InternalError
   :undoc-members:
   :no-inherited-members:
   :show-inheritance:
   :special-members:


Ancillary members
+++++++++++++++++

.. autoclass:: pydsdl.BitLengthSet
   :undoc-members:
   :no-inherited-members:
   :show-inheritance:
   :special-members:
