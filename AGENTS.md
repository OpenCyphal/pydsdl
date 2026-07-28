# Instructions for clankers

When reading source files, ingest them in their entirety instead of relying on search/grep tools.

Read `README.md` and `CONTRIBUTING.rst` first.

When implementing functional code changes, be sure to read the DSDL specification in <https://github.com/OpenCyphal/specification>.

## Project Structure & Module Organization

- Core library code lives in `pydsdl/`.
- Key internal subpackages are `pydsdl/_expression/`, `pydsdl/_serializable/`.
- Vendored dependencies are under `pydsdl/third_party/` (treat as external code; modify only when intentionally syncing).
- Tests are mostly co-located with implementation. Larger suites are in `pydsdl/_test*.py`, they are never imported.
- Documentation sources are in `docs/`.
- Test and release automation is in `noxfile.py` and `.github/`.

## Commit & Pull Request Guidelines

Provide detailed commit messages explaining the rationale behind the changes. Aim for a brief title with a following expanded description explaining what has been done and why was it necessary.
