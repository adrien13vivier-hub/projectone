"""Permet `import risk_engine` / `import portfolio_analyzer` depuis tests/
sans installer le projet comme package -- on ajoute juste la racine du
depot au chemin d'import, une fois, avant que pytest ne collecte les tests.
"""
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)
