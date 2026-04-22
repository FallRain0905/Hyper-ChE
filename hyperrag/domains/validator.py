# -*- coding: utf-8 -*-
"""
领域输出验证器
Domain Output Validator

验证LLM输出是否符合领域配置的要求。
"""

from typing import Dict, List, Any


class DomainValidator:
    """领域输出验证器"""

    @staticmethod
    def validate_entity(entity: Dict, domain_config: Dict) -> List[str]:
        """
        验证实体是否符合领域配置

        Args:
            entity: 实体字典
            domain_config: 领域配置

        Returns:
            错误列表，如果为空则表示验证通过
        """
        errors = []

        # 检查必需字段
        entity_fields = domain_config.get('entity_fields', [])
        for field in entity_fields:
            field_name = field['name']
            required = field.get('required', False)

            # 处理条件必需字段
            if required == 'conditional':
                condition = field.get('condition', '')
                if condition:
                    try:
                        # 简单的条件评估
                        should_be_required = eval(condition, {}, {'type': entity.get('type')})
                        if should_be_required:
                            if field_name not in entity or not entity[field_name]:
                                errors.append(f"Missing conditionally required field: {field_name}")
                    except Exception as e:
                        errors.append(f"Error evaluating condition for {field_name}: {e}")
                continue

            # 处理普通必需字段
            if required and field_name not in entity:
                errors.append(f"Missing required field: {field_name}")

        # 检查实体类型
        entity_type = entity.get('type')
        if entity_type:
            valid_types = DomainValidator._get_valid_entity_types(domain_config)
            if entity_type not in valid_types:
                errors.append(f"Invalid entity type: {entity_type}. Valid types: {valid_types}")

        # 检查数值字段
        numeric_fields = ['value', 'value_min', 'value_max']
        for field_name in numeric_fields:
            if field_name in entity and entity[field_name] is not None:
                if not isinstance(entity[field_name], (int, float)):
                    errors.append(f"Field {field_name} must be numeric, got {type(entity[field_name])}")

        # 检查子类型有效性
        if 'subtype' in entity and entity['subtype']:
            valid_subtypes = DomainValidator._get_valid_subtypes(entity_type, domain_config)
            if valid_subtypes and entity['subtype'] not in valid_subtypes:
                errors.append(f"Invalid subtype '{entity['subtype']}' for type '{entity_type}'. Valid subtypes: {valid_subtypes}")

        return errors

    @staticmethod
    def validate_relation(relation: Dict, domain_config: Dict) -> List[str]:
        """
        验证关系是否符合领域配置

        Args:
            relation: 关系字典
            domain_config: 领域配置

        Returns:
            错误列表，如果为空则表示验证通过
        """
        errors = []

        # 检查关系类型
        relation_type = relation.get('relation_type')
        if relation_type:
            valid_types = DomainValidator._get_valid_relation_types(domain_config)
            if relation_type not in valid_types:
                errors.append(f"Invalid relation type: {relation_type}. Valid types: {valid_types}")

        # 检查strength范围
        if 'strength' in relation:
            strength = relation['strength']
            if not isinstance(strength, int) or strength < 0 or strength > 10:
                errors.append("Strength must be integer between 0 and 10")

        # 检查必需字段
        relation_fields = domain_config.get('relation_fields', [])
        for field in relation_fields:
            field_name = field['name']
            required = field.get('required', False)

            if required and field_name not in relation:
                errors.append(f"Missing required field: {field_name}")

        return errors

    @staticmethod
    def validate_hyperedge(hyperedge: Dict, domain_config: Dict) -> List[str]:
        """
        验证超边是否符合领域配置

        Args:
            hyperedge: 超边字典
            domain_config: 领域配置

        Returns:
            错误列表，如果为空则表示验证通过
        """
        errors = []

        # 检查vertices字段
        if 'vertices' not in hyperedge:
            errors.append("Missing required field: vertices")
        elif not isinstance(hyperedge['vertices'], list) or len(hyperedge['vertices']) < 2:
            errors.append("Field 'vertices' must be a list with at least 2 elements")

        # 检查关系类型
        relation_type = hyperedge.get('relation_type')
        if relation_type:
            valid_types = DomainValidator._get_valid_relation_types(domain_config)
            if relation_type not in valid_types:
                errors.append(f"Invalid relation type: {relation_type}. Valid types: {valid_types}")

        # 检查strength范围
        if 'strength' in hyperedge:
            strength = hyperedge['strength']
            if not isinstance(strength, int) or strength < 0 or strength > 10:
                errors.append("Strength must be integer between 0 and 10")

        # 检查evidence_span长度
        if 'evidence_span' in hyperedge and hyperedge['evidence_span']:
            if len(hyperedge['evidence_span']) > 120:
                errors.append("Field 'evidence_span' should not exceed 120 characters")

        return errors

    @staticmethod
    def validate_json_output(output: str, output_type: str = 'entities') -> tuple[List[Dict], List[str]]:
        """
        验证JSON输出格式

        Args:
            output: LLM输出字符串
            output_type: 输出类型 (entities, relations, hyperedges)

        Returns:
            (解析后的数据列表, 错误列表)
        """
        import json
        import re

        errors = []
        data = []

        # 尝试解析JSON
        try:
            # 尝试直接解析
            data = json.loads(output)
        except json.JSONDecodeError:
            # 尝试提取JSON数组
            match = re.search(r'\[.*\]', output, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError as e:
                    errors.append(f"Failed to parse JSON: {e}")
                    return [], errors
            else:
                errors.append("No valid JSON array found in output")
                return [], errors

        # 确保是列表格式
        if not isinstance(data, list):
            if isinstance(data, dict):
                data = [data]
            else:
                errors.append(f"Output must be a list or dict, got {type(data)}")
                return [], errors

        return data, errors

    @staticmethod
    def _get_valid_entity_types(domain_config: Dict) -> List[str]:
        """获取有效的实体类型列表"""
        entity_types = domain_config.get('entity_types', [])

        if isinstance(entity_types, list) and len(entity_types) > 0:
            if isinstance(entity_types[0], dict):
                return [t['name'] for t in entity_types]
            else:
                return entity_types

        return []

    @staticmethod
    def _get_valid_relation_types(domain_config: Dict) -> List[str]:
        """获取有效的关系类型列表"""
        relation_types = domain_config.get('relation_types', [])

        if isinstance(relation_types, list) and len(relation_types) > 0:
            if isinstance(relation_types[0], dict):
                return [t['name'] for t in relation_types]
            else:
                return relation_types

        return ['generic']

    @staticmethod
    def _get_valid_subtypes(entity_type: str, domain_config: Dict) -> List[str]:
        """获取特定实体类型的有效子类型"""
        entity_types_config = DomainValidator._get_valid_entity_types_config(domain_config)

        for entity_type_config in entity_types_config:
            if entity_type_config.get('name') == entity_type:
                return entity_type_config.get('subtypes', [])

        return []

    @staticmethod
    def _get_valid_entity_types_config(domain_config: Dict) -> List[Dict]:
        """获取实体类型的详细配置"""
        entity_types = domain_config.get('entity_types', [])

        if isinstance(entity_types, list) and len(entity_types) > 0:
            if isinstance(entity_types[0], dict):
                return entity_types
            else:
                return [{'name': t, 'description': '', 'subtypes': []} for t in entity_types]

        return []

    @staticmethod
    def validate_batch(entities: List[Dict], domain_config: Dict) -> Dict[str, Any]:
        """
        批量验证实体

        Args:
            entities: 实体列表
            domain_config: 领域配置

        Returns:
            验证结果字典 {
                'valid': bool,
                'total': int,
                'valid_count': int,
                'invalid_count': int,
                'errors': List[Dict],
                'valid_entities': List[Dict],
                'invalid_entities': List[Dict]
            }
        """
        result = {
            'valid': True,
            'total': len(entities),
            'valid_count': 0,
            'invalid_count': 0,
            'errors': [],
            'valid_entities': [],
            'invalid_entities': []
        }

        for i, entity in enumerate(entities):
            errors = DomainValidator.validate_entity(entity, domain_config)

            if errors:
                result['valid'] = False
                result['invalid_count'] += 1
                result['invalid_entities'].append({
                    'index': i,
                    'entity': entity,
                    'errors': errors
                })
                result['errors'].extend([f"Entity {i}: {error}" for error in errors])
            else:
                result['valid_count'] += 1
                result['valid_entities'].append(entity)

        return result