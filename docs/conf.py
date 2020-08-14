#
# Copyright (C) 2020  UAVCAN Development Team  <uavcan.org>
# This software is distributed under the terms of the MIT License.
#

import sys
import pathlib
import datetime


GITHUB_USER_REPO = 'UAVCAN', 'pydsdl'

DESCRIPTION = 'A UAVCAN DSDL compiler front-end in Python'

DOC_ROOT = pathlib.Path(__file__).absolute().parent
REPOSITORY_ROOT = DOC_ROOT.parent

sys.path.insert(0, str(REPOSITORY_ROOT))
import pydsdl
assert 'site-packages' not in pydsdl.__file__, 'Wrong import source'

PACKAGE_ROOT = pathlib.Path(pydsdl.__file__).absolute().parent

EXTERNAL_LINKS = {
    'UAVCAN homepage': 'https://uavcan.org/',
    'Support forum':   'https://forum.uavcan.org/',
}

project = 'PyDSDL'
# noinspection PyShadowingBuiltins
copyright = str(datetime.datetime.now().year) + ', UAVCAN Development Team'
author = 'UAVCAN Development Team'

version = '.'.join(map(str, pydsdl.__version_info__))
release = pydsdl.__version__  # The full version, including alpha/beta/rc tags

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.doctest',
    'sphinx.ext.coverage',
    'sphinx.ext.todo',
    'sphinx.ext.intersphinx',
    'sphinx.ext.inheritance_diagram',
    'sphinx.ext.graphviz',
    'sphinx_computron',
    'ref_fixer_hack',
]
sys.path.append(str(DOC_ROOT))  # This is for the hack to be importable

templates_path = []

exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

source_suffix = ['.rst']

master_doc = 'index'

autoclass_content = 'class'
autodoc_member_order = 'bysource'
autodoc_inherit_docstrings = False
autodoc_default_options = {
    'members':          True,
    'undoc-members':    True,
    'special-members':  True,
    'imported-members': True,
    'show-inheritance': True,
    'member-order':     'bysource',
    'exclude-members':
        '__weakref__, __module__, __dict__, __dataclass_fields__, __dataclass_params__, __annotations__, '
        '__abstractmethods__, __orig_bases__, __parameters__, __post_init__, __getnewargs__',
}

todo_include_todos = True

graphviz_output_format = 'svg'

inheritance_graph_attrs = {
    'rankdir':  'LR',
    'bgcolor':  '"transparent"',
}
inheritance_node_attrs = {
    'color':     '"#000000"',
    'fontcolor': '"#000000"',
}
inheritance_edge_attrs = {
    'color': inheritance_node_attrs['color'],
}

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
}

pygments_style = 'friendly'

html_favicon = '_static/favicon.ico'
html_theme = 'sphinx_rtd_theme'
html_theme_options = {
    'display_version':            True,
    'prev_next_buttons_location': 'bottom',
    'style_external_links':       True,
    'navigation_depth':           -1,
}
html_context = {
}
html_static_path = ['_static']
html_css_files = [
    'custom.css',
]
