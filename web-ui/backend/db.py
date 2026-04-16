from hyperdb import HypergraphDB
import os

class DatabaseManager:
    """数据库管理器，支持多个数据库实例和双系统"""
    def __init__(self):
        self.databases = {}
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

    def delete_database(self, database_name: str) -> dict:
        """
        删除指定数据库（支持HyperRAG和Cog-RAG双系统）

        Args:
            database_name: 数据库名称

        Returns:
            删除结果字典，包含各系统的删除状态
        """
        result = {
            "database": database_name,
            "hyperrag": {"success": False, "message": ""},
            "cograg": {"success": False, "message": ""}
        }

        # 删除HyperRAG数据库
        hyperrag_db_path = os.path.join(self.cache_dir, database_name)
        if os.path.exists(hyperrag_db_path):
            try:
                import shutil
                shutil.rmtree(hyperrag_db_path)
                result["hyperrag"]["success"] = True
                result["hyperrag"]["message"] = f"HyperRAG数据库 {database_name} 删除成功"
                print(f"已删除HyperRAG数据库: {hyperrag_db_path}")
            except Exception as e:
                result["hyperrag"]["message"] = f"HyperRAG数据库删除失败: {str(e)}"
                print(f"删除HyperRAG数据库失败: {e}")
        else:
            result["hyperrag"]["success"] = True
            result["hyperrag"]["message"] = "HyperRAG数据库不存在，跳过删除"

        # 删除Cog-RAG数据库
        cograg_db_path = os.path.join(self.cograg_cache_dir, database_name)
        if os.path.exists(cograg_db_path):
            try:
                import shutil
                shutil.rmtree(cograg_db_path)
                result["cograg"]["success"] = True
                result["cograg"]["message"] = f"Cog-RAG数据库 {database_name} 删除成功"
                print(f"已删除Cog-RAG数据库: {cograg_db_path}")
            except Exception as e:
                result["cograg"]["message"] = f"Cog-RAG数据库删除失败: {str(e)}"
                print(f"删除Cog-RAG数据库失败: {e}")
        else:
            result["cograg"]["success"] = True
            result["cograg"]["message"] = "Cog-RAG数据库不存在，跳过删除"

        # 清除内存中的数据库实例
        db_key_hyperrag = f"{database_name}_hyperrag"
        db_key_cograg = f"{database_name}_cograg"

        if db_key_hyperrag in self.databases:
            del self.databases[db_key_hyperrag]
            print(f"已清除数据库实例: {db_key_hyperrag}")

        if db_key_cograg in self.databases:
            del self.databases[db_key_cograg]
            print(f"已清除数据库实例: {db_key_cograg}")

        # 判断整体删除是否成功
        all_success = result["hyperrag"]["success"] and result["cograg"]["success"]
        result["success"] = all_success

        return result

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