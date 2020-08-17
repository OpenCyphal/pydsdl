"""
This script is used for generating documentation for the specified class and all its descendants.
It accepts one argument: the name of the class, and prints the ReST documentation markup.
The script is intended to be invoked from the ReST documents using https://github.com/pavel-kirienko/sphinx-computron.
"""

import sys
import itertools
import pydsdl


def children(ty):
    for t in ty.__subclasses__():
        yield t
        yield from children(t)


T = getattr(pydsdl, sys.argv[1])
for t in itertools.chain([T], children(pydsdl.Any)):
    print('.. autoclass::', '.'.join([t.__module__, t.__name__]))
    print('   :members:')
    print('   :undoc-members:')
    print('   :special-members:')
    print('   :no-inherited-members:')
    print('   :show-inheritance:')
    print()
