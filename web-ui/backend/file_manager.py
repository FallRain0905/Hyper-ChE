import os
import uuid
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import aiofiles
import asyncio

class FileManager:
    def __init__(self, storage_dir: str = "uploads", metadata_file: str = "file_metadata.json"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        
        # 元数据文件路径
        self.metadata_file = Path(metadata_file)
        self.metadata_lock = asyncio.Lock()
        
        # 支持的文件类型
        self.supported_extensions = {'.txt', '.pdf', '.docx', '.md', '.doc'}
        self.supported_mime_types = {
            'text/plain', 'application/pdf', 
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/msword', 'text/markdown'
        }
        
        # 初始化元数据文件
        self._init_metadata_file()
    
    def _init_metadata_file(self):
        """初始化元数据文件"""
        if not self.metadata_file.exists():
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
    
    def _load_metadata(self) -> Dict:
        """加载元数据"""
        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def _save_metadata(self, metadata: Dict):
        """保存元数据"""
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    def generate_file_id(self) -> str:
        """生成唯一的文件ID"""
        return str(uuid.uuid4())
    
    def get_file_hash(self, file_path: str) -> str:
        """计算文件的MD5哈希值"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def is_supported_file(self, filename: str, mime_type: str = None) -> bool:
        """检查文件是否支持"""
        ext = Path(filename).suffix.lower()
        return ext in self.supported_extensions or (mime_type and mime_type in self.supported_mime_types)
    
    def generate_database_name(self, filename: str) -> str:
        """根据文件名前5个字符生成数据库名"""
        # 去除文件扩展名
        name_without_ext = Path(filename).stem
        # 只保留字母、数字和中文字符，移除特殊字符
        clean_name = re.sub(r'[^\w\u4e00-\u9fff]', '', name_without_ext)
        # 取前5个字符
        db_name = clean_name[:5]
        # 如果少于5个字符，用原文件名
        if len(db_name) < 1:
            db_name = "default"
        return db_name
    
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
                    "database_name": database_name,
                    "file_size": file_size,
                    "status": "uploaded",
                    "upload_time": file_record["upload_time"]
                }
                
        except Exception as e:
            # 如果保存失败，删除已创建的文件
            if 'file_path' in locals() and file_path.exists():
                file_path.unlink()
            raise e
    
    def get_all_files(self) -> List[Dict]:
        """获取所有文件列表"""
        metadata = self._load_metadata()
        files = []
        
        for file_id, file_record in metadata.items():
            files.append({
                "file_id": file_record["file_id"],
                "filename": file_record["original_filename"],
                "database_name": file_record["database_name"],
                "file_size": file_record["file_size"],
                "file_type": file_record["file_type"],
                "mime_type": file_record["mime_type"],
                "upload_time": file_record["upload_time"],
                "status": file_record["status"],
                "processed_time": file_record.get("processed_time"),
                "error_message": file_record.get("error_message")
            })
        
        # 按上传时间降序排序
        files.sort(key=lambda x: x["upload_time"], reverse=True)
        return files
    
    def get_file_by_id(self, file_id: str) -> Optional[Dict]:
        """根据ID获取文件信息"""
        metadata = self._load_metadata()
        file_record = metadata.get(file_id)
        
        if not file_record:
            return None
        
        return {
            "file_id": file_record["file_id"],
            "filename": file_record["original_filename"],
            "database_name": file_record["database_name"],
            "file_path": file_record["file_path"],
            "file_size": file_record["file_size"],
            "file_type": file_record["file_type"],
            "mime_type": file_record["mime_type"],
            "upload_time": file_record["upload_time"],
            "status": file_record["status"],
            "processed_time": file_record.get("processed_time"),
            "error_message": file_record.get("error_message")
        }
    
    def update_file_status(self, file_id: str, status: str, error_message: str = None):
        """更新文件状态"""
        metadata = self._load_metadata()
        
        if file_id in metadata:
            metadata[file_id]["status"] = status
            if error_message:
                metadata[file_id]["error_message"] = error_message
            if status == "embedded":
                metadata[file_id]["processed_time"] = datetime.utcnow().isoformat()
            
            self._save_metadata(metadata)
    
    def delete_file(self, file_id: str, clean_database: bool = False, rag_instance=None) -> bool:
        """
        删除文件

        Args:
            file_id: 文件ID
            clean_database: 是否清理数据库中的嵌入数据
            rag_instance: HyperRAG实例，用于清理数据库
        """
        metadata = self._load_metadata()

        if file_id not in metadata:
            return False

        file_record = metadata[file_id]

        # 删除文件
        file_path = Path(file_record["file_path"])
        if file_path.exists():
            file_path.unlink()

        # 如果需要清理数据库
        if clean_database and rag_instance is not None:
            try:
                import asyncio
                # 获取事件循环或创建新的
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                # 异步清理数据库中的相关数据
                loop.run_until_complete(self._clean_file_from_database(file_id, file_record, rag_instance))
                main_logger.info(f"已清理文件 {file_id} 的数据库数据")
            except Exception as e:
                main_logger.error(f"清理数据库数据失败: {str(e)}")

        # 删除元数据记录
        del metadata[file_id]
        self._save_metadata(metadata)

        return True

    async def _clean_file_from_database(self, file_id: str, file_record: dict, rag_instance):
        """清理数据库中与文件相关的数据"""
        try:
            # 生成文档ID前缀
            doc_id_prefix = f"doc-{file_id}"

            # 1. 清理 full_docs 中的文档数据
            all_docs = await rag_instance.full_docs.get_all()
            docs_to_delete = [k for k in all_docs.keys() if k.startswith(doc_id_prefix)]

            if docs_to_delete:
                for doc_id in docs_to_delete:
                    await rag_instance.full_docs.delete(doc_id)
                main_logger.info(f"删除了 {len(docs_to_delete)} 个文档记录")

            # 2. 清理 text_chunks 中的文本块
            all_chunks = await rag_instance.text_chunks.get_all()
            chunks_to_delete = [k for k, v in all_chunks.items()
                              if v.get("full_doc_id", "").startswith(doc_id_prefix)]

            if chunks_to_delete:
                for chunk_id in chunks_to_delete:
                    await rag_instance.text_chunks.delete(chunk_id)
                main_logger.info(f"删除了 {len(chunks_to_delete)} 个文本块")

            # 3. 清理向量数据库 (chunks_vdb)
            # 由于向量数据库可能没有直接的delete方法，我们需要通过chunk IDs来处理
            if chunks_to_delete and hasattr(rag_instance.chunks_vdb, 'delete'):
                for chunk_id in chunks_to_delete:
                    try:
                        await rag_instance.chunks_vdb.delete(chunk_id)
                    except Exception as e:
                        main_logger.warning(f"删除向量 {chunk_id} 失败: {str(e)}")
                main_logger.info(f"删除了 {len(chunks_to_delete)} 个向量嵌入")

            # 注意：实体关系超图 (chunk_entity_relation_hypergraph) 的清理比较复杂
            # 因为实体可能被多个文档共享，这里暂时不自动清理
            # 如果需要完整清理，建议使用清空整个数据库的功能

            main_logger.info(f"文件 {file_id} 的数据库数据清理完成")

        except Exception as e:
            main_logger.error(f"清理数据库数据时出错: {str(e)}")
            raise
    
    async def read_file_content(self, file_path: str) -> str:
        """读取文件内容"""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 根据文件类型选择不同的读取方式
        if file_path.suffix.lower() == '.pdf':
            return self._read_pdf(file_path)
        elif file_path.suffix.lower() in ['.docx']:
            return self._read_docx(file_path)
        elif file_path.suffix.lower() in ['.txt', '.md']:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                return await f.read()
        else:
            raise ValueError(f"不支持的文件类型: {file_path.suffix}")
    
    def _read_pdf(self, file_path: Path) -> str:
        """读取PDF文件内容"""
        try:
            import PyPDF2
            with open(file_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except Exception as e:
            raise ValueError(f"PDF文件读取失败: {str(e)}")
    
    def _read_docx(self, file_path: Path) -> str:
        """读取DOCX文件内容"""
        try:
            import docx2txt
            return docx2txt.process(str(file_path))
        except Exception as e:
            raise ValueError(f"DOCX文件读取失败: {str(e)}")

# 全局文件管理器实例
file_manager = FileManager() 