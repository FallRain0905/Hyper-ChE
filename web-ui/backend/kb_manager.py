# -*- coding: utf-8 -*-
"""
知识库管理器 - 管理知识库的创建、查询、更新和删除
"""
import os
import re
import json
import asyncio
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List


class KnowledgeBaseManager:
    """知识库管理器"""

    def __init__(self, storage_dir: str = "knowledge_bases", metadata_file: str = "kb_metadata.json"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.storage_dir / metadata_file
        self.metadata_lock = asyncio.Lock()

    def _load_metadata(self) -> Dict:
        """加载知识库元数据"""
        if not self.metadata_file.exists():
            return {}
        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _save_metadata(self, metadata: Dict):
        """保存知识库元数据"""
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    def sanitize_name(self, name: str) -> str:
        """将名称清理为合法的数据库名"""
        clean_name = re.sub(r'[^\w一-鿿\-]', '_', name)
        if len(clean_name) < 1:
            clean_name = "default"
        return clean_name

    async def create_kb(self, name: str, description: str = "",
                        rag_system: str = "hyperrag", domain: str = "default",
                        chunk_size: int = 1000, chunk_overlap: int = 200) -> Dict:
        """创建知识库"""
        import uuid
        database_name = self.sanitize_name(name)

        async with self.metadata_lock:
            metadata = self._load_metadata()

            # 检查重名
            if database_name in metadata:
                raise ValueError(f"知识库 '{name}' 已存在")

            kb_data = {
                "kb_id": str(uuid.uuid4()),
                "name": name,
                "description": description,
                "database_name": database_name,
                "rag_system": rag_system,
                "domain": domain,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            metadata[database_name] = kb_data
            self._save_metadata(metadata)

        return kb_data

    async def list_kbs(self) -> List[Dict]:
        """列出所有知识库"""
        metadata = self._load_metadata()
        return list(metadata.values())

    async def get_kb(self, kb_name: str) -> Optional[Dict]:
        """获取知识库详情"""
        metadata = self._load_metadata()
        database_name = self.sanitize_name(kb_name)
        return metadata.get(database_name)

    async def update_kb(self, kb_name: str, **updates) -> Optional[Dict]:
        """更新知识库设置"""
        database_name = self.sanitize_name(kb_name)

        async with self.metadata_lock:
            metadata = self._load_metadata()
            if database_name not in metadata:
                return None

            allowed_fields = {"description", "rag_system", "domain", "chunk_size", "chunk_overlap", "name"}
            for key, value in updates.items():
                if key in allowed_fields:
                    metadata[database_name][key] = value

            metadata[database_name]["updated_at"] = datetime.utcnow().isoformat()
            self._save_metadata(metadata)

        return metadata[database_name]

    async def delete_kb(self, kb_name: str) -> bool:
        """删除知识库（仅删除元数据，文件和数据库由调用方清理）"""
        database_name = self.sanitize_name(kb_name)

        async with self.metadata_lock:
            metadata = self._load_metadata()
            if database_name not in metadata:
                return False

            del metadata[database_name]
            self._save_metadata(metadata)

        return True

    async def get_kb_stats(self, kb_name: str, file_manager=None) -> Dict:
        """获取知识库统计信息"""
        kb = await self.get_kb(kb_name)
        if not kb:
            return {}

        stats = {
            "file_count": 0,
            "embedded_count": 0,
            "error_count": 0,
            "total_size": 0,
        }

        if file_manager:
            files = file_manager.get_all_files()
            kb_files = [f for f in files if f.get("kb_name") == kb["database_name"]]
            stats["file_count"] = len(kb_files)
            stats["embedded_count"] = sum(1 for f in kb_files if f.get("status") == "embedded")
            stats["error_count"] = sum(1 for f in kb_files if f.get("status") == "error")
            stats["total_size"] = sum(f.get("file_size", 0) for f in kb_files)

        return stats
