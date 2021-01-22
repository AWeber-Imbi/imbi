"""
Imbi Service Management System
==============================

Imbi is Old High German for "Swarm of Bees"

"""
import pkg_resources
import warnings

version = pkg_resources.get_distribution('imbi').version
warnings.simplefilter('ignore', UserWarning)
