"""
Patch de compatibilite Python 3.8.

Le parametre 'usedforsecurity' pour hashlib.md5() a ete ajoute en Python 3.9.
Ce patch permet a reportlab/xhtml2pdf de fonctionner sur Python 3.8.
"""

from __future__ import annotations

import sys
import hashlib

def patch_hashlib_for_python38():
    """
    Patche hashlib pour supporter le parametre usedforsecurity sur Python 3.8.

    reportlab utilise md5(usedforsecurity=False) qui n'existe pas en Python 3.8.
    Ce patch cree un wrapper qui ignore ce parametre.
    """
    if sys.version_info >= (3, 9):
        # Pas besoin de patch sur Python 3.9+
        return

    # Sauvegarde les fonctions originales
    _original_md5 = hashlib.md5
    _original_sha1 = hashlib.sha1
    _original_sha256 = hashlib.sha256

    def patched_md5(*args, **kwargs):
        """md5 patche qui ignore usedforsecurity."""
        kwargs.pop('usedforsecurity', None)
        return _original_md5(*args, **kwargs)

    def patched_sha1(*args, **kwargs):
        """sha1 patche qui ignore usedforsecurity."""
        kwargs.pop('usedforsecurity', None)
        return _original_sha1(*args, **kwargs)

    def patched_sha256(*args, **kwargs):
        """sha256 patche qui ignore usedforsecurity."""
        kwargs.pop('usedforsecurity', None)
        return _original_sha256(*args, **kwargs)

    # Applique les patches
    hashlib.md5 = patched_md5
    hashlib.sha1 = patched_sha1
    hashlib.sha256 = patched_sha256


# Applique le patch au chargement du module
patch_hashlib_for_python38()
