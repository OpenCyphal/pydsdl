.. _usage:

Usage
=====

The entirety of the library API is exposed at the top level ``pydsdl.*``.


The main function ``read_namespace``
++++++++++++++++++++++++++++++++++++

This function is the main entry point of the library.

.. autofunction:: pydsdl.read_namespace


Type model
++++++++++

Both serializable types and expression types derive from the common ancestor :class:`pydsdl.Any`.

.. computron-injection::
    :filename: ../descendant_diagram.py
    :argv: Any


Serializable
^^^^^^^^^^^^


Expression
^^^^^^^^^^


Error model
+++++++++++

.. computron-injection::
    :filename: ../descendant_diagram.py
    :argv: FrontendError
