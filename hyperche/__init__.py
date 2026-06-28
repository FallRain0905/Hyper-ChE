"""HyperChE extension modules.

The package contains optional, side-car engineering modules built around the
original Hyper-RAG pipeline. These modules avoid mutating the core extraction
flow unless callers explicitly invoke them.
"""

__all__ = ["normalization"]
