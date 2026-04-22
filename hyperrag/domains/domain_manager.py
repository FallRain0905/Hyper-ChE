# -*- coding: utf-8 -*-
"""
领域配置管理器
Domain Configuration Manager

负责加载和管理不同领域的配置，包括实体类型、关系类型和提示词模板。
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any


class DomainManager:
    """领域配置管理器"""

    def __init__(self):
        # 获取domains目录的路径
        current_dir = Path(__file__).parent
        self.domains_dir = current_dir
        self.current_domain = 'default'
        self.domain_configs: Dict[str, Dict] = {}

    def load_domain_config(self, domain_name: str) -> Dict:
        """
        加载领域配置

        Args:
            domain_name: 领域名称

        Returns:
            领域配置字典
        """
        if domain_name in self.domain_configs:
            return self.domain_configs[domain_name]

        config_path = self.domains_dir / domain_name / 'config.json'

        if not config_path.exists():
            raise FileNotFoundError(f"Domain config not found: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        self.domain_configs[domain_name] = config
        return config

    def get_entity_types(self, domain: str = 'default') -> List[str]:
        """
        获取实体类型列表

        Args:
            domain: 领域名称

        Returns:
            实体类型名称列表
        """
        config = self.load_domain_config(domain)

        # 处理两种配置格式
        if 'entity_types' in config:
            entity_types_config = config['entity_types']
            # 如果是字典列表格式，提取name字段
            if isinstance(entity_types_config, list) and len(entity_types_config) > 0:
                if isinstance(entity_types_config[0], dict):
                    return [t['name'] for t in entity_types_config]
                else:
                    return entity_types_config
            return entity_types_config

        return []

    def get_entity_types_config(self, domain: str = 'default') -> List[Dict]:
        """
        获取实体类型的详细配置

        Args:
            domain: 领域名称

        Returns:
            实体类型配置列表，每个配置包含name, description, examples等
        """
        config = self.load_domain_config(domain)

        if 'entity_types' in config:
            entity_types_config = config['entity_types']
            # 如果是字符串列表，转换为字典格式
            if isinstance(entity_types_config, list) and len(entity_types_config) > 0:
                if isinstance(entity_types_config[0], str):
                    return [{'name': t, 'description': '', 'examples': []} for t in entity_types_config]
                else:
                    return entity_types_config

        return []

    def get_relation_types(self, domain: str = 'default') -> List[str]:
        """
        获取关系类型列表

        Args:
            domain: 领域名称

        Returns:
            关系类型名称列表
        """
        config = self.load_domain_config(domain)

        if 'relation_types' in config:
            relation_types_config = config['relation_types']
            # 如果是字典列表格式，提取name字段
            if isinstance(relation_types_config, list) and len(relation_types_config) > 0:
                if isinstance(relation_types_config[0], dict):
                    return [t['name'] for t in relation_types_config]
                else:
                    return relation_types_config
            return relation_types_config

        return ['generic']  # 默认关系类型

    def get_relation_types_config(self, domain: str = 'default') -> List[Dict]:
        """
        获取关系类型的详细配置

        Args:
            domain: 领域名称

        Returns:
            关系类型配置列表
        """
        config = self.load_domain_config(domain)

        if 'relation_types' in config:
            relation_types_config = config['relation_types']
            # 如果是字符串列表，转换为字典格式
            if isinstance(relation_types_config, list) and len(relation_types_config) > 0:
                if isinstance(relation_types_config[0], str):
                    return [{'name': t, 'description': '', 'examples': []} for t in relation_types_config]
                else:
                    return relation_types_config

        return []

    def get_prompt_template(self, prompt_name: str, domain: str = 'default') -> str:
        """
        获取提示词模板

        Args:
            prompt_name: 提示词名称 (如: entity_extraction, low_order_extraction, etc.)
            domain: 领域名称

        Returns:
            提示词模板字符串
        """
        template_path = self.domains_dir / domain / f'{prompt_name}.txt'

        if not template_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {template_path}")

        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()

    def get_domain_context(self, domain: str = 'default') -> str:
        """
        获取领域上下文

        Args:
            domain: 领域名称

        Returns:
            领域上下文字符串
        """
        config = self.load_domain_config(domain)
        return config.get('domain_context', '')

    def get_output_format(self, domain: str = 'default') -> str:
        """
        获取输出格式

        Args:
            domain: 领域名称

        Returns:
            输出格式 (json 或 delimiter_based)
        """
        config = self.load_domain_config(domain)
        return config.get('output_format', 'delimiter_based')

    def set_domain(self, domain_name: str):
        """
        设置当前领域

        Args:
            domain_name: 领域名称
        """
        try:
            self.load_domain_config(domain_name)
            self.current_domain = domain_name
        except FileNotFoundError as e:
            raise ValueError(f"Failed to set domain '{domain_name}': {e}")

    def get_current_domain(self) -> str:
        """
        获取当前领域

        Returns:
            当前领域名称
        """
        return self.current_domain

    def get_available_domains(self) -> List[str]:
        """
        获取所有可用的领域

        Returns:
            可用领域名称列表
        """
        domains = []

        for item in self.domains_dir.iterdir():
            if item.is_dir() and (item / 'config.json').exists():
                domains.append(item.name)

        return sorted(domains)

    def get_entity_fields_config(self, domain: str = 'default') -> List[Dict]:
        """
        获取实体字段配置

        Args:
            domain: 领域名称

        Returns:
            实体字段配置列表
        """
        config = self.load_domain_config(domain)
        return config.get('entity_fields', [])

    def get_relation_fields_config(self, domain: str = 'default') -> List[Dict]:
        """
        获取关系字段配置

        Args:
            domain: 领域名称

        Returns:
            关系字段配置列表
        """
        config = self.load_domain_config(domain)
        return config.get('relation_fields', [])

    def get_critical_rules(self, domain: str = 'default') -> List[str]:
        """
        获取关键规则

        Args:
            domain: 领域名称

        Returns:
            关键规则列表
        """
        config = self.load_domain_config(domain)
        return config.get('critical_rules', [])

    def safe_get_prompt_template(self, prompt_name: str, domain: str = 'default') -> Optional[str]:
        """
        安全获取提示词模板，支持回退到默认领域

        Args:
            prompt_name: 提示词名称
            domain: 领域名称

        Returns:
            提示词模板字符串，如果找不到则返回None
        """
        try:
            return self.get_prompt_template(prompt_name, domain)
        except FileNotFoundError:
            if domain != 'default':
                # 尝试从默认领域获取
                try:
                    return self.get_prompt_template(prompt_name, 'default')
                except FileNotFoundError:
                    return None
            return None


# 全局单例实例
domain_manager = DomainManager()