# -*- coding: utf-8 -*-
"""
Hyper-RAG Domain Configuration System

支持多领域的提示词配置，实现领域特定的实体类型、关系类型和提示词模板。
"""

from .domain_manager import DomainManager, domain_manager
from .validator import DomainValidator

__all__ = [
    'DomainManager',
    'domain_manager',
    'DomainValidator',
]