"""
This script is used for generating inheritance diagrams in the docs.
It accepts one argument: the name of the class, and prints the ReST markup into stdout that produces the diagram.
The script is intended to be invoked from the ReST documents using https://github.com/pavel-kirienko/sphinx-computron.
"""

import sys
import pydsdl


def children(ty):
    for t in ty.__subclasses__():
        yield t
        yield from children(t)


T = getattr(pydsdl, sys.argv[1])
print('.. inheritance-diagram::', ' '.join('.'.join([t.__module__, t.__name__]) for t in children(T)))
print('   :parts: 1')
print('   :top-classes:', '.'.join([T.__module__, T.__name__]))
