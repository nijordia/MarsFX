"""
Setup script for MarsFX Data Generator
"""
from setuptools import find_packages, setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="marsfx-generator",
    version="1.0.0",
    author="MarsFX Team",
    description="Interplanetary FX tick data generator with economic events",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.11",
    install_requires=[
        "numpy>=1.26.4",
        "pandas>=2.1.4",
        "pyarrow>=14.0.2",
        "kafka-python>=2.0.2",
        "confluent-kafka>=2.3.0",
        "pyyaml>=6.0.1",
        "python-dotenv>=1.0.1",
        "python-dateutil>=2.8.2",
        "structlog>=24.1.0",
        "pydantic>=2.5.3",
        "pydantic-settings>=2.1.0",
        "click>=8.1.7",
        "rich>=13.7.0",
        "trino>=0.328.0",
        "sqlalchemy>=2.0.25",
        "psycopg2-binary>=2.9.9",
        "scipy>=1.11.4",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.4",
            "pytest-asyncio>=0.23.3",
            "pytest-mock>=3.12.0",
            "black>=24.1.0",
            "ruff>=0.1.14",
            "mypy>=1.8.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "marsfx-generator=main:cli",
        ],
    },
)
