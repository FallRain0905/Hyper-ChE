# -*- coding: utf-8 -*-
"""
文件管理器 - 用于处理文件上传、存储和元数据管理
"""
import os
import re
import json
import asyncio
import aiofiles
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List


class FileManager:
    """文件管理器，处理文件的上传、存储和元数据管理"""

    def __init__(self, storage_dir: str = "uploads", metadata_file: str = "file_metadata.json"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.storage_dir / metadata_file
        self.metadata_lock = asyncio.Lock()

    def is_supported_file(self, filename: str, mime_type: str) -> bool:
        """检查文件类型是否支持"""
        supported_extensions = {'.txt', '.pdf', '.docx', '.doc', '.md'}
        ext = Path(filename).suffix.lower()
        return ext in supported_extensions

    def generate_file_id(self) -> str:
        """生成唯一的文件ID"""
        import uuid
        return str(uuid.uuid4())

    def get_file_hash(self, file_path: str) -> str:
        """计算文件的哈希值"""
        import hashlib
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def generate_database_name(self, filename: str) -> str:
        """使用完整文件名（去除扩展名）作为数据库名"""
        # 去除文件扩展名
        name_without_ext = Path(filename).stem
        # 只保留字母、数字、下划线、连字符和中文字符
        clean_name = re.sub(r'[^\w一-鿿\-]', '_', name_without_ext)
        # 如果清理后为空，使用默认名
        if len(clean_name) < 1:
            clean_name = "default"
        return clean_name

    async def save_uploaded_file(self, file_content: bytes, original_filename: str) -> Dict:
        """保存上传的文件"""
        try:
            # 根据文件扩展名推断MIME类型
            ext = Path(original_filename).suffix.lower()
            mime_type_map = {
                '.txt': 'text/plain',
                '.pdf': 'application/pdf',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.doc': 'application/msword',
                '.md': 'text/markdown'
            }
            mime_type = mime_type_map.get(ext, 'application/octet-stream')

            if not self.is_supported_file(original_filename, mime_type):
                raise ValueError(f"不支持的文件类型: {original_filename}")

            # 生成数据库名
            database_name = self.generate_database_name(original_filename)

            # 生成文件ID和存储路径
            file_id = self.generate_file_id()
            file_ext = Path(original_filename).suffix
            filename = f"{file_id}{file_ext}"
            file_path = self.storage_dir / filename

            # 异步保存文件
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(file_content)

            # 计算文件大小和哈希
            file_size = len(file_content)
            file_hash = self.get_file_hash(str(file_path))

            # 保存到元数据文件
            async with self.metadata_lock:
                metadata = self._load_metadata()

                file_record = {
                    "file_id": file_id,
                    "filename": filename,
                    "original_filename": original_filename,
                    "file_path": str(file_path),
                    "file_size": file_size,
                    "file_type": file_ext,
                    "mime_type": mime_type,
                    "database_name": database_name,
                    "upload_time": datetime.utcnow().isoformat(),
                    "status": "uploaded",
                    "processed_time": None,
                    "error_message": None,
                    "file_metadata": {"hash": file_hash}
                }

                metadata[file_id] = file_record
                self._save_metadata(metadata)

                return {
                    "file_id": file_id,
                    "filename": original_filename,
                    "file_path": str(file_path),
                    "file_size": file_size,
                    "file_type": file_ext,
                    "database_name": database_name,
                    "upload_time": file_record["upload_time"]
                }

        except Exception as e:
            raise Exception(f"文件保存失败: {str(e)}")

    def _load_metadata(self) -> Dict:
        """加载元数据"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_metadata(self, metadata: Dict):
        """保存元数据"""
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    def get_all_files(self) -> List[Dict]:
        """获取所有文件的列表"""
        return list(self._load_metadata().values())

    def get_file_info(self, file_id: str) -> Optional[Dict]:
        """获取指定文件的信息"""
        return self._load_metadata().get(file_id)

    def update_file_status(self, file_id: str, status: str, error_message: str = None):
        """更新文件状态"""
        metadata = self._load_metadata()
        if file_id in metadata:
            metadata[file_id]["status"] = status
            metadata[file_id]["processed_time"] = datetime.utcnow().isoformat()
            if error_message:
                metadata[file_id]["error_message"] = error_message
            self._save_metadata(metadata)

    async def read_file_content(self, file_path: str) -> str:
        """读取文件内容"""
        async with aiofiles.open(file_path, 'rb') as f:
            content = await f.read()

        # 处理不同文件类型
        ext = Path(file_path).suffix.lower()
        if ext == '.txt' or ext == '.md':
            return content.decode('utf-8')
        elif ext == '.pdf':
            # PDF解析逻辑
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            return text
        elif ext == '.docx':
            # DOCX解析逻辑
            from docx import Document
            doc = Document(file_path)
            return "\n".join([para.text for para in doc.paragraphs])
        else:
            return content.decode('utf-8', errors='ignore')


# 全局文件管理器实例
file_manager = FileManager()
