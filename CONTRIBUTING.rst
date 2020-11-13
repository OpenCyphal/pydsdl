.. _dev:

Development guide
=================

This document is intended for library developers only.
If you just want to use the library, you don't need to read it.


Dependencies
++++++++++++

Despite the fact that the library itself is dependency-free,
some additional packages are needed for development and testing.
They are listed in ``/requirements.txt``.

External runtime dependencies are not allowed in this project --
if you can't bundle it with the library, you can't use it.


Coding conventions
++++++++++++++++++

Follow `PEP8 <https://www.python.org/dev/peps/pep-0008/>`_ with one exception:
the line length limit is 120 characters (not 79).

All functions and methods shall be type-annotated. This is enforced statically with MyPy.

Ensure compatibility with all versions of Python that have not yet reached the end-of-life.

Try not to import specific entities; instead, import only the package itself and then use verbose references,
as shown below.
If you really need to import a specific entity, consider prefixing it with an underscore to prevent
scope leakage, unless you really want it to be externally visible (usually you don't).
Exception applies to well-encapsulated submodules which are not part of the library API
(i.e., prefixed with an underscore).

.. code-block:: python

    from . import _serializable               # Good
    from ._serializable import CompositeType  # Pls no


Writing tests
+++++++++++++

100% branch coverage is required.

Write unit tests as functions without arguments prefixed with ``_unittest_``.
Test functions should be located as close as possible to the tested code,
preferably at the end of the same Python module.

Make assertions using the standard ``assert`` statement.
For extra functionality, import ``pytest`` in your test function locally.
**Never import PyTest outside of your test functions** because it will break the library
outside of test-enabled environments.

.. code-block:: python

    def _unittest_my_test() -> None:    # Type annotations required
        import pytest  # OK to import inside test functions only (rarely useful)
        assert get_the_answer() == 42

For more information refer to the PyTest documentation.


Generating the docs
+++++++++++++++++++

Use ``/docs/build.sh`` to generate the documentation locally.


Releasing
+++++++++

The script ``/release.sh`` is automatically invoked by the CI/CD pipeline for all commits pushed to master.
It can also be used by a developer locally to publish releases manually, should that be necessary,
although this is obviously discouraged.

The script uploads a new release to PyPI and pushes a new tag upstream.
It is therefore necessary to ensure that the library version is bumped whenever a new commit is merged into master;
otherwise, the automation will fail with an explicit tag conflict error instead of deploying the release.
