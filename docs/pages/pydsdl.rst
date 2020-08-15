.. _pydsdl:

PyDSDL usage
============

The entirety of the library API is exposed at the top level ``pydsdl.*``.

.. contents:: Contents
   :local:


The main function
+++++++++++++++++

.. autofunction:: pydsdl.read_namespace


Type model
++++++++++

Both serializable types and expression types derive from the common ancestor :class:`pydsdl.Any`.
Serializable types have the suffix ``Type`` because their instances represent not DSDL values but DSDL types.

.. computron-injection::
    :filename: ../descendant_diagram.py
    :argv: Any

.. computron-injection::
    :filename: ../descendant_autodoc.py
    :argv: Any


Error model
+++++++++++

.. computron-injection::
    :filename: ../descendant_diagram.py
    :argv: FrontendError

.. autoexception:: pydsdl.FrontendError
   :undoc-members:
   :no-inherited-members:
   :show-inheritance:
   :special-members:

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
