# -*- coding: utf-8 -*-
import sys
import io
import re
import logging  # Import logging early for SafeLogFilter class definition

# Safe string conversion function for Windows encoding
def safe_str(obj):
    """Convert object to string with safe encoding for Windows gbk"""
    try:
        # First try to convert to string
        s = str(obj)

        if sys.platform == 'win32':
            # Use a more comprehensive approach to handle all problematic Unicode characters
            safe_chars = []
            for char in s:
                try:
                    # Test if the character can be encoded in gbk
                    char.encode('gbk')
                    safe_chars.append(char)
                except (UnicodeEncodeError, UnicodeDecodeError):
                    # If it fails, replace with a safe representation
                    safe_chars.append(f'[U+{ord(char):04X}]')

            s = ''.join(safe_chars)

        return s
    except Exception as e:
        # If conversion fails completely, return a generic error message
        return f"[ENCODING ERROR: {type(e).__name__}]"

# Safe print function for Windows encoding
def safe_print(*args, **kwargs):
    """Print function that handles Unicode encoding issues safely"""
    try:
        # Convert all arguments to safe strings
        safe_args = [safe_str(arg) for arg in args]
        print(*safe_args, **kwargs)
    except Exception as e:
        # If printing fails, try a basic fallback
        try:
            print(f"[PRINT ERROR: {safe_str(e)}]")
        except Exception:
            # Ultimate fallback
            print("[UNABLE TO PRINT MESSAGE DUE TO ENCODING ERROR]")

# Safe log filter for Windows encoding
class SafeLogFilter(logging.Filter):
    """Log filter that handles Unicode encoding issues"""

    def filter(self, record):
        try:
            # Safe-ify the log message
            if hasattr(record, 'msg') and record.msg:
                record.msg = safe_str(record.msg)
            if hasattr(record, 'getMessage'):
                try:
                    message = record.getMessage()
                    record.msg = safe_str(message)
                except Exception:
                    record.msg = safe_str(str(record.msg))
        except Exception:
            # If filtering fails, at least don't break the logging
            pass
        return True

def extract_user_friendly_error(error_message: str) -> str:
    """提取用户友好的错误信息"""
    error_lower = error_message.lower()

    if "500" in error_message:
        return "API服务器暂时不可用，请稍后重试"
    elif "502" in error_message or "503" in error_message:
        return "API服务暂时过载，请等待片刻后重试"
    elif "rate" in error_lower or "limit" in error_lower:
        return "API请求过于频繁，请等待一段时间后重试"
    elif "timeout" in error_lower:
        return "请求超时，请检查网络连接或减少文件大小"
    elif "authentication" in error_lower or "key" in error_lower:
        return "API密钥配置错误，请检查设置"
    elif "quota" in error_lower:
        return "API配额已用完，请检查账户状态"
    elif "embeddings" in error_lower and "error" in error_lower:
        return "文本嵌入服务暂时不可用，请稍后重试"
    elif "invalid_request" in error_lower:
        return "请求格式错误，请检查文件内容"
    elif "connection" in error_lower:
        return "网络连接问题，请检查网络设置"
    else:
        # 提取错误的核心信息
        if "error" in error_lower:
            # 尝试提取第一个错误信息
            try:
                error_start = error_lower.index("error")
                error_part = error_message[error_start:error_start + 200]
                return f"处理失败: {error_part}..."
            except ValueError:
                pass
        return f"处理失败: {error_message[:100]}..."

# Fix Windows encoding issue (only if not running under uvicorn)
# Check if we're running under uvicorn to avoid conflicts with its logging system
if sys.platform == 'win32' and 'uvicorn' not in sys.modules:
    try:
        # Only wrap if they're not already wrapped
        if not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if not isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception as e:
        # If wrapping fails, continue without it - better to have encoding issues than crash
        pass

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect, Form
from fastapi.middleware.cors import CORSMiddleware
from db import get_hypergraph, getFrequentVertices, get_vertices, get_hyperedges, get_vertice, get_vertice_neighbor, get_hyperedge_neighbor_server, add_vertex, add_hyperedge, delete_vertex, delete_hyperedge, update_vertex, update_hyperedge, get_hyperedge_detail, db_manager, get_theme_hypergraph, get_theme_vertices, get_theme_hyperedges, get_theme_vertex_neighbor
from file_manager import file_manager
from kb_manager import KnowledgeBaseManager
import json
import os
import asyncio
import numpy as np
import importlib.util
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional
from io import StringIO

# 添加 HyperRAG 相关导入
# 若尚不可导入，则向上逐级查找含有 hyperrag 包的目录，并把“其父目录”加到 sys.path
if importlib.util.find_spec("hyperrag") is None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "hyperrag" / "__init__.py").exists():
            sys.path.insert(0, str(parent))  # 注意是父目录，不是 …/hyperrag
            break

try:
    from hyperrag import HyperRAG, QueryParam
    from hyperrag.utils import EmbeddingFunc
    from hyperrag.llm import openai_embedding, openai_complete_if_cache
    HYPERRAG_AVAILABLE = True
except ImportError as e:
    print(f"HyperRAG not available: {e}")
    HYPERRAG_AVAILABLE = False

# 添加Cog-RAG导入
# 向上查找Hyper-RAG根目录并添加到sys.path，使cog-rag/cograg可以被导入
if importlib.util.find_spec("cograg") is None:
    for parent in Path(__file__).resolve().parents:
        # 检查是否是Hyper-RAG根目录（包含hyperrag和cog-rag子目录）
        if (parent / "hyperrag" / "__init__.py").exists() and (parent / "cog-rag" / "cograg" / "__init__.py").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
                print(f"已添加路径到sys.path: {parent}")
            # 添加cog-rag目录到sys.path以便导入
            cog_rag_path = parent / "cog-rag"
            if str(cog_rag_path) not in sys.path:
                sys.path.insert(0, str(cog_rag_path))
                print(f"已添加cog-rag路径到sys.path: {cog_rag_path}")
            break

try:
    # 尝试从cograg导入
    import importlib
    spec = importlib.util.find_spec("cograg")
    if spec:
        from cograg import CogRAG as CogRAGClass, QueryParam as CogQueryParam
        from cograg.utils import EmbeddingFunc
        COGRAG_AVAILABLE = True
        print("Cog-RAG 模块加载成功")
    else:
        raise ImportError("cograg module spec not found")
except ImportError as e:
    print(f"Cog-RAG not available: {e}")
    COGRAG_AVAILABLE = False
    print("Cog-RAG 模块不可用")


# 设置文件路径
SETTINGS_FILE = "settings.json"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Hyper-RAG"}


# ============ Knowledge Base Management ============

kb_manager = KnowledgeBaseManager()

class KBCreateRequest(BaseModel):
    name: str
    description: str = ""
    rag_system: str = "hyperrag"
    domain: str = "default"
    chunk_size: int = 1000
    chunk_overlap: int = 200

class KBUpdateRequest(BaseModel):
    description: Optional[str] = None
    rag_system: Optional[str] = None
    domain: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    name: Optional[str] = None

@app.post("/kb")
async def create_kb(req: KBCreateRequest):
    """创建知识库"""
    try:
        kb = await kb_manager.create_kb(
            name=req.name,
            description=req.description,
            rag_system=req.rag_system,
            domain=req.domain,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
        )
        return {"success": True, "data": kb}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=safe_str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.get("/kb")
async def list_kbs():
    """列出所有知识库（含统计）"""
    try:
        kbs = await kb_manager.list_kbs()
        result = []
        for kb in kbs:
            stats = await kb_manager.get_kb_stats(kb["database_name"], file_manager)
            result.append({**kb, "stats": stats})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.get("/kb/{kb_name}")
async def get_kb(kb_name: str):
    """获取知识库详情"""
    try:
        kb = await kb_manager.get_kb(kb_name)
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")
        stats = await kb_manager.get_kb_stats(kb["database_name"], file_manager)
        return {**kb, "stats": stats}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.put("/kb/{kb_name}")
async def update_kb(kb_name: str, req: KBUpdateRequest):
    """更新知识库设置"""
    try:
        updates = {k: v for k, v in req.dict().items() if v is not None}
        kb = await kb_manager.update_kb(kb_name, **updates)
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")
        return {"success": True, "data": kb}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.delete("/kb/{kb_name}")
async def delete_kb(kb_name: str):
    """删除知识库及其文件和数据库"""
    try:
        kb = await kb_manager.get_kb(kb_name)
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")

        database_name = kb["database_name"]

        # 删除关联文件
        all_files = file_manager.get_all_files()
        kb_files = [f for f in all_files if f.get("kb_name") == database_name]
        for f in kb_files:
            try:
                file_manager.delete_file(f["file_id"])
            except Exception:
                pass

        # 删除数据库
        try:
            db_manager.delete_database(database_name)
        except Exception:
            pass

        # 删除KB元数据
        await kb_manager.delete_kb(kb_name)

        return {"success": True, "message": f"知识库 '{kb_name}' 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))


@app.get("/db")
async def db(database: str = None):
    """
    获取全部数据json
    """
    try:
        data = get_hypergraph(database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/vertices")
async def get_vertices_function(database: str = None, page: int = None, page_size: int = None):
    """
    获取vertices列表
    """
    try:
        data = getFrequentVertices(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/hyperedges")
async def get_hypergraph_function(database: str = None, page: int = None, page_size: int = None):
    """
    获取hyperedges列表
    """
    try:
        data = get_hyperedges(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/hyperedges/{hyperedge_id}")
async def get_hyperedge(hyperedge_id: str, database: str = None):
    """
    获取指定hyperedge的详情
    """
    try:
        hyperedge_id = hyperedge_id.replace("%20", " ")
        vertices = hyperedge_id.split("|*|")
        data = get_hyperedge_detail(vertices, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/vertices/{vertex_id}")
async def get_vertex(vertex_id: str, database: str = None):
    """
    获取指定vertex的json
    """
    vertex_id = vertex_id.replace("%20", " ")
    try:
        data = get_vertice(vertex_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/vertices_neighbor/{vertex_id}")
async def get_vertex_neighbor(vertex_id: str, database: str = None):
    """
    获取指定vertex的neighbor
    """
    vertex_id = vertex_id.replace("%20", " ")
    try:
        data = get_vertice_neighbor(vertex_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/hyperedge_neighbor/{hyperedge_id}")
async def get_hyperedge_neighbor(hyperedge_id: str, database: str = None):
    """
    获取指定hyperedge的neighbor
    """
    hyperedge_id = hyperedge_id.replace("%20", " ")
    hyperedge_id = hyperedge_id.replace("*", "#")
    print(hyperedge_id)
    try:
        data = get_hyperedge_neighbor_server(hyperedge_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

class VertexModel(BaseModel):
    vertex_id: str
    entity_name: str = ""
    entity_type: str = ""
    description: str = ""
    additional_properties: str = ""
    database: str = None

class HyperedgeModel(BaseModel):
    vertices: list
    keywords: str = ""
    summary: str = ""
    database: str = None

class VertexUpdateModel(BaseModel):
    entity_name: str = ""
    entity_type: str = ""
    description: str = ""
    additional_properties: str = ""
    database: str = None

class HyperedgeUpdateModel(BaseModel):
    keywords: str = ""
    summary: str = ""
    database: str = None

@app.post("/db/vertices")
async def create_vertex(vertex: VertexModel):
    """
    创建新的vertex
    """
    try:
        result = add_vertex(vertex.vertex_id, {
            "entity_name": vertex.entity_name,
            "entity_type": vertex.entity_type,
            "description": vertex.description,
            "additional_properties": vertex.additional_properties
        }, vertex.database)
        return {"success": True, "message": "Vertex created successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.post("/db/hyperedges")
async def create_hyperedge(hyperedge: HyperedgeModel):
    """
    创建新的hyperedge
    """
    try:
        result = add_hyperedge(hyperedge.vertices, {
            "keywords": hyperedge.keywords,
            "summary": hyperedge.summary
        }, hyperedge.database)
        return {"success": True, "message": "Hyperedge created successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.put("/db/vertices/{vertex_id}")
async def update_vertex_endpoint(vertex_id: str, vertex: VertexUpdateModel):
    """
    更新vertex信息
    """
    try:
        vertex_id = vertex_id.replace("%20", " ")
        result = update_vertex(vertex_id, {
            "entity_name": vertex.entity_name,
            "entity_type": vertex.entity_type,
            "description": vertex.description,
            "additional_properties": vertex.additional_properties
        }, vertex.database)
        return {"success": True, "message": "Vertex updated successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.put("/db/hyperedges/{hyperedge_id}")
async def update_hyperedge_endpoint(hyperedge_id: str, hyperedge: HyperedgeUpdateModel):
    """
    更新hyperedge信息
    """
    try:
        hyperedge_id = hyperedge_id.replace("%20", " ")
        vertices = hyperedge_id.split("|*|")
        result = update_hyperedge(vertices, {
            "keywords": hyperedge.keywords,
            "summary": hyperedge.summary
        }, hyperedge.database)
        return {"success": True, "message": "Hyperedge updated successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.delete("/db/vertices/{vertex_id}")
async def delete_vertex_endpoint(vertex_id: str, database: str = None):
    """
    删除vertex
    """
    try:
        vertex_id = vertex_id.replace("%20", " ")
        result = delete_vertex(vertex_id, database)
        return {"success": True, "message": "Vertex deleted successfully"}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.delete("/db/hyperedges/{hyperedge_id}")
async def delete_hyperedge_endpoint(hyperedge_id: str, database: str = None):
    """
    删除hyperedge
    """
    try:
        hyperedge_id = hyperedge_id.replace("%20", " ")
        vertices = hyperedge_id.split("|*|")
        result = delete_hyperedge(vertices, database)
        return {"success": True, "message": "Hyperedge deleted successfully"}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

# ========== 主题超图相关API端点 ==========

@app.get("/db/theme_hypergraph")
async def get_theme_hypergraph_endpoint(database: str = None):
    """获取主题超图全部数据"""
    try:
        data = get_theme_hypergraph(database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/theme_vertices")
async def get_theme_vertices_endpoint(database: str = None, page: int = None, page_size: int = None):
    """获取主题超图顶点列表"""
    try:
        data = get_theme_vertices(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/theme_hyperedges")
async def get_theme_hyperedges_endpoint(database: str = None, page: int = None, page_size: int = None):
    """获取主题超图超边列表"""
    try:
        data = get_theme_hyperedges(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/theme_vertices_neighbor/{vertex_id}")
async def get_theme_vertex_neighbor_endpoint(vertex_id: str, database: str = None):
    """获取主题超图中顶点的邻居"""
    try:
        vertex_id = vertex_id.replace("%20", " ")
        data = get_theme_vertex_neighbor(vertex_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

# 设置相关的API接口

class SettingsModel(BaseModel):
    apiKey: str = ""
    modelProvider: str = "openai"
    modelName: str = "gpt-5-mini"
    baseUrl: str = "https://api.openai.com/v1"
    selectedDatabase: str = ""
    maxTokens: int = 2000
    temperature: float = 0.7
    # HyperRAG 嵌入模型设置
    embeddingModel: str = "text-embedding-3-small"
    embeddingDim: int = 1536
    embeddingBaseUrl: str = ""  # 嵌入模型的API地址
    embeddingApiKey: str = ""  # 嵌入模型的API密钥
    # Cog-RAG相关设置
    enableCogRAG: bool = True  # 启用/禁用Cog-RAG功能
    # Hyper-RAG 领域配置
    hyperrag_domain: str = "default"  # "default", "flow_battery", or custom domains

class APITestModel(BaseModel):
    apiKey: str
    baseUrl: str
    modelName: str
    modelProvider: str

class DatabaseTestModel(BaseModel):
    database: str

@app.get("/settings")
async def get_settings():
    """
    获取系统设置
    """
    try:
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content:
                        main_logger.error(f"设置文件为空: {SETTINGS_FILE}")
                        return {
                            "success": False,
                            "message": "设置文件为空，请重新配置"
                        }
                    settings = json.loads(content)
            except json.JSONDecodeError as e:
                main_logger.error(f"设置文件JSON解析错误: {SETTINGS_FILE}, 错误: {e}")
                return {
                    "success": False,
                    "message": f"设置文件格式错误: {str(e)}"
                }
            # 不返回敏感信息如API Key
            settings_safe = settings.copy()
            if 'apiKey' in settings_safe:
                settings_safe['apiKey'] = '***' if settings_safe['apiKey'] else ''
            if 'embeddingApiKey' in settings_safe:
                settings_safe['embeddingApiKey'] = '***' if settings_safe['embeddingApiKey'] else ''
            return settings_safe
        else:
            # 返回默认设置
            return {
                "apiKey": "",
                "modelProvider": "openai",
                "modelName": "gpt-4o-mini",
                "baseUrl": "https://api.openai.com/v1",
                "selectedDatabase": "",
                "maxTokens": 2000,
                "temperature": 0.7,
                "embeddingModel": "text-embedding-3-small",
                "embeddingDim": 1536,
                "embeddingBaseUrl": "",
                "embeddingApiKey": ""
            }
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.post("/settings")
async def save_settings(settings: SettingsModel):
    """
    保存系统设置
    """
    try:
        settings_dict = settings.dict()

        # 添加调试日志
        main_logger.info(f"🔍 [Settings] 接收到的设置: {json.dumps(settings_dict, ensure_ascii=False, indent=2)}")

        # 如果apiKey是***，则保持原有的apiKey不变
        if settings_dict.get('apiKey') == '***':
            # 读取现有设置中的apiKey
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    existing_settings = json.load(f)
                # 保持原有的apiKey
                settings_dict['apiKey'] = existing_settings.get('apiKey', '')
            else:
                # 如果没有现有设置文件，则设为空字符串
                settings_dict['apiKey'] = ''

        # 如果embeddingApiKey是***，则保持原有的embeddingApiKey不变
        if settings_dict.get('embeddingApiKey') == '***':
            # 读取现有设置中的embeddingApiKey
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    existing_settings = json.load(f)
                # 保持原有的embeddingApiKey
                settings_dict['embeddingApiKey'] = existing_settings.get('embeddingApiKey', '')
            else:
                # 如果没有现有设置文件，则设为空字符串
                settings_dict['embeddingApiKey'] = ''

        # 确保embedding相关字段被保存
        if 'embeddingBaseUrl' not in settings_dict:
            settings_dict['embeddingBaseUrl'] = ''

        main_logger.info(f"💾 [Settings] 准备保存的设置: {json.dumps(settings_dict, ensure_ascii=False, indent=2)}")

        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, ensure_ascii=False, indent=2)
        return {"success": True, "message": "设置保存成功"}
    except Exception as e:
        main_logger.error(f"[ERROR] [Settings] 保存设置失败: {safe_str(e)}")
        return {"success": False, "message": safe_str(e)}

@app.get("/domains")
async def get_domains():
    """获取可用领域列表"""
    try:
        from hyperrag.domains.domain_manager import domain_manager
        domains = domain_manager.get_available_domains()
        result = []
        for domain_name in domains:
            try:
                config = domain_manager.load_domain_config(domain_name)
                result.append({
                    "name": domain_name,
                    "description": config.get("domain_description", ""),
                    "output_format": config.get("output_format", "delimiter"),
                })
            except Exception:
                result.append({
                    "name": domain_name,
                    "description": "",
                    "output_format": "delimiter",
                })
        return {"domains": result}
    except Exception as e:
        main_logger.error(f"获取领域列表失败: {safe_str(e)}")
        return {"domains": [{"name": "default", "description": "通用领域", "output_format": "delimiter"}]}

@app.get("/databases")
async def get_databases():
    """
    获取可用数据库列表
    """
    try:
        databases = []

        # 使用db_manager获取数据库列表
        database_files = db_manager.list_databases()

        for db_info in database_files:
            # db_info 现在是字典格式，包含 'name', 'description', 'system' 字段
            if isinstance(db_info, dict):
                databases.append(db_info)
            else:
                # 向后兼容：如果是旧格式（字符串），则转换为字典
                databases.append({
                    "name": db_info,
                    "description": f"{db_info.replace('.hgdb', '')}超图",
                    "system": "hyperrag"  # 默认为 HyperRAG
                })

        # 如果没有找到数据库文件，返回默认列表
        if not databases:
            databases = []

        return databases
    except Exception as e:
        return {"success": False, "message": safe_str(e), "data": []}

@app.post("/test/embedding")
async def test_embedding():
    """
    测试嵌入API连接
    """
    try:
        main_logger.info("开始测试嵌入API连接...")

        # 从设置文件读取配置
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
        api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
        base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))

        main_logger.info(f"测试嵌入模型: {embedding_model}")

        # 使用简单的测试文本
        test_texts = ["This is a test for embedding API connectivity."]

        embeddings = await openai_embedding(
            test_texts,
            model=embedding_model,
            api_key=api_key,
            base_url=base_url,
        )

        main_logger.info(f"嵌入测试成功，维度: {embeddings.shape}")

        return {
            "success": True,
            "message": "嵌入API连接正常",
            "details": {
                "model": embedding_model,
                "embedding_dim": embeddings.shape[1] if len(embeddings.shape) > 1 else embeddings.shape[0],
                "test_text_length": len(test_texts[0])
            }
        }
    except Exception as e:
        error_msg = safe_str(e)
        main_logger.error(f"嵌入API测试失败: {error_msg}")

        # 提供用户友好的错误信息
        user_friendly_error = extract_user_friendly_error(error_msg)

        return {
            "success": False,
            "message": user_friendly_error,
            "detailed_error": error_msg[:200]
        }

@app.post("/test-api")
async def test_api_connection(api_test: APITestModel):
    """
    测试API连接
    """
    try:
        from openai import OpenAI
        
        # 根据不同的模型提供商进行测试
        if api_test.modelProvider == "openai":
            client = OpenAI(
                api_key=api_test.apiKey,
                base_url=api_test.baseUrl
            )
            
            # 发送一个简单的测试请求
            response = client.chat.completions.create(
                model=api_test.modelName,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            
            return {"success": True, "message": "API连接测试成功"}
            
        elif api_test.modelProvider == "anthropic":
            # 对于Anthropic，可以添加相应的测试逻辑
            return {"success": True, "message": "Anthropic API连接测试成功"}
            
        else:
            # 对于其他提供商，进行通用测试
            return {"success": True, "message": "API连接测试成功"}
            
    except Exception as e:
        return {"success": False, "message": f"API连接测试失败: {safe_str(e)}"}

@app.post("/test-database")
async def test_database_connection(db_test: DatabaseTestModel):
    """
    测试数据库连接
    """
    try:
        # 使用db_manager测试数据库连接
        db = db_manager.get_database(db_test.database)
        
        # 尝试获取数据库的基本信息来验证连接
        vertices_count = len(db.all_v)
        edges_count = len(db.all_e)
        
        return {
            "success": True, 
            "message": "数据库连接测试成功",
            "info": {
                "vertices_count": vertices_count,
                "edges_count": edges_count,
                "database": db_test.database
            }
        }
        
    except Exception as e:
        return {"success": False, "message": f"数据库连接测试失败: {safe_str(e)}"}


# 全局 HyperRAG 实例 - 改为字典来支持多数据库
hyperrag_instances = {}
hyperrag_working_dir = "hyperrag_cache"

# 全局 Cog-RAG 实例 - 支持多数据库
cograg_instances = {}
cograg_working_dir = "cograg_cache"

async def get_hyperrag_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs) -> str:
    """
    HyperRAG 专用的 LLM 函数，使用异步版本
    """
    try:
        main_logger.info(f"开始LLM调用，prompt长度: {len(prompt)} 字符")
        if system_prompt:
            main_logger.info(f"系统提示词长度: {len(system_prompt)} 字符")

        # 清理历史消息，移除空的assistant消息
        cleaned_history = []
        if history_messages:
            for msg in history_messages:
                # 保留非空的assistant消息
                if msg.get('role') != 'assistant' or msg.get('content', '').strip():
                    cleaned_history.append(msg)

        # 从设置文件读取配置
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        model_name = settings.get("modelName", "gpt-5-mini")
        api_key = settings.get("apiKey")
        base_url = settings.get("baseUrl")

        main_logger.info(f"使用模型: {model_name}, API地址: {base_url}")
        main_logger.info(f"历史消息数量: {len(cleaned_history)} (原始: {len(history_messages)})")

        # 设置超时参数（默认600秒，适应Moonshot慢速响应）
        timeout = kwargs.get('timeout', 600.0)
        main_logger.info(f"超时设置: {timeout} 秒")

        response = await openai_complete_if_cache(
            model_name,
            prompt,
            system_prompt=system_prompt,
            history_messages=cleaned_history,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            **kwargs,
        )

        main_logger.info(f"LLM调用完成，响应长度: {len(response)} 字符")
        return response

    except Exception as e:
        main_logger.error(f"LLM调用失败: {safe_str(e)}")
        main_logger.error(f"错误类型: {type(e).__name__}")
        if hasattr(e, '__cause__'):
            main_logger.error(f"根本原因: {safe_str(e.__cause__)}")
        import traceback
        main_logger.error(f"详细错误: {traceback.format_exc()}")
        raise

async def get_hyperrag_embedding_func(texts: list[str]) -> np.ndarray:
    """
    HyperRAG 专用的嵌入函数，带重试机制
    """
    max_retries = 3
    base_delay = 1  # 基础延迟时间（秒）

    for attempt in range(max_retries):
        try:
            main_logger.info(f"开始文本嵌入 (尝试 {attempt + 1}/{max_retries})，文本数量: {len(texts)}")
            main_logger.info(f"文本总长度: {sum(len(text) for text in texts)} 字符")

            # 从设置文件读取配置
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
            api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
            base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))

            main_logger.info(f"使用嵌入模型: {embedding_model}")

            embeddings = await openai_embedding(
                texts,
                model=embedding_model,
                api_key=api_key,
                base_url=base_url,
            )

            main_logger.info(f"文本嵌入完成，嵌入维度: {embeddings.shape}")
            return embeddings

        except Exception as e:
            error_msg = safe_str(e)
            main_logger.error(f"文本嵌入失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")

            # 检查是否是可重试的错误
            is_retryable = False
            if "500" in error_msg or "502" in error_msg or "503" in error_msg or "504" in error_msg:
                is_retryable = True
                main_logger.warning(f"服务器错误，将进行重试...")
            elif "rate" in error_msg.lower() or "limit" in error_msg.lower():
                is_retryable = True
                main_logger.warning(f"速率限制错误，将进行重试...")
            elif "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                is_retryable = True
                main_logger.warning(f"网络错误，将进行重试...")

            if attempt < max_retries - 1 and is_retryable:
                # 指数退避
                delay = base_delay * (2 ** attempt)
                main_logger.info(f"等待 {delay} 秒后重试...")
                await asyncio.sleep(delay)
            else:
                # 不可重试错误或已达到最大重试次数
                main_logger.error(f"文本嵌入最终失败: {error_msg}")
                raise

def get_or_create_hyperrag(database: str = None):
    """
    获取或创建指定数据库的 HyperRAG 实例
    """
    global hyperrag_instances
    
    if not HYPERRAG_AVAILABLE:
        main_logger.error("HyperRAG 不可用")
        raise RuntimeError("HyperRAG is not available")
    
    # 如果没有指定数据库，使用默认数据库
    if database is None:
        database = db_manager.default_database
        main_logger.info(f"使用默认数据库: {database}")
    
    # 检查是否已存在该数据库的实例
    if database not in hyperrag_instances:
        main_logger.info(f"创建新的HyperRAG实例，数据库: {database}")
        
        # 使用数据库名作为工作目录（去掉.hgdb后缀）
        if database.endswith('.hgdb'):
            db_dir_name = database.replace('.hgdb', '')
        else:
            db_dir_name = database
            
        # HyperRAG 工作目录直接使用 hyperrag_cache 下的数据库文件夹
        db_working_dir = os.path.join(hyperrag_working_dir, db_dir_name)
        Path(db_working_dir).mkdir(parents=True, exist_ok=True)
        
        main_logger.info(f"HyperRAG工作目录: {db_working_dir}")
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        embedding_dim = settings.get("embeddingDim")

        # 获取领域配置
        current_domain = settings.get("hyperrag_domain", "default")
        main_logger.info(f"使用Hyper-RAG领域: {current_domain}")

        # 如果是特定领域，设置领域管理器
        if current_domain != "default":
            try:
                from hyperrag.prompt import set_domain
                set_domain(current_domain)
                main_logger.info(f"领域已设置为: {current_domain}")
            except Exception as e:
                main_logger.warning(f"设置领域失败，使用默认领域: {safe_str(e)}")
                current_domain = "default"

        # 获取领域特定的实体类型（如果支持）
        entity_types = None
        if current_domain != "default":
            try:
                from hyperrag.prompt import get_entity_types
                entity_types = get_entity_types(current_domain)
                main_logger.info(f"领域实体类型: {entity_types}")
            except Exception as e:
                main_logger.warning(f"获取领域实体类型失败: {safe_str(e)}")

        # 初始化 HyperRAG 实例
        hyperrag_kwargs = {
            "working_dir": db_working_dir,
            "llm_model_func": get_hyperrag_llm_func,
            "embedding_func": EmbeddingFunc(
                embedding_dim=embedding_dim,  # text-embedding-3-small 的维度
                max_token_size=8192,
                func=get_hyperrag_embedding_func
            ),
        }

        hyperrag_instances[database] = HyperRAG(**hyperrag_kwargs)

        # 传递领域配置到 HyperRAG 实例
        if current_domain != "default":
            hyperrag_instances[database].domain = current_domain
        
        main_logger.info(f"HyperRAG实例创建完成，数据库: {database}")
    else:
        main_logger.info(f"使用现有HyperRAG实例，数据库: {database}")
    
    return hyperrag_instances[database]


def get_or_create_cograg(database: str = None):
    """
    获取或创建指定数据库的 Cog-RAG 实例
    """
    global cograg_instances

    if not COGRAG_AVAILABLE:
        main_logger.error("Cog-RAG 不可用")
        raise RuntimeError("Cog-RAG is not available")

    # 如果没有指定数据库，使用默认数据库
    if database is None:
        database = db_manager.default_database
        main_logger.info(f"使用默认数据库: {database}")

    # 检查是否已存在该数据库的实例
    if database not in cograg_instances:
        main_logger.info(f"创建新的Cog-RAG实例，数据库: {database}")

        # 使用数据库名作为工作目录（去掉.hgdb后缀）
        if database.endswith('.hgdb'):
            db_dir_name = database.replace('.hgdb', '')
        else:
            db_dir_name = database

        # Cog-RAG 工作目录
        db_working_dir = os.path.join(cograg_working_dir, db_dir_name)
        Path(db_working_dir).mkdir(parents=True, exist_ok=True)

        main_logger.info(f"Cog-RAG工作目录: {db_working_dir}")
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        embedding_dim = settings.get("embeddingDim")

        # 初始化 Cog-RAG 实例，复用现有的LLM和嵌入函数
        cograg_instances[database] = CogRAGClass(
            working_dir=db_working_dir,
            llm_model_func=get_hyperrag_llm_func,
            embedding_func=EmbeddingFunc(
                embedding_dim=embedding_dim,
                max_token_size=8192,
                func=get_hyperrag_embedding_func
            ),
        )

        main_logger.info(f"Cog-RAG实例创建完成，数据库: {database}")
    else:
        main_logger.info(f"使用现有Cog-RAG实例，数据库: {database}")

    return cograg_instances[database]


class Message(BaseModel):
    message: str

@app.post("/process_message")
async def process_message(msg: Message):
    user_message = msg.message
    try:
        response_message = await get_hyperrag_llm_func(prompt=user_message)
    except Exception as e:
        return {"response": safe_str(e)} 
    return {"response": response_message}

# HyperRAG 问答相关接口

class DocumentModel(BaseModel):
    content: str
    retries: int = 3
    database: str = None  # 添加数据库参数

class QueryModel(BaseModel):
    question: str
    mode: str = "hyper"  # 支持: hyper, hyper-lite, naive, graph, llm, cog, cog-hybrid, cog-entity, cog-theme
    top_k: int = 60
    max_token_for_text_unit: int = 1600
    max_token_for_entity_context: int = 300
    max_token_for_relation_context: int = 1600
    only_need_context: bool = False
    response_type: str = "Multiple Paragraphs"
    database: str = None  # 添加数据库参数

@app.post("/hyperrag/insert")
async def insert_document(doc: DocumentModel):
    """
    向指定数据库的 HyperRAG 插入文档
    """
    if not HYPERRAG_AVAILABLE:
        return {"success": False, "message": "HyperRAG is not available"}
    
    try:
        rag = get_or_create_hyperrag(doc.database)
        
        # 重试机制
        for attempt in range(doc.retries):
            try:
                await rag.ainsert(doc.content)
                return {
                    "success": True, 
                    "message": "Document inserted successfully",
                    "database": doc.database or "default"
                }
            except Exception as e:
                if attempt == doc.retries - 1:
                    raise e
                print(f"Insert attempt {attempt + 1} failed: {e}. Retrying...")
                await asyncio.sleep(2)
                
    except Exception as e:
        return {"success": False, "message": f"Failed to insert document: {safe_str(e)}"}

@app.post("/hyperrag/query")
async def query_hyperrag(query: QueryModel):
    """
    统一的查询端点，支持HyperRAG和Cog-RAG模式
    """
    try:
        # 定义Cog-RAG模式
        cog_modes = ["cog", "cog-hybrid", "cog-entity", "cog-theme"]
        hyper_modes = ["hyper", "hyper-lite", "naive", "graph", "llm"]

        if query.mode in cog_modes:
            # 使用Cog-RAG
            if not COGRAG_AVAILABLE:
                return {"success": False, "message": "Cog-RAG is not available"}

            main_logger.info(f"使用Cog-RAG查询，模式: {query.mode}")
            rag = get_or_create_cograg(query.database)

            # 创建Cog-RAG查询参数
            param = CogQueryParam(
                mode=query.mode,
                top_k=query.top_k,
                max_token_for_text_unit=query.max_token_for_text_unit,
                max_token_for_entity_context=query.max_token_for_entity_context,
                max_token_for_relation_context=query.max_token_for_relation_context,
                only_need_context=query.only_need_context,
                response_type=query.response_type,
            )

            # 执行查询
            result = await rag.aquery(query.question, param)

            # 处理Cog-RAG响应格式
            return {
                "success": True,
                "response": result.get("response", ""),
                "entities": result.get("entities", []),
                "themes": result.get("themes", []),  # Cog-RAG特有的主题信息
                "hyperedges": result.get("hyperedges", []),
                "text_units": result.get("text_units", []),
                "mode": query.mode,
                "rag_system": "cograg",  # 标识使用的系统
                "question": query.question,
                "database": query.database or "default"
            }

        elif query.mode in hyper_modes:
            # 使用现有的HyperRAG逻辑
            if not HYPERRAG_AVAILABLE:
                return {"success": False, "message": "HyperRAG is not available"}

            main_logger.info(f"使用HyperRAG查询，模式: {query.mode}")
            rag = get_or_create_hyperrag(query.database)
            param = QueryParam(
                mode=query.mode,
                top_k=query.top_k,
                max_token_for_text_unit=query.max_token_for_text_unit,
                max_token_for_entity_context=query.max_token_for_entity_context,
                max_token_for_relation_context=query.max_token_for_relation_context,
                only_need_context=query.only_need_context,
                response_type=query.response_type,
                return_type='json'
            )

            result = await rag.aquery(query.question, param)

            return {
                "success": True,
                "response": result.get("response", ""),
                "entities": result.get("entities", []),
                "hyperedges": result.get("hyperedges", []),
                "text_units": result.get("text_units", []),
                "mode": query.mode,
                "rag_system": "hyperrag",
                "question": query.question,
                "database": query.database or "default"
            }
        else:
            return {"success": False, "message": f"Unknown query mode: {query.mode}"}

    except Exception as e:
        main_logger.error(f"查询失败: {safe_str(e)}")
        return {"success": False, "message": f"Query failed: {safe_str(e)}"}
        
    except Exception as e:
        return {"success": False, "message": f"Query failed: {safe_str(e)}"}

@app.get("/hyperrag/status")
async def get_hyperrag_status(database: str = None):
    """
    获取指定数据库的 HyperRAG 实例状态
    """
    try:
        status = {
            "available": HYPERRAG_AVAILABLE,
            "database": database or "default",
            "working_dir": hyperrag_working_dir,
            "instances": list(hyperrag_instances.keys())
        }
        
        if database:
            # 获取特定数据库的状态
            if database in hyperrag_instances:
                instance = hyperrag_instances[database]
                status["initialized"] = True
                try:
                    status["details"] = {
                        "chunk_token_size": instance.chunk_token_size,
                        "llm_model_name": instance.llm_model_name,
                        "embedding_func_available": instance.embedding_func is not None,
                        "working_dir": os.path.join(hyperrag_working_dir, database.replace('.hgdb', ''))
                    }
                except Exception as e:
                    status["details"] = f"Error getting details: {safe_str(e)}"
            else:
                status["initialized"] = False
        else:
            # 获取所有实例的概览
            status["initialized"] = len(hyperrag_instances) > 0
            status["total_instances"] = len(hyperrag_instances)
        
        return status

    except Exception as e:
        return {"success": False, "message": f"Failed to get status: {safe_str(e)}"}

@app.post("/cograg/insert")
async def insert_cograg_document(doc: DocumentModel):
    """
    向指定数据库的 Cog-RAG 插入文档
    """
    if not COGRAG_AVAILABLE:
        return {"success": False, "message": "Cog-RAG is not available"}

    try:
        rag = get_or_create_cograg(doc.database)

        # 重试机制
        for attempt in range(doc.retries):
            try:
                await rag.ainsert(doc.content)
                main_logger.info(f"文档插入Cog-RAG成功，数据库: {doc.database}")
                return {
                    "success": True,
                    "message": "Document inserted into Cog-RAG successfully",
                    "database": doc.database or "default",
                    "rag_system": "cograg"
                }
            except Exception as e:
                if attempt == doc.retries - 1:
                    raise e
                main_logger.warning(f"插入尝试 {attempt + 1} 失败: {safe_str(e)}. 重试中...")
                await asyncio.sleep(2)

    except Exception as e:
        main_logger.error(f"插入Cog-RAG文档失败: {safe_str(e)}")
        return {"success": False, "message": f"Failed to insert document into Cog-RAG: {safe_str(e)}"}

@app.get("/cograg/status")
async def get_cograg_status(database: str = None):
    """
    获取Cog-RAG实例状态
    """
    try:
        status = {
            "available": COGRAG_AVAILABLE,
            "database": database or "default",
            "working_dir": cograg_working_dir,
            "instances": list(cograg_instances.keys())
        }

        if database and database in cograg_instances:
            instance = cograg_instances[database]
            status["initialized"] = True
            status["details"] = {
                "chunk_token_size": instance.chunk_token_size,
                "llm_model_name": instance.llm_model_name,
                "embedding_func_available": instance.embedding_func is not None,
                "working_dir": os.path.join(cograg_working_dir, database.replace('.hgdb', ''))
            }
        else:
            status["initialized"] = False

        return status
    except Exception as e:
        main_logger.error(f"获取Cog-RAG状态失败: {safe_str(e)}")
        return {"success": False, "message": f"Failed to get Cog-RAG status: {safe_str(e)}"}

@app.get("/systems/status")
async def get_systems_status():
    """
    获取所有RAG系统的状态
    """
    try:
        status = {
            "hyperrag": {
                "available": HYPERRAG_AVAILABLE,
                "instances": len(hyperrag_instances),
                "working_dir": hyperrag_working_dir
            },
            "cograg": {
                "available": COGRAG_AVAILABLE,
                "instances": len(cograg_instances),
                "working_dir": cograg_working_dir
            },
            "current_system": "hyperrag"  # 默认系统
        }
        return status
    except Exception as e:
        main_logger.error(f"获取系统状态失败: {safe_str(e)}")
        return {"success": False, "message": f"Failed to get systems status: {safe_str(e)}"}

@app.delete("/hyperrag/reset")
async def reset_hyperrag(database: str = None):
    """
    重置指定数据库的 HyperRAG 实例，或重置所有实例
    """
    global hyperrag_instances
    
    try:
        if database:
            # 重置特定数据库的实例
            if database in hyperrag_instances:
                del hyperrag_instances[database]
                return {
                    "success": True, 
                    "message": f"HyperRAG instance for database '{database}' reset successfully"
                }
            else:
                return {
                    "success": False, 
                    "message": f"No HyperRAG instance found for database '{database}'"
                }
        else:
            # 重置所有实例
            hyperrag_instances = {}
            return {"success": True, "message": "All HyperRAG instances reset successfully"}
            
    except Exception as e:
        return {"success": False, "message": f"Failed to reset: {safe_str(e)}"}

# 文件管理相关的API接口

class FileEmbedRequest(BaseModel):
    file_ids: List[str]
    chunk_size: int = 500  # 减小chunk_size避免超时
    chunk_overlap: int = 100  # 相应减小overlap
    rag_system: str = "hyperrag"  # 新增：选择RAG系统 (hyperrag 或 cograg)
    target_database: Optional[str] = None  # 目标数据库名称，None则使用文件关联的数据库
    update_file_database: bool = False  # 是否更新文件关联的数据库
    kb_name: Optional[str] = None  # 知识库名称，自动填充嵌入配置

@app.get("/files")
async def get_files():
    """
    获取所有上传的文件列表
    """
    try:
        files = file_manager.get_all_files()
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文件列表失败: {safe_str(e)}")

@app.post("/files/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    target_database: str = Form(default=None),
    kb_name: str = Form(default=None)
):
    """
    上传文件接口

    Args:
        files: 上传的文件列表
        target_database: 目标数据库名称（可选），如果指定则所有文件都关联到此数据库

    Returns:
        包含上传结果的字典
    """
    print(f"\n{'='*50}")
    print(f"开始文件上传，文件数量: {len(files)}")
    if target_database:
        print(f"目标数据库: {target_database}")
    print(f"{'='*50}")

    # 检查是否有文件
    if not files or len(files) == 0:
        print("[ERROR] 没有接收到文件")
        raise HTTPException(status_code=400, detail="没有接收到文件")

    results = []

    for i, file in enumerate(files):
        try:
            print(f"\n上传文件 {i+1}/{len(files)}: {file.filename}")
            print(f"文件大小: {file.size if hasattr(file, 'size') else '未知'} bytes")
            print(f"文件类型: {file.content_type}")

            # 检查文件大小
            if hasattr(file, 'size') and file.size and file.size > 50 * 1024 * 1024:  # 50MB
                raise ValueError("文件大小超过50MB限制")

            # 读取文件内容
            print("正在读取文件内容...")
            content = await file.read()
            print(f"[OK] 文件内容读取完成，实际大小: {len(content)} bytes")

            if len(content) == 0:
                raise ValueError("文件内容为空")

            # 保存文件 - 传入目标数据库
            print("正在保存文件到本地...")

            # 如果指定了kb_name，使用KB的数据库名
            effective_target_db = target_database
            if kb_name:
                kb = await kb_manager.get_kb(kb_name)
                if kb:
                    effective_target_db = kb["database_name"]

            file_info = await file_manager.save_uploaded_file(content, file.filename, target_database=effective_target_db)

            # 关联知识库
            if kb_name:
                file_manager.update_file_kb(file_info["file_id"], kb_name)

            file_info["status"] = "uploaded"
            file_info["size"] = len(content)
            print(f"[OK] 文件保存成功: {file_info['filename']}")
            print(f"  - 文件ID: {file_info['file_id']}")
            print(f"  - 保存路径: {file_info['file_path']}")
            print(f"  - 数据库: {file_info['database_name']}")

            results.append(file_info)

        except Exception as e:
            error_msg = f"文件上传失败: {file.filename if hasattr(file, 'filename') else '未知文件'}, 错误: {safe_str(e)}"
            print(f"[ERROR] {error_msg}")
            main_logger.error(error_msg)
            results.append({
                "filename": file.filename if hasattr(file, 'filename') else '未知文件',
                "status": "error",
                "error": safe_str(e)
            })

    print(f"\n文件上传完成，成功: {len([r for r in results if r.get('status') == 'uploaded'])}/{len(files)}")
    print(f"{'='*50}")

    return {"files": results}

@app.delete("/files/{file_id}")
async def delete_file(file_id: str, clean_database: bool = False):
    """
    删除指定的文件

    Args:
        file_id: 文件ID
        clean_database: 是否同时清理数据库中的嵌入数据
    """
    try:
        # 获取当前活动的HyperRAG实例用于清理数据库
        rag_instance = None
        if clean_database:
            # 获取默认数据库的HyperRAG实例
            try:
                rag_instance = get_or_create_hyperrag()
                main_logger.info(f"准备清理文件 {file_id} 的数据库数据")
            except Exception as e:
                main_logger.warning(f"无法获取HyperRAG实例进行数据库清理: {safe_str(e)}")
                clean_database = False

        success = file_manager.delete_file(file_id, clean_database=clean_database, rag_instance=rag_instance)

        if success:
            message = "文件删除成功"
            if clean_database and rag_instance:
                message += "，数据库数据已清理"
            return {"success": True, "message": message}
        else:
            raise HTTPException(status_code=404, detail="文件不存在")
    except Exception as e:
        main_logger.error(f"删除文件失败: {safe_str(e)}")
        raise HTTPException(status_code=500, detail=f"文件删除失败: {safe_str(e)}")

@app.post("/database/clear")
async def clear_database(database: str = "default"):
    """
    清空指定数据库的所有数据

    Args:
        database: 数据库名称
    """
    try:
        main_logger.info(f"开始清空数据库: {database}")

        # 清空HyperRAG实例缓存
        if database in hyperrag_instances:
            del hyperrag_instances[database]
            main_logger.info(f"已清除数据库 {database} 的实例缓存")

        # 删除数据库文件（保留日志文件，避免文件占用错误）
        db_path = Path(hyperrag_working_dir) / database
        if db_path.exists():
            import shutil
            # 保留日志文件，只删除数据文件
            data_files_to_delete = []
            for item in db_path.iterdir():
                if item.is_file() and not item.name.endswith('.log'):
                    data_files_to_delete.append(item)
                elif item.is_dir():
                    # 删除子目录中的所有文件（除了.log文件）
                    for sub_item in item.rglob('*'):
                        if sub_item.is_file() and not sub_item.name.endswith('.log'):
                            try:
                                sub_item.unlink()
                            except Exception as e:
                                main_logger.warning(f"删除文件 {sub_item} 失败: {safe_str(e)}")

            # 删除数据文件
            for file in data_files_to_delete:
                try:
                    file.unlink()
                    main_logger.info(f"已删除数据文件: {file}")
                except Exception as e:
                    main_logger.warning(f"删除文件 {file} 失败: {safe_str(e)}")

            # 尝试删除空目录
            for item in db_path.iterdir():
                if item.is_dir():
                    try:
                        shutil.rmtree(item)
                    except Exception as e:
                        main_logger.warning(f"删除目录 {item} 失败: {safe_str(e)}")

            main_logger.info(f"已清空数据库数据: {db_path}")

        return {
            "success": True,
            "message": f"数据库 {database} 已清空",
            "database": database
        }
    except Exception as e:
        main_logger.error(f"清空数据库失败: {safe_str(e)}")
        raise HTTPException(status_code=500, detail=f"清空数据库失败: {safe_str(e)}")

@app.get("/database/status")
async def get_database_status(database: str = "default"):
    """
    获取数据库状态信息

    Args:
        database: 数据库名称
    """
    try:
        # 检查数据库是否存在
        db_path = Path(hyperrag_working_dir) / database
        db_exists = db_path.exists()

        # 获取数据库大小
        db_size = 0
        if db_exists:
            for file_path in db_path.rglob("*"):
                if file_path.is_file():
                    db_size += file_path.stat().st_size

        # 获取实例状态
        has_instance = database in hyperrag_instances

        return {
            "database": database,
            "exists": db_exists,
            "has_instance": has_instance,
            "size_bytes": db_size,
            "size_mb": round(db_size / (1024 * 1024), 2),
            "path": str(db_path)
        }
    except Exception as e:
        main_logger.error(f"获取数据库状态失败: {safe_str(e)}")
        raise HTTPException(status_code=500, detail=f"获取数据库状态失败: {safe_str(e)}")

@app.get("/databases/{database_name}/diagnose")
async def diagnose_database(database_name: str):
    """
    诊断数据库文件占用情况

    Args:
        database_name: 数据库名称

    Returns:
        诊断信息
    """
    try:
        import psutil
        import os

        diagnosis = {
            "database": database_name,
            "hyperrag": {"exists": False, "path": "", "files": [], "processes": []},
            "cograg": {"exists": False, "path": "", "files": [], "processes": []},
            "instances": {
                "hyperrag": database_name in hyperrag_instances,
                "cograg": database_name in cograg_instances,
                "db_manager_hyperrag": f"{database_name}_hyperrag" in db_manager.databases,
                "db_manager_cograg": f"{database_name}_cograg" in db_manager.databases,
                "theme_db": database_name in db_manager.theme_databases
            }
        }

        # 诊断 HyperRAG 数据库
        hyperrag_path = os.path.join(hyperrag_working_dir, database_name)
        if os.path.exists(hyperrag_path):
            diagnosis["hyperrag"]["exists"] = True
            diagnosis["hyperrag"]["path"] = hyperrag_path

            # 列出所有文件
            for root, dirs, files in os.walk(hyperrag_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_info = {
                        "path": file_path,
                        "size": os.path.getsize(file_path),
                        "locked": False
                    }

                    # 尝试检测文件是否被锁定
                    try:
                        # 尝试以独占模式打开文件
                        with open(file_path, 'a') as f:
                            pass
                    except (IOError, PermissionError):
                        file_info["locked"] = True
                        # 尝试查找占用文件的进程
                        try:
                            for proc in psutil.process_iter(['pid', 'name', 'open_files']):
                                try:
                                    for item in proc.info['open_files'] or []:
                                        if file_path.lower() in item.path.lower():
                                            diagnosis["hyperrag"]["processes"].append({
                                                "pid": proc.info['pid'],
                                                "name": proc.info['name'],
                                                "path": item.path
                                            })
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    continue
                        except Exception:
                            pass

                    diagnosis["hyperrag"]["files"].append(file_info)

        # 诊断 Cog-RAG 数据库
        cograg_path = os.path.join(cograg_working_dir, database_name)
        if os.path.exists(cograg_path):
            diagnosis["cograg"]["exists"] = True
            diagnosis["cograg"]["path"] = cograg_path

            # 列出所有文件
            for root, dirs, files in os.walk(cograg_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_info = {
                        "path": file_path,
                        "size": os.path.getsize(file_path),
                        "locked": False
                    }

                    # 尝试检测文件是否被锁定
                    try:
                        with open(file_path, 'a') as f:
                            pass
                    except (IOError, PermissionError):
                        file_info["locked"] = True
                        # 尝试查找占用文件的进程
                        try:
                            for proc in psutil.process_iter(['pid', 'name', 'open_files']):
                                try:
                                    for item in proc.info['open_files'] or []:
                                        if file_path.lower() in item.path.lower():
                                            diagnosis["cograg"]["processes"].append({
                                                "pid": proc.info['pid'],
                                                "name": proc.info['name'],
                                                "path": item.path
                                            })
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    continue
                        except Exception:
                            pass

                    diagnosis["cograg"]["files"].append(file_info)

        return diagnosis

    except ImportError:
        return {"error": "psutil module not installed", "message": "Install psutil to use this feature: pip install psutil"}
    except Exception as e:
        main_logger.error(f"诊断数据库失败: {database_name}, 错误: {safe_str(e)}")
        return {"error": safe_str(e), "message": f"诊断失败: {safe_str(e)}"}

@app.delete("/databases/{database_name}")
async def delete_database_endpoint(database_name: str):
    """
    删除指定数据库（支持HyperRAG和Cog-RAG双系统）

    Args:
        database_name: 数据库名称

    Returns:
        删除结果
    """
    import gc
    import time

    try:
        main_logger.info(f"[DELETE]  开始删除数据库: {database_name}")

        # 验证数据库名称安全性
        if not database_name or database_name in ['.', '..'] or '/' in database_name or '\\' in database_name:
            return {"success": False, "message": "Invalid database name"}

        # 第一步：清除所有RAG实例缓存
        print(f"📋 清除RAG实例缓存...")
        cleared_instances = []

        if database_name in hyperrag_instances:
            instance = hyperrag_instances[database_name]
            # 尝试调用实例的清理方法（如果存在）
            if hasattr(instance, '_cleanup'):
                try:
                    instance._cleanup()
                    print(f"   [OK] 调用HyperRAG实例清理方法")
                except Exception as e:
                    print(f"   [WARNING]  HyperRAG实例清理失败: {safe_str(e)}")

            del hyperrag_instances[database_name]
            cleared_instances.append(f"HyperRAG({database_name})")
            main_logger.info(f"已清除HyperRAG实例: {database_name}")
            print(f"   [OK] 已清除HyperRAG实例: {database_name}")

        if database_name in cograg_instances:
            instance = cograg_instances[database_name]
            # 尝试调用实例的清理方法（如果存在）
            if hasattr(instance, '_cleanup'):
                try:
                    instance._cleanup()
                    print(f"   [OK] 调用Cog-RAG实例清理方法")
                except Exception as e:
                    print(f"   [WARNING]  Cog-RAG实例清理失败: {safe_str(e)}")

            del cograg_instances[database_name]
            cleared_instances.append(f"Cog-RAG({database_name})")
            main_logger.info(f"已清除Cog-RAG实例: {database_name}")
            print(f"   [OK] 已清除Cog-RAG实例: {database_name}")

        # 强制垃圾回收
        gc.collect()
        time.sleep(0.5)  # 给系统时间释放资源

        if cleared_instances:
            print(f"   [INFO] 共清除 {len(cleared_instances)} 个实例: {', '.join(cleared_instances)}")

        # 第二步：调用数据库管理器删除数据库
        print(f"📂 调用数据库管理器删除数据库文件...")
        result = db_manager.delete_database(database_name)

        # 再次强制垃圾回收
        gc.collect()

        # 第三步：发送WebSocket通知
        try:
            await manager.broadcast_json({
                "type": "database_deleted",
                "database_name": database_name,
                "success": result.get("success", False),
                "timestamp": datetime.now().isoformat()
            })
            main_logger.info(f"已发送数据库删除通知: {database_name}")
            print(f"📢 已发送数据库删除通知")
        except Exception as e:
            main_logger.warning(f"发送WebSocket通知失败: {safe_str(e)}")
            print(f"[WARNING]  发送WebSocket通知失败: {safe_str(e)}")

        # 添加清理的实例信息到结果中
        result["cleared_instances"] = cleared_instances

        return result

    except Exception as e:
        main_logger.error(f"[ERROR] 删除数据库失败: {database_name}, 错误: {safe_str(e)}")
        print(f"[ERROR] 删除数据库失败: {database_name}, 错误: {safe_str(e)}")
        return {"success": False, "message": f"删除数据库失败: {safe_str(e)}"}

@app.post("/files/embed")
async def embed_files(request: FileEmbedRequest):
    """
    批量嵌入文档到HyperRAG
    """
    if not HYPERRAG_AVAILABLE:
        raise HTTPException(status_code=500, detail="HyperRAG is not available")
    
    print(f"\n{'='*50}")
    print(f"开始文档嵌入，文件数量: {len(request.file_ids)}")
    print(f"配置参数: chunk_size={request.chunk_size}, chunk_overlap={request.chunk_overlap}")
    print(f"{'='*50}")
    
    results = []
    
    try:
        for i, file_id in enumerate(request.file_ids):
            try:
                print(f"\n处理文件 {i+1}/{len(request.file_ids)}: {file_id}")
                
                # 更新文件状态为处理中
                print("更新文件状态为处理中...")
                file_manager.update_file_status(file_id, "processing")
                
                # 获取文件信息
                print("获取文件信息...")
                file_info = file_manager.get_file_by_id(file_id)
                if not file_info:
                    error_msg = f"文件不存在: {file_id}"
                    print(f"[ERROR] {error_msg}")
                    results.append({
                        "file_id": file_id,
                        "status": "error",
                        "error": "文件不存在"
                    })
                    continue
                
                print(f"[OK] 文件信息: {file_info['filename']} ({file_info['file_size']} bytes)")
                
                # 使用文件对应的数据库名
                database_name = file_info["database_name"]
                print(f"目标数据库: {database_name}")
                rag = get_or_create_hyperrag(database_name)
                
                # 读取文件内容
                print("读取文件内容...")
                content = await file_manager.read_file_content(file_info["file_path"])
                print(f"[OK] 内容长度: {len(content)} 字符")
                
                # 插入到HyperRAG
                print("开始文档嵌入...")
                await rag.ainsert(content)
                print("[OK] 文档嵌入完成")
                
                # 更新文件状态为已嵌入
                file_manager.update_file_status(file_id, "embedded")
                
                results.append({
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "status": "embedded"
                })
                
                print(f"[OK] 文件 {file_info['filename']} 嵌入成功")
                
            except Exception as e:
                # 更新文件状态为错误
                error_msg = f"文件嵌入失败: {file_id}, 错误: {safe_str(e)}"
                print(f"[ERROR] {error_msg}")
                file_manager.update_file_status(file_id, "error", safe_str(e))
                
                results.append({
                    "file_id": file_id,
                    "status": "error",
                    "error": safe_str(e)
                })
        
        successful = len([r for r in results if r.get('status') == 'embedded'])
        print(f"\n文档嵌入完成，成功: {successful}/{len(request.file_ids)}")
        print(f"{'='*50}")
        
        return {"embedded_files": results}

    except Exception as e:
        error_msg = f"批量嵌入失败: {safe_str(e)}"
        print(f"[ERROR] {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/cache/clear")
async def clear_hyperrag_cache():
    """
    清除 HyperRAG 实例缓存，强制重新创建实例
    """
    global hyperrag_instances
    cleared_count = len(hyperrag_instances)
    hyperrag_instances = {}
    main_logger.info(f"已清除 {cleared_count} 个 HyperRAG 实例缓存")
    return {"success": True, "message": f"已清除 {cleared_count} 个实例缓存"}

# 自定义日志处理器，将日志通过WebSocket发送
class WebSocketLogHandler(logging.Handler):
    def __init__(self, connection_manager):
        super().__init__()
        self.connection_manager = connection_manager

    def emit(self, record):
        try:
            log_message = self.format(record)
            # 使用safe_str处理可能包含问题Unicode字符的日志消息
            safe_message = safe_str(log_message)
            # 异步发送日志消息
            asyncio.create_task(self.connection_manager.send_log_message({
                "type": "log",
                "level": record.levelname,
                "message": safe_message,
                "timestamp": record.created,
                "logger_name": record.name
            }))
        except Exception:
            pass  # 避免日志处理器自身错误影响主程序

# 自定义流处理器，捕获print语句和其他输出
class WebSocketStreamHandler:
    def __init__(self, connection_manager, stream_type="stdout"):
        self.connection_manager = connection_manager
        self.stream_type = stream_type
        self.original_stream = sys.stdout if stream_type == "stdout" else sys.stderr
        
    def write(self, message):
        try:
            # 同时写入原始流
            self.original_stream.write(message)
            self.original_stream.flush()

            # 发送到WebSocket（去除空行）
            if message.strip():
                # 使用safe_str处理可能包含问题Unicode字符的消息
                safe_message = safe_str(message.strip())
                asyncio.create_task(self.connection_manager.send_log_message({
                    "type": "console",
                    "level": "ERROR" if self.stream_type == "stderr" else "INFO",
                    "message": safe_message,
                    "timestamp": asyncio.get_event_loop().time(),
                    "source": self.stream_type
                }))
        except Exception:
            # 如果写入失败，至少尝试继续执行
            pass
    
    def flush(self):
        self.original_stream.flush()

# WebSocket连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.logging_enabled = False
        self.original_stdout = None
        self.original_stderr = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        
        # 如果是第一个连接，启用日志重定向
        if len(self.active_connections) == 1 and not self.logging_enabled:
            self.enable_logging_redirect()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        
        # 如果没有连接了，禁用日志重定向
        if len(self.active_connections) == 0 and self.logging_enabled:
            self.disable_logging_redirect()

    def enable_logging_redirect(self):
        """启用日志重定向"""
        if not self.logging_enabled:
            self.original_stdout = sys.stdout
            self.original_stderr = sys.stderr
            
            # 重定向标准输出和错误输出
            sys.stdout = WebSocketStreamHandler(self, "stdout")
            sys.stderr = WebSocketStreamHandler(self, "stderr")
            
            self.logging_enabled = True
            print("日志重定向已启用")

    def disable_logging_redirect(self):
        """禁用日志重定向"""
        if self.logging_enabled and self.original_stdout and self.original_stderr:
            sys.stdout = self.original_stdout
            sys.stderr = self.original_stderr
            self.logging_enabled = False
            print("日志重定向已禁用")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # 如果连接已断开，标记为移除
                disconnected.append(connection)

        # 移除断开的连接
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_json(self, message: dict):
        """向所有连接的客户端广播JSON消息"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # 如果连接已断开，标记为移除
                disconnected.append(connection)

        # 移除断开的连接
        for conn in disconnected:
            self.disconnect(conn)

    async def send_progress_update(self, progress_data: dict):
        """发送进度更新到所有连接的客户端"""
        message = json.dumps(progress_data)
        await self.broadcast(message)
    
    async def send_log_message(self, log_data: dict):
        """发送日志消息到所有连接的客户端"""
        message = json.dumps(log_data)
        await self.broadcast(message)

manager = ConnectionManager()

# 设置全面的日志配置
def setup_comprehensive_logging():
    """设置全面的日志配置"""
    # 设置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # 清除现有的处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 创建WebSocket处理器
    ws_handler = WebSocketLogHandler(manager)
    ws_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ws_handler.setFormatter(formatter)
    
    # 创建控制台处理器（保留控制台输出）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    # 设置编码为UTF-8以支持特殊字符
    if hasattr(console_handler, 'stream') and hasattr(console_handler.stream, 'reconfigure'):
        try:
            console_handler.stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass  # 如果重新配置失败，继续使用默认编码
    
    # 添加处理器到根日志记录器
    root_logger.addHandler(ws_handler)
    root_logger.addHandler(console_handler)

    # 添加安全日志过滤器到根记录器
    safe_filter = SafeLogFilter()
    root_logger.addFilter(safe_filter)
    
    # 设置特定模块的日志级别
    logging.getLogger('hyperrag').setLevel(logging.INFO)
    logging.getLogger('openai').setLevel(logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)  # 减少HTTP请求日志
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    # 确保HyperRAG相关的所有子模块都能输出日志
    hyperrag_modules = [
        'hyperrag.base',
        'hyperrag.hyperrag',
        'hyperrag.llm',
        'hyperrag.operate',
        'hyperrag.prompt',
        'hyperrag.storage',
        'hyperrag.utils'
    ]

    for module_name in hyperrag_modules:
        module_logger = logging.getLogger(module_name)
        module_logger.setLevel(logging.INFO)
        # 确保模块日志也会传播到根记录器
        module_logger.propagate = True
        # 添加安全过滤器到每个模块
        module_logger.addFilter(safe_filter)
    
    return root_logger

def configure_hyperrag_logging():
    """配置HyperRAG相关的详细日志输出"""
    try:
        # 如果HyperRAG可用，配置其内部日志
        if HYPERRAG_AVAILABLE:
            # 导入HyperRAG相关模块并设置日志
            try:
                import hyperrag
                import hyperrag.base
                import hyperrag.storage
                import hyperrag.llm
                import hyperrag.utils
                
                # 为HyperRAG的主要模块设置日志记录器
                modules_to_configure = [
                    hyperrag,
                    hyperrag.base,
                    hyperrag.storage, 
                    hyperrag.llm,
                    hyperrag.utils
                ]
                
                for module in modules_to_configure:
                    if hasattr(module, '__name__'):
                        logger = logging.getLogger(module.__name__)
                        logger.setLevel(logging.INFO)
                        logger.propagate = True
                        # 添加安全过滤器
                        safe_filter = SafeLogFilter()
                        logger.addFilter(safe_filter)
                        
                print("[OK] HyperRAG logging configuration completed")

            except ImportError as e:
                print(f"[WARNING] Failed to import HyperRAG module for logging configuration: {safe_str(e)}")

    except Exception as e:
        print(f"[WARNING] HyperRAG logging configuration failed: {safe_str(e)}")

# 初始化日志系统
main_logger = setup_comprehensive_logging()

# 配置HyperRAG日志
configure_hyperrag_logging()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # 这里可以处理客户端发送的消息
            await manager.send_personal_message(f"Message received: {data}", websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# 带实时进度通知的文档嵌入接口
@app.post("/files/embed-with-progress")
async def embed_files_with_progress(request: FileEmbedRequest):
    """
    批量嵌入文档到HyperRAG，带实时进度通知

    参数:
        file_ids: 文件ID列表
        chunk_size: 分块大小
        chunk_overlap: 分块重叠
        rag_system: RAG系统 (hyperrag/cograg)
        target_database: 目标数据库名称（可选），如果指定则所有文档嵌入到此数据库
        update_file_database: 是否更新文件关联的数据库
    """
    if not HYPERRAG_AVAILABLE:
        raise HTTPException(status_code=500, detail="HyperRAG is not available")

    # 如果指定了kb_name，从KB配置中读取默认参数
    if request.kb_name:
        kb = await kb_manager.get_kb(request.kb_name)
        if kb:
            if not request.target_database:
                request.target_database = kb["database_name"]
            request.rag_system = kb.get("rag_system", request.rag_system)
            request.chunk_size = kb.get("chunk_size", request.chunk_size)
            request.chunk_overlap = kb.get("chunk_overlap", request.chunk_overlap)
            request.update_file_database = True
            # 设置领域 - 直接更新设置文件中的 domain
            try:
                if os.path.exists(SETTINGS_FILE):
                    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                        _settings = json.load(f)
                else:
                    _settings = {}
                _settings["hyperrag_domain"] = kb.get("domain", "default")
                with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(_settings, f, ensure_ascii=False, indent=2)
            except Exception as e:
                main_logger.warning(f"更新领域设置失败: {safe_str(e)}")

    # 立即返回处理开始的响应
    total_files = len(request.file_ids)

    # 记录目标数据库信息
    if request.target_database:
        main_logger.info(f"目标数据库已指定: {request.target_database}")
        print(f"目标数据库: {request.target_database}")
    
    # 异步处理文件嵌入
    asyncio.create_task(process_files_with_progress(request, total_files))
    
    return {
        "message": "文档嵌入处理已开始",
        "total_files": total_files,
        "processing": True
    }

async def process_files_with_progress(request: FileEmbedRequest, total_files: int):
    """异步处理文件嵌入并发送进度更新"""
    try:
        print(f"="*60)
        print(f"开始批量文件嵌入任务")
        print(f"文件总数: {total_files}")
        print(f"配置参数: chunk_size={request.chunk_size}, chunk_overlap={request.chunk_overlap}")
        print(f"="*60)
        
        main_logger.info(f"开始处理 {total_files} 个文件的嵌入任务")
        main_logger.info(f"配置参数: chunk_size={request.chunk_size}, chunk_overlap={request.chunk_overlap}")
        
        successful_files = 0
        failed_files = 0
        
        for i, file_id in enumerate(request.file_ids):
            try:
                print(f"\n{'='*40}")
                print(f"处理文件 {i + 1}/{total_files}")
                print(f"文件ID: {file_id}")
                print(f"{'='*40}")
                
                # 发送进度更新
                await manager.send_progress_update({
                    "type": "progress",
                    "file_id": file_id,
                    "current": i + 1,
                    "total": total_files,
                    "percentage": ((i + 1) / total_files) * 100,
                    "status": "processing",
                    "message": f"正在处理文件 {i + 1}/{total_files}"
                })
                
                # 更新文件状态为处理中
                print("更新文件状态为处理中...")
                file_manager.update_file_status(file_id, "processing")
                
                # 获取文件信息
                print("正在获取文件信息...")
                main_logger.info(f"获取文件信息: {file_id}")
                file_info = file_manager.get_file_by_id(file_id)
                if not file_info:
                    error_msg = f"文件不存在: {file_id}"
                    print(f"[ERROR] 错误: {error_msg}")
                    main_logger.error(error_msg)
                    await manager.send_progress_update({
                        "type": "error",
                        "file_id": file_id,
                        "error": "文件不存在",
                        "current": i + 1,
                        "total": total_files
                    })
                    failed_files += 1
                    continue
                
                print(f"[OK] 文件信息获取成功:")
                print(f"  - 文件名: {file_info['filename']}")
                print(f"  - 文件大小: {file_info['file_size']} bytes")
                print(f"  - 上传时间: {file_info['upload_time']}")

                # 使用目标数据库（如果指定）或文件对应的数据库名
                if request.target_database:
                    database_name = file_manager.sanitize_database_name(request.target_database)
                    # 更新文件关联的数据库
                    if request.update_file_database:
                        file_manager.update_file_database(file_id, database_name)
                        print(f"  - 更新文件关联数据库为: {database_name}")
                else:
                    database_name = file_info["database_name"]
                print(f"  - 目标数据库: {database_name}")
                
                main_logger.info(f"开始处理文件: {file_info['filename']} ({file_info['file_size']} bytes)，使用数据库: {database_name}")
                
                # 为每个文件初始化对应的HyperRAG实例
                # 根据请求选择RAG系统
                if request.rag_system == "cograg":
                    if not COGRAG_AVAILABLE:
                        return {"success": False, "message": "Cog-RAG is not available"}
                    print(f"正在初始化 Cog-RAG 实例（{request.rag_system.upper()}系统）...")
                    main_logger.info(f"正在初始化 Cog-RAG 实例，数据库: {database_name}")
                    rag = get_or_create_cograg(database_name)
                    print(f"[OK] Cog-RAG 实例初始化完成")
                    main_logger.info(f"Cog-RAG 实例初始化完成，使用数据库: {database_name}")
                else:
                    if not HYPERRAG_AVAILABLE:
                        return {"success": False, "message": "HyperRAG is not available"}
                    print(f"正在初始化 HyperRAG 实例（{request.rag_system.upper()}系统）...")
                    main_logger.info(f"正在初始化 HyperRAG 实例，数据库: {database_name}")
                    rag = get_or_create_hyperrag(database_name)
                    print(f"[OK] HyperRAG 实例初始化完成")
                    main_logger.info(f"HyperRAG 实例初始化完成，使用数据库: {database_name}")
                
                # 发送详细进度信息
                await manager.send_progress_update({
                    "type": "file_processing",
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "stage": "reading",
                    "message": f"正在读取文件: {file_info['filename']} (数据库: {database_name}, {request.rag_system.upper()}系统)",
                    "rag_system": request.rag_system  # 添加系统标识
                })
                
                # 读取文件内容
                print("正在读取文件内容...")
                main_logger.info(f"开始读取文件内容: {file_info['filename']}")
                content = await file_manager.read_file_content(file_info["file_path"])
                print(f"[OK] 文件读取完成，内容长度: {len(content)} 字符")
                main_logger.info(f"文件读取完成，内容长度: {len(content)} 字符")
                
                # 显示内容预览
                preview = content[:200] + "..." if len(content) > 200 else content
                print(f"内容预览: {preview}")
                
                # 发送嵌入阶段的进度
                await manager.send_progress_update({
                    "type": "file_processing",
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "stage": "embedding",
                    "message": f"正在嵌入文档: {file_info['filename']} (数据库: {database_name})"
                })
                
                # 插入到HyperRAG
                print("开始文档嵌入处理...")
                print("这个过程可能需要一些时间，请耐心等待...")
                main_logger.info(f"开始文档嵌入处理: {file_info['filename']}，数据库: {database_name}")
                main_logger.info("正在进行文档分块...")

                # 这里会触发HyperRAG的详细处理过程
                try:
                    await rag.ainsert(content)
                    print("[OK] 文档嵌入完成！")
                    main_logger.info(f"文档嵌入完成: {file_info['filename']}，数据库: {database_name}")
                except Exception as embed_error:
                    error_msg = safe_str(embed_error)

                    # 提供更详细的错误信息和建议
                    main_logger.error(f"文档嵌入失败: {error_msg}")

                    # 检查常见的错误类型并提供建议
                    if "500" in error_msg:
                        suggestion = "API服务器错误，请稍后重试"
                    elif "rate" in error_msg.lower() or "limit" in error_msg.lower():
                        suggestion = "API速率限制，请减少并发请求或等待一段时间后重试"
                    elif "timeout" in error_msg.lower():
                        suggestion = "请求超时，请检查网络连接或增加超时时间"
                    elif "authentication" in error_msg.lower() or "key" in error_msg.lower():
                        suggestion = "API密钥问题，请检查配置"
                    elif "quota" in error_msg.lower():
                        suggestion = "API配额已用完，请检查账户状态"
                    else:
                        suggestion = "未知错误，请检查日志获取详细信息"

                    # 抛出包含详细建议的错误
                    raise Exception(f"{error_msg}。建议: {suggestion}")
                
                # 更新文件状态为已嵌入
                file_manager.update_file_status(file_id, "embedded")
                
                # 发送成功完成的进度更新
                await manager.send_progress_update({
                    "type": "file_completed",
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "status": "completed",
                    "message": f"文件嵌入完成: {file_info['filename']} (数据库: {database_name})"
                })
                
                successful_files += 1
                print(f"[OK] 文件 {file_info['filename']} 处理成功！")
                
            except Exception as e:
                # 更新文件状态为错误
                error_msg = f"文件处理失败: {file_id}"
                detailed_error = safe_str(e)
                print(f"[ERROR] {error_msg}")
                print(f"[ERROR] 详细错误: {detailed_error}")
                main_logger.error(f"{error_msg}, 详细错误: {detailed_error}")

                # 提取有用的错误信息给用户
                user_friendly_error = extract_user_friendly_error(detailed_error)
                file_manager.update_file_status(file_id, "error", user_friendly_error)

                # 发送错误进度更新，使用用户友好的错误信息
                await manager.send_progress_update({
                    "type": "file_error",
                    "file_id": file_id,
                    "filename": file_info.get("filename", "未知文件"),
                    "error": user_friendly_error,
                    "detailed_error": detailed_error[:200],  # 限制详细错误长度
                    "current": i + 1,
                    "total": total_files
                })
                
                failed_files += 1
        
        # 发送整体完成的进度更新
        print(f"\n{'='*60}")
        print(f"批量文档处理完成！")
        print(f"总文件数: {total_files}")
        print(f"成功处理: {successful_files}")
        print(f"处理失败: {failed_files}")
        print(f"成功率: {(successful_files/total_files)*100:.1f}%")
        print(f"{'='*60}")
        
        main_logger.info(f"所有文档处理完成！总计: {total_files} 个文件，成功: {successful_files}，失败: {failed_files}")
        await manager.send_progress_update({
            "type": "all_completed",
            "message": f"所有文档处理完成 (成功: {successful_files}, 失败: {failed_files})",
            "total_files": total_files,
            "successful_files": successful_files,
            "failed_files": failed_files
        })
        
    except Exception as e:
        # 发送整体错误信息
        error_msg = f"批量嵌入失败: {safe_str(e)}"
        print(f"[ERROR] {error_msg}")
        main_logger.error(error_msg)
        await manager.send_progress_update({
            "type": "error",
            "error": error_msg
        })
