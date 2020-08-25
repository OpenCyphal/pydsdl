.. _pydsdl:

PyDSDL usage
============

The entirety of the library API is exposed at the top level as ``pydsdl.*``.
There are no usable submodules.

You can find a practical usage example in the Nunavut code generation library that uses PyDSDL as the frontend.

.. contents:: Contents
   :local:


The main function
+++++++++++++++++

.. autofunction:: pydsdl.read_namespace


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
