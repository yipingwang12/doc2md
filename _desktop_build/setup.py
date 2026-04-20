"""py2app build for doc2md Reader — run from this directory, not the repo root.

Isolated here so setuptools does not read the repo's pyproject.toml and inject
install_requires, which py2app 0.28+ rejects.

Usage:
    cd _desktop_build
    ../.venv/bin/python setup.py py2app --alias
    # -> ../dist/doc2md Reader.app
"""

from pathlib import Path
from setuptools import setup

_REPO = Path(__file__).resolve().parent.parent

APP = [str(_REPO / 'src' / 'doc2md' / 'desktop.py')]
OPTIONS = {
    'argv_emulation': False,
    'dist_dir': str(_REPO / 'dist'),
    'plist': {
        'CFBundleName': 'doc2md Reader',
        'CFBundleDisplayName': 'doc2md Reader',
        'CFBundleIdentifier': 'com.yipingwang.doc2md-reader',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
    },
}

setup(
    name='doc2md-reader',
    app=APP,
    options={'py2app': OPTIONS},
)
