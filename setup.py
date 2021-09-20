#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from os import path
from setuptools import setup, find_packages

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(name='hwtAxiPerfTester',
      version='0.0',
      description='Tester of AXI3 and AXI4 slaves (latency, throughput, MOPS, ...) written in hwt',
      long_description=long_description,
      long_description_content_type="text/markdown",
      url='https://github.com/Nic30/hwtAxiPerfTester',
      author='Michal Orsak',
      author_email='Nic30original@gmail.com',
      classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",
        "Topic :: System :: Hardware",
        "Topic :: System :: Emulators",
        "Topic :: Utilities"
      ],
      install_requires=[
        'hwtLib>=2.9',
      ],
      license='MIT',
      packages=find_packages(),
      zip_safe=True,
)
