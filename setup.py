from setuptools import setup
import sys, os

if sys.platform.startswith("win32"):
    scripts = []
    console = [os.path.join("bin", "gansa")]
else:
    scripts = [os.path.join("bin", "gansa")]
    console = []

setup(
    name = "gansa",
    version = "0.1.0",
    author = "Decky Coss",
    author_email = "coss@cosstropolis.com",
    description = "A tiny static site generator.",
    packages = ["gansa"],
    install_requires = [
        "psycopg2",
        "six",
        "jinja2",
        "Markdown",
        "PyYAML",
        "sqlalchemy",
        "mongoengine",
        "pyjade"
    ],
    scripts = scripts,
    console = console,
)
