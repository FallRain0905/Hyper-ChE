# -*- coding: utf-8 -*-
import sys
import io

# Set console encoding to UTF-8 for Windows (only if not running under uvicorn)
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

from hyperdb import HypergraphDB
import os

class DatabaseManager:
    """数据库管理器，支持多个数据库实例和双系统"""
    def __init__(self):
        self.databases = {}
        self.theme_databases = {}  # 新增：主题超图数据库缓存
        self.cache_dir = "hyperrag_cache"
        self.cograg_cache_dir = "cograg_cache"
        
    def get_database(self, database_name=None):
        """获取数据库实例

        Args:
            database_name: 数据库名称
        """
        if database_name is None:
            return None

        # 尝试在 hyperrag_cache 中查找
        hyperrag_path = os.path.join(self.cache_dir, database_name, "hypergraph_chunk_entity_relation.hgdb")
        database_path = None
        system = None

        if os.path.exists(hyperrag_path):
            database_path = hyperrag_path
            system = "hyperrag"
        else:
            # 尝试在 cograg_cache 中查找
            cograg_path = os.path.join(self.cograg_cache_dir, database_name, "hypergraph_chunk_entity_relation.hgdb")
            if os.path.exists(cograg_path):
                database_path = cograg_path
                system = "cograg"

        # 检查数据库文件是否存在
        if not database_path:
            raise Exception(f"Database '{database_name}' not found in either hyperrag_cache or cograg_cache")

        # 使用唯一键存储数据库实例 (database_name_system)
        db_key = f"{database_name}_{system}"

        # 如果数据库实例不存在，创建新实例
        if db_key not in self.databases:
            self.databases[db_key] = HypergraphDB(storage_file=database_path)

        return self.databases[db_key]
    
    def validate_database_file(self, db_path: str) -> bool:
        """
        验证数据库文件是否完整和可用

        Args:
            db_path: 数据库文件路径

        Returns:
            数据库是否有效
        """
        try:
            # 检查数据库文件是否存在
            hgdb_file = os.path.join(db_path, "hypergraph_chunk_entity_relation.hgdb")
            if not os.path.exists(hgdb_file):
                return False

            # 尝试打开数据库文件（不进行完整加载，只验证可读性）
            try:
                with open(hgdb_file, 'rb') as f:
                    # 读取前几个字节验证文件格式
                    header = f.read(16)
                    if len(header) < 16:
                        return False
            except Exception as e:
                print(f"数据库文件验证失败: {db_path}, 错误: {e}")
                return False

            return True
        except Exception as e:
            print(f"数据库验证异常: {db_path}, 错误: {e}")
            return False

    def list_databases(self):
        """列出hyperrag_cache和cograg_cache目录下所有可用的数据库文件"""
        databases = []

        # 扫描 hyperrag_cache 目录
        if os.path.exists(self.cache_dir):
            try:
                for file in os.listdir(self.cache_dir):
                    file_path = os.path.join(self.cache_dir, file)
                    if os.path.isdir(file_path):
                        # 验证数据库文件完整性
                        if self.validate_database_file(file_path):
                            databases.append({
                                "name": file,
                                "description": f"{file} 超图 (HyperRAG)",
                                "system": "hyperrag",
                                "valid": True
                            })
                        else:
                            print(f"跳过无效数据库: {file_path}")
            except OSError:
                pass

        # 扫描 cograg_cache 目录
        if os.path.exists(self.cograg_cache_dir):
            try:
                for file in os.listdir(self.cograg_cache_dir):
                    file_path = os.path.join(self.cograg_cache_dir, file)
                    if os.path.isdir(file_path):
                        # 验证数据库文件完整性
                        if self.validate_database_file(file_path):
                            databases.append({
                                "name": file,
                                "description": f"{file} 超图 (Cog-RAG)",
                                "system": "cograg",
                                "valid": True
                            })
                        else:
                            print(f"跳过无效数据库: {file_path}")
            except OSError:
                pass

        return databases

    def _safe_delete_file(self, file_path: str, max_retries: int = 3, delay: float = 1.0) -> bool:
        """
        安全删除文件，处理文件占用问题

        Args:
            file_path: 文件路径
            max_retries: 最大重试次数
            delay: 重试延迟（秒）

        Returns:
            是否删除成功
        """
        import time
        import gc

        for attempt in range(max_retries):
            try:
                if os.path.exists(file_path):
                    # 尝试删除文件
                    os.unlink(file_path)
                    print(f"✅ 成功删除文件: {file_path}")
                    return True
                else:
                    return True  # 文件不存在，视为成功

            except PermissionError as e:
                print(f"⚠️  文件被占用，重试 {attempt + 1}/{max_retries}: {file_path}")
                print(f"   错误: {e}")

                # 强制垃圾回收，释放可能持有文件句柄的对象
                gc.collect()

                # 等待一段时间后重试
                if attempt < max_retries - 1:
                    time.sleep(delay)
                else:
                    # 最后一次重试失败，返回 False
                    print(f"❌ 删除文件失败，已达最大重试次数: {file_path}")
                    return False

            except Exception as e:
                print(f"❌ 删除文件时发生意外错误: {file_path}")
                print(f"   错误: {e}")
                return False

        return False

    def _close_log_files(self, dir_path: str):
        """
        尝试关闭可能占用日志文件的处理器

        Args:
            dir_path: 目录路径
        """
        import logging
        import sys

        try:
            # 获取所有日志处理器
            root_logger = logging.getLogger()
            handlers_to_remove = []

            for handler in root_logger.handlers[:]:
                # 检查处理器是否关联到目标目录的日志文件
                if hasattr(handler, 'baseFilename'):
                    handler_file = handler.baseFilename
                    if dir_path in handler_file:
                        print(f"🔒 找到关联的日志处理器: {handler_file}")
                        # 尝试关闭处理器
                        try:
                            handler.close()
                            handlers_to_remove.append(handler)
                            print(f"   ✅ 已关闭日志处理器: {handler_file}")
                        except Exception as e:
                            print(f"   ⚠️  关闭日志处理器失败: {e}")

            # 移除已关闭的处理器
            for handler in handlers_to_remove:
                root_logger.removeHandler(handler)
                print(f"   🗑️  已移除日志处理器")

            # 强制刷新标准输出
            sys.stdout.flush()
            sys.stderr.flush()

        except Exception as e:
            print(f"⚠️  关闭日志文件时发生错误: {e}")

    def _safe_delete_directory(self, dir_path: str, max_retries: int = 3, delay: float = 1.0) -> dict:
        """
        安全删除目录，处理文件占用问题

        Args:
            dir_path: 目录路径
            max_retries: 最大重试次数
            delay: 重试延迟（秒）

        Returns:
            删除结果字典
        """
        import time
        import gc
        import shutil

        result = {
            "success": False,
            "message": "",
            "failed_files": [],
            "partial_success": False
        }

        if not os.path.exists(dir_path):
            result["success"] = True
            result["message"] = f"目录不存在，跳过删除: {dir_path}"
            return result

        print(f"🗑️  开始删除目录: {dir_path}")

        # 尝试关闭可能占用日志文件的处理器
        print(f"🔒 检查并关闭日志文件处理器...")
        self._close_log_files(dir_path)
        time.sleep(0.3)  # 给系统时间释放文件句柄

        for attempt in range(max_retries):
            try:
                # 第一次尝试：直接删除整个目录
                shutil.rmtree(dir_path)
                result["success"] = True
                result["message"] = f"目录删除成功: {dir_path}"
                print(f"✅ 目录删除成功: {dir_path}")
                return result

            except PermissionError as e:
                print(f"⚠️  目录删除被占用，尝试逐文件删除 (重试 {attempt + 1}/{max_retries})")
                print(f"   错误: {e}")

                # 强制垃圾回收
                gc.collect()
                time.sleep(delay)

                # 尝试逐文件删除
                try:
                    failed_files = []
                    deleted_count = 0

                    # 遍历目录中的所有文件和子目录
                    for root, dirs, files in os.walk(dir_path, topdown=False):
                        # 先删除文件
                        for file in files:
                            file_path = os.path.join(root, file)
                            if not self._safe_delete_file(file_path, max_retries=2, delay=0.5):
                                failed_files.append(file_path)
                            else:
                                deleted_count += 1

                        # 再删除空目录
                        for dir_name in dirs:
                            dir_full_path = os.path.join(root, dir_name)
                            try:
                                os.rmdir(dir_full_path)
                                print(f"✅ 删除空目录: {dir_full_path}")
                            except Exception as e:
                                print(f"⚠️  删除目录失败: {dir_full_path}, 错误: {e}")
                                failed_files.append(dir_full_path)

                    # 尝试删除根目录
                    try:
                        os.rmdir(dir_path)
                        print(f"✅ 删除根目录: {dir_path}")
                    except Exception as e:
                        print(f"⚠️  删除根目录失败: {dir_path}, 错误: {e}")
                        failed_files.append(dir_path)

                    # 判断删除结果
                    if not failed_files:
                        result["success"] = True
                        result["message"] = f"目录及其所有内容删除成功: {dir_path} (共删除 {deleted_count} 个文件)"
                        print(f"✅ 完全删除成功: {dir_path}")
                        return result
                    elif deleted_count > 0:
                        result["partial_success"] = True
                        result["message"] = f"部分删除成功: {dir_path} (成功删除 {deleted_count} 个文件，{len(failed_files)} 个文件失败)"
                        result["failed_files"] = failed_files
                        print(f"⚠️  部分删除成功: {deleted_count} 个文件删除成功，{len(failed_files)} 个文件失败")
                        return result
                    else:
                        # 所有文件都删除失败，继续重试
                        if attempt < max_retries - 1:
                            time.sleep(delay)
                            continue
                        else:
                            result["success"] = False
                            result["message"] = f"目录删除失败: {dir_path} (所有文件都被占用)"
                            result["failed_files"] = failed_files
                            print(f"❌ 目录删除失败: {dir_path}")
                            return result

                except Exception as inner_e:
                    print(f"❌ 逐文件删除过程中发生错误: {inner_e}")
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        continue
                    else:
                        result["success"] = False
                        result["message"] = f"目录删除失败: {str(inner_e)}"
                        return result

            except Exception as e:
                print(f"❌ 删除目录时发生意外错误: {dir_path}")
                print(f"   错误: {e}")
                if attempt < max_retries - 1:
                    gc.collect()
                    time.sleep(delay)
                    continue
                else:
                    result["success"] = False
                    result["message"] = f"目录删除失败: {str(e)}"
                    return result

        return result

    def delete_database(self, database_name: str) -> dict:
        """
        删除指定数据库（支持HyperRAG和Cog-RAG双系统）

        Args:
            database_name: 数据库名称

        Returns:
            删除结果字典，包含各系统的删除状态
        """
        import gc
        import time

        result = {
            "database": database_name,
            "hyperrag": {"success": False, "message": "", "failed_files": []},
            "cograg": {"success": False, "message": "", "failed_files": []}
        }

        print(f"\n{'='*60}")
        print(f"🗑️  开始删除数据库: {database_name}")
        print(f"{'='*60}")

        # 第一步：清除内存中的数据库实例
        print("📋 第一步：清除内存中的数据库实例...")
        db_key_hyperrag = f"{database_name}_hyperrag"
        db_key_cograg = f"{database_name}_cograg"

        if db_key_hyperrag in self.databases:
            del self.databases[db_key_hyperrag]
            print(f"   ✅ 已清除数据库实例: {db_key_hyperrag}")

        if db_key_cograg in self.databases:
            del self.databases[db_key_cograg]
            print(f"   ✅ 已清除数据库实例: {db_key_cograg}")

        # 清除主题数据库缓存
        if database_name in self.theme_databases:
            del self.theme_databases[database_name]
            print(f"   ✅ 已清除主题数据库实例: {database_name}")

        # 强制垃圾回收，释放文件句柄
        gc.collect()
        time.sleep(0.5)  # 给系统一点时间释放资源

        # 第二步：删除HyperRAG数据库
        print(f"📂 第二步：删除HyperRAG数据库...")
        hyperrag_db_path = os.path.join(self.cache_dir, database_name)
        if os.path.exists(hyperrag_db_path):
            hyperrag_result = self._safe_delete_directory(hyperrag_db_path, max_retries=3, delay=1.0)
            result["hyperrag"]["success"] = hyperrag_result["success"]
            result["hyperrag"]["message"] = hyperrag_result["message"]
            result["hyperrag"]["failed_files"] = hyperrag_result.get("failed_files", [])
            result["hyperrag"]["partial_success"] = hyperrag_result.get("partial_success", False)
        else:
            result["hyperrag"]["success"] = True
            result["hyperrag"]["message"] = "HyperRAG数据库不存在，跳过删除"
            print(f"   ℹ️  HyperRAG数据库不存在，跳过删除")

        # 再次强制垃圾回收
        gc.collect()
        time.sleep(0.5)

        # 第三步：删除Cog-RAG数据库
        print(f"📂 第三步：删除Cog-RAG数据库...")
        cograg_db_path = os.path.join(self.cograg_cache_dir, database_name)
        if os.path.exists(cograg_db_path):
            cograg_result = self._safe_delete_directory(cograg_db_path, max_retries=3, delay=1.0)
            result["cograg"]["success"] = cograg_result["success"]
            result["cograg"]["message"] = cograg_result["message"]
            result["cograg"]["failed_files"] = cograg_result.get("failed_files", [])
            result["cograg"]["partial_success"] = cograg_result.get("partial_success", False)
        else:
            result["cograg"]["success"] = True
            result["cograg"]["message"] = "Cog-RAG数据库不存在，跳过删除"
            print(f"   ℹ️  Cog-RAG数据库不存在，跳过删除")

        # 判断整体删除是否成功
        hyperrag_success = result["hyperrag"]["success"] or result["hyperrag"].get("partial_success", False)
        cograg_success = result["cograg"]["success"] or result["cograg"].get("partial_success", False)

        all_success = hyperrag_success and cograg_success
        result["success"] = all_success

        print(f"\n{'='*60}")
        if all_success:
            print(f"✅ 数据库删除完成: {database_name}")
        else:
            print(f"⚠️  数据库删除部分完成: {database_name}")
            if result["hyperrag"].get("failed_files"):
                print(f"   HyperRAG失败文件: {len(result['hyperrag']['failed_files'])} 个")
            if result["cograg"].get("failed_files"):
                print(f"   Cog-RAG失败文件: {len(result['cograg']['failed_files'])} 个")
        print(f"{'='*60}\n")

        return result

    def get_theme_database(self, database_name: str):
        """获取主题超图数据库实例

        Args:
            database_name: 数据库名称

        Returns:
            HypergraphDB实例或None（如果主题超图不存在）
        """
        if database_name not in self.theme_databases:
            # 检查数据库是否存在
            db_path = self._get_database_path(database_name)
            if not db_path:
                return None

            # 加载主题超图数据库
            theme_hgdb_path = os.path.join(db_path, "hypergraph_chunk_key_theme.hgdb")
            if not os.path.exists(theme_hgdb_path):
                return None

            self.theme_databases[database_name] = HypergraphDB(storage_file=theme_hgdb_path)

        return self.theme_databases[database_name]

    def _get_database_path(self, database_name: str) -> str:
        """获取数据库路径

        Args:
            database_name: 数据库名称

        Returns:
            数据库路径或None
        """
        # 先检查cograg_cache
        cograg_path = os.path.join(self.cograg_cache_dir, database_name)
        if os.path.exists(cograg_path):
            return cograg_path

        # 再检查hyperrag_cache
        hyperrag_path = os.path.join(self.cache_dir, database_name)
        if os.path.exists(hyperrag_path):
            return hyperrag_path

        return None

# 全局数据库管理器实例
db_manager = DatabaseManager()

# 为了向后兼容，保留原有的hg变量
hg = db_manager.get_database()

# 声明函数
def get_hypergraph(database=None):
    # 获取指定数据库实例
    db = db_manager.get_database(database)
    # 声明变量 赋值 db.all_v
    all_v = db.all_v
    # 声明变量 赋值 db.all_e
    all_e = db.all_e

    return get_all_detail(all_v, all_e, database)

def get_vertices(database=None, page=None, page_size=None):
    """
    获取vertices列表
    """
    db = db_manager.get_database(database)
    all_v = list(db.all_v)  # 强制转为 list
    
    # 如果没有分页参数，返回所有数据
    if page is None or page_size is None:
        return all_v
    
    # 计算分页
    total = len(all_v)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    
    # 获取分页数据
    page_data = all_v[start_idx:end_idx]
    
    return {
        'data': page_data,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': (total + page_size - 1) // page_size
    }

def getFrequentVertices(database=None, page=None, page_size=None):
    """
    获取有边的vertices列表，支持分页
    """
    db = db_manager.get_database(database)
    
    # 从 all_e 中取出出现两次以上的vertices
    frequent_vertices = {}
    for e in db.all_e:
        for v in e:
            if v in frequent_vertices:
                frequent_vertices[v] += 1
            else:
                frequent_vertices[v] = 1
    
    frequent_vertices = [v for v, count in frequent_vertices.items() if count >= 2]

    # 如果没有分页参数，返回所有数据
    if page is None or page_size is None:
        return frequent_vertices

    # 计算分页
    total = len(frequent_vertices)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size

    # 获取分页数据
    page_data = frequent_vertices[start_idx:end_idx]

    return {
        'data': page_data,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': (total + page_size - 1) // page_size
    }

def get_vertice(vertex_id: str, database=None):
    """
    获取指定vertex的json
    """
    db = db_manager.get_database(database)
    vertex = db.v(vertex_id)
    return vertex

def get_hyperedges(database=None, page=None, page_size=None):
    """
    获取hyperedges列表（包含详细信息）
    """
    db = db_manager.get_database(database)
    all_e = list(db.all_e)  # 强制转为 list

    hyperedges = []
    for e in all_e:
        hyperedge_id = '|*|'.join(e)
        hyperedge_data = db.e(e)
        
        # 构建返回数据
        edge_info = {
            'id': hyperedge_id,
            'vertices': list(e),
            'keywords': hyperedge_data.get('keywords', ''),
            'summary': hyperedge_data.get('summary', ''),
            'description': hyperedge_data.get('keywords', '')  # 使用keywords作为描述
        }
        hyperedges.append(edge_info)

    # 如果没有分页参数，返回所有数据
    if page is None or page_size is None:
        return hyperedges
    
    # 计算分页
    total = len(hyperedges)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    
    # 获取分页数据
    page_data = hyperedges[start_idx:end_idx]
    
    return {
        'data': page_data,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': (total + page_size - 1) // page_size
    }

def get_hyperedge(hyperedge_id: str, database=None):
    """
    获取指定hyperedge的json
    """
    db = db_manager.get_database(database)
    hyperedge = db.e(hyperedge_id)

    return hyperedge

def get_hyperedge_detail(vertices: list, database=None):
    """
    获取指定hyperedge的详细信息
    """
    try:
        db = db_manager.get_database(database)
        # 转换为tuple
        edge_tuple = db.encode_e(tuple(vertices))
        
        # 检查hyperedge是否存在
        if not db.has_e(edge_tuple):
            raise Exception(f"Hyperedge does not exist")
        
        # 获取hyperedge数据
        hyperedge_data = db.e(edge_tuple)
        
        return hyperedge_data
    except Exception as e:
        raise Exception(f"Failed to get hyperedge detail: {str(e)}")

def get_vertice_neighbor_inner(vertex_id: str, database=None):
    """
    获取指定vertex的neighbor

    todo: 查不到会报错 CLERGYMAN
    """
    try:
        db = db_manager.get_database(database)
        n = db.nbr_v(vertex_id)
    
        n.add(vertex_id)

        e = db.nbr_e_of_v(vertex_id)
    except Exception:
        # 如果报错，返回空列表
        n = []
        e = []

    return (n,e)

def get_vertice_neighbor(vertex_id: str, database=None):
    """
    获取指定vertex的neighbor

    todo: 查不到会报错 CLERGYMAN
    """
    n, e = get_vertice_neighbor_inner(vertex_id, database)

    return get_all_detail(n, e, database)


def get_all_detail(all_v, all_e, database=None):
    """
    获取所有详情
    """
    db = db_manager.get_database(database)
    # 循环遍历 all_v 每个元素 赋值为 db.v
    nodes = {}
    for v in all_v:
        nodes[v] = db.v(v)

    hyperedges = {}
    for e in all_e:
        data = db.e(e)
        # data的 keywords 赋值
        data['keywords'] = data['keywords'].replace("<SEP>", ",")
        hyperedges['|#|'.join(e)] = data

    return { "vertices": nodes , "edges": hyperedges }

def get_hyperedge_neighbor_server(hyperedge_id: str, database=None):
    """
    获取指定hyperedge的neighbor
    """
    nodes = hyperedge_id.split("|#|")
    print(hyperedge_id)
    vertices = set()
    hyperedges = set()
    for node in nodes:
        n, e = get_vertice_neighbor_inner(node, database)
        # 这里的 n 是一个集合
        # 这里的 e 是一个集合
        # vertexs 增加n
        # hyperedges 增加e
        vertices.update(n)
        hyperedges.update(e)

    return get_all_detail(vertices, hyperedges, database)

def add_vertex(vertex_id: str, vertex_data: dict, database=None):
    """
    添加新的vertex
    """
    try:
        db = db_manager.get_database(database)
        # 如果vertex已存在，抛出异常
        if db.has_v(vertex_id):
            raise Exception(f"Vertex '{vertex_id}' already exists")
        
        # 添加vertex
        db.add_v(vertex_id, vertex_data)
        
        # 保存到文件
        db.save(db.storage_file)
        
        # 清除缓存
        db._clear_cache()
        
        return db.v(vertex_id)
    except Exception as e:
        raise Exception(f"Failed to add vertex: {str(e)}")

def add_hyperedge(vertices: list, hyperedge_data: dict, database=None):
    """
    添加新的hyperedge
    """
    try:
        db = db_manager.get_database(database)
        # 检查所有vertices是否存在
        for vertex in vertices:
            if not db.has_v(vertex):
                raise Exception(f"Vertex '{vertex}' does not exist")
        
        # 转换为tuple
        edge_tuple = db.encode_e(tuple(vertices))
        
        # 如果hyperedge已存在，抛出异常
        if db.has_e(edge_tuple):
            raise Exception(f"Hyperedge already exists")
        
        # 添加hyperedge
        db.add_e(edge_tuple, hyperedge_data)
        
        # 保存到文件
        db.save(db.storage_file)
        
        # 清除缓存
        db._clear_cache()
        
        return db.e(edge_tuple)
    except Exception as e:
        raise Exception(f"Failed to add hyperedge: {str(e)}")

def update_vertex(vertex_id: str, vertex_data: dict, database=None):
    """
    更新vertex信息
    """
    try:
        db = db_manager.get_database(database)
        # 检查vertex是否存在
        if not db.has_v(vertex_id):
            raise Exception(f"Vertex '{vertex_id}' does not exist")
        
        # 获取现有数据
        existing_data = db.v(vertex_id)
        
        # 更新数据（只更新非空字段）
        for key, value in vertex_data.items():
            if value:  # 只更新非空值
                existing_data[key] = value
        
        # 移除旧的vertex并添加新的
        db.remove_v(vertex_id)
        db.add_v(vertex_id, existing_data)
        
        # 保存到文件
        db.save(db.storage_file)
        
        # 清除缓存
        db._clear_cache()
        
        return db.v(vertex_id)
    except Exception as e:
        raise Exception(f"Failed to update vertex: {str(e)}")

def update_hyperedge(vertices: list, hyperedge_data: dict, database=None):
    """
    更新hyperedge信息
    """
    try:
        db = db_manager.get_database(database)
        # 转换为tuple
        edge_tuple = db.encode_e(tuple(vertices))
        
        # 检查hyperedge是否存在
        if not db.has_e(edge_tuple):
            raise Exception(f"Hyperedge does not exist")
        
        # 获取现有数据
        existing_data = db.e(edge_tuple)
        
        # 更新数据（只更新非空字段）
        for key, value in hyperedge_data.items():
            if value:  # 只更新非空值
                existing_data[key] = value
        
        # 移除旧的hyperedge并添加新的
        db.remove_e(edge_tuple)
        db.add_e(edge_tuple, existing_data)
        
        # 保存到文件
        db.save(db.storage_file)
        
        # 清除缓存
        db._clear_cache()
        
        return db.e(edge_tuple)
    except Exception as e:
        raise Exception(f"Failed to update hyperedge: {str(e)}")

def delete_vertex(vertex_id: str, database=None):
    """
    删除vertex
    """
    try:
        db = db_manager.get_database(database)
        # 检查vertex是否存在
        if not db.has_v(vertex_id):
            raise Exception(f"Vertex '{vertex_id}' does not exist")
        
        # 删除vertex
        db.remove_v(vertex_id)
        
        # 保存到文件
        db.save(db.storage_file)
        
        # 清除缓存
        db._clear_cache()
        
        return True
    except Exception as e:
        raise Exception(f"Failed to delete vertex: {str(e)}")

def delete_hyperedge(vertices: list, database=None):
    """
    删除hyperedge
    """
    try:
        db = db_manager.get_database(database)
        # 转换为tuple
        edge_tuple = db.encode_e(tuple(vertices))
        
        # 检查hyperedge是否存在
        if not db.has_e(edge_tuple):
            raise Exception(f"Hyperedge does not exist")
        
        # 删除hyperedge
        db.remove_e(edge_tuple)
        
        # 保存到文件
        db.save(db.storage_file)
        
        # 清除缓存
        db._clear_cache()
        
        return True
    except Exception as e:
        raise Exception(f"Failed to delete hyperedge: {str(e)}")

# ========== 主题超图相关函数 ==========

def get_theme_hypergraph(database=None):
    """获取主题超图数据"""
    db = db_manager.get_theme_database(database)
    if db is None:
        return {"vertices": {}, "edges": {}, "error": "主题超图数据库不存在"}

    all_v = db.all_v
    all_e = db.all_e

    return get_theme_all_detail(all_v, all_e, database)

def get_theme_vertices(database=None, page=None, page_size=None):
    """获取主题超图的顶点列表"""
    db = db_manager.get_theme_database(database)
    if db is None:
        return {"data": [], "total": 0, "error": "主题超图数据库不存在"}

    all_v = list(db.all_v)

    # 如果没有分页参数，返回所有数据
    if page is None or page_size is None:
        return all_v

    # 计算分页
    total = len(all_v)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size

    # 获取分页数据
    page_data = all_v[start_idx:end_idx]

    return {
        'data': page_data,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': (total + page_size - 1) // page_size
    }

def get_theme_hyperedges(database=None, page=None, page_size=None):
    """获取主题超图的超边列表"""
    db = db_manager.get_theme_database(database)
    if db is None:
        return {"data": [], "total": 0, "error": "主题超图数据库不存在"}

    all_e = list(db.all_e)

    hyperedges = []
    for e in all_e:
        hyperedge_id = '|*|'.join(e)
        hyperedge_data = db.e(e)

        edge_info = {
            'id': hyperedge_id,
            'vertices': list(e),
            'keywords': hyperedge_data.get('keywords', ''),
            'description': hyperedge_data.get('description', ''),
            'weight': hyperedge_data.get('weight', 1.0)
        }
        hyperedges.append(edge_info)

    # 如果没有分页参数，返回所有数据
    if page is None or page_size is None:
        return hyperedges

    # 计算分页
    total = len(hyperedges)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size

    # 获取分页数据
    page_data = hyperedges[start_idx:end_idx]

    return {
        'data': page_data,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': (total + page_size - 1) // page_size
    }

def get_theme_vertex_neighbor(vertex_id: str, database=None):
    """获取主题超图中顶点的邻居"""
    db = db_manager.get_theme_database(database)
    if db is None:
        return {"vertices": {}, "edges": {}, "error": "主题超图数据库不存在"}

    n, e = get_theme_vertice_neighbor_inner(vertex_id, db)
    return get_theme_all_detail(n, e, database)

def get_theme_vertice_neighbor_inner(vertex_id: str, db):
    """获取主题超图中顶点的邻居（内部函数）"""
    try:
        n = db.nbr_v(vertex_id)
        n.add(vertex_id)
        e = db.nbr_e_of_v(vertex_id)
    except Exception:
        # 如果报错，返回空列表
        n = []
        e = []

    return (n, e)

def get_theme_all_detail(all_v, all_e, database=None):
    """获取主题超图的所有详情"""
    db = db_manager.get_theme_database(database)
    # 循环遍历 all_v 每个元素 赋值为 db.v
    nodes = {}
    for v in all_v:
        nodes[v] = db.v(v)

    hyperedges = {}
    for e in all_e:
        data = db.e(e)
        # data的 keywords 赋值
        data['keywords'] = data.get('keywords', '').replace("<SEP>", ",")
        hyperedges['|#|'.join(e)] = data

    return {"vertices": nodes, "edges": hyperedges}