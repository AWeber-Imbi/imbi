"""
Imbi Service Management System
==============================

Imbi is Old High German for "Swarm of Bees"

"""
import warnings

import pkg_resources

version = pkg_resources.get_distribution('imbi').version
warnings.simplefilter('ignore', UserWarning)
