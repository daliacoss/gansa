from setuptools import setup
import sys, os

if sys.platform.startswith("win32"):
    scripts = []
    console = [os.path.join("bin", "froggit")]
else:
    scripts = [os.path.join("bin", "froggit")]
    console = []

setup(
    name = "froggit",
    version = "0.1.0",
    author = "Decky Coss",
    author_email = "coss@cosstropolis.com",
    description = "A tiny static site generator.",
    packages = ["froggit"],
    install_requires = ["jinja2", "Markdown", "PyYAML"],
    scripts = scripts,
    console = console,
)
