"""
Imbi - DevOps Service Management Platform

A modern FastAPI-based platform for managing services, projects, and operations
in a DevOps environment.
"""

__version__ = "1.0.0"
__author__ = "Gavin M. Roy"

from imbi.api.app import create_app

__all__ = ["create_app", "__version__"]
