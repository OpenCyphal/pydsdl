.. _dev:

Development guide
=================

This document is intended for library developers only.
If you just want to use the library, you don't need to read it.

Development automation is managed by Nox; please see ``noxfile.py``.


Writing tests
+++++++++++++

Write unit tests as functions without arguments prefixed with ``_unittest_``.
Test functions should be located close to the tested code,
preferably at the end of the same Python module.

For extra functionality, import ``pytest`` in your test function locally.
**Never import PyTest outside of your test functions** because it will break the library
outside of test-enabled environments.

.. code-block:: python

    def _unittest_my_test() -> None:    # Type annotations required
        import pytest  # OK to import inside test functions only (rarely useful)
        assert get_the_answer() == 42


Supporting newer versions of Python
+++++++++++++++++++++++++++++++++++

Normally, this should be done a few months after a new version of CPython is released:

1. Update the CI/CD pipelines to enable the new Python version.
2. Update the CD configuration to make sure that the library is released using the newest version of Python.
3. Bump the version number using the ``.dev`` suffix to indicate that it is not release-ready until tested.

When the CI/CD pipelines pass, you are all set.


Releasing
+++++++++

A CI/CD pipeline automatically uploads a new release to PyPI and adds a new tag upstream for every push to ``master``.
It is therefore necessary to ensure that the library version is bumped whenever a new commit is merged into master;
otherwise, the automation will fail with an explicit tag conflict error instead of deploying the release.
