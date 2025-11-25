from setuptools import setup, find_packages

setup(
    name="unlinkmkv",
    version="2.0.0",
    description="Automate the tedious process of unlinking segmented MKV files",
    author="Garret C. Noling (original Perl), Python port",
    license="MIT",
    py_modules=["unlinkmkv"],
    install_requires=[
        "lxml>=4.9.0",
    ],
    entry_points={
        "console_scripts": [
            "unlinkmkv=unlinkmkv:main",
        ],
    },
    python_requires=">=3.8",
)
