"""
Imbi
====

Imbi is an operational management platform for medium to large environments.

"""
import warnings

import pkg_resources

version = pkg_resources.get_distribution('imbi').version
warnings.simplefilter('ignore', UserWarning)
