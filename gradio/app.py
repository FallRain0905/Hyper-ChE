"""
Hyper-RAG Hypergraph Visualizer - Gradio with AntV G6
修复版：支持异步非阻塞处理、实时进度展示、多用户状态隔离
更新：添加日志捕获功能，实时显示处理日志
"""
import gradio as gr
from pathlib import Path
import json
import html as html_lib
from typing import Dict, List, Tuple
import sys
import importlib.util
import os
import asyncio
import logging
import shutil
from datetime import datetime
from queue import Queue
from threading import Thread

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import utils from streamlit directory
utils_path = project_root / "streamlit" / "utils.py"
spec = importlib.util.spec_from_file_location("utils", utils_path)
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)
load_hypergraph_data = utils.load_hypergraph_data

# ============================================
# 日志捕获处理器
# ============================================

class LogCaptureHandler(logging.Handler):
    """自定义日志处理器，将日志捕获到队列中"""
    def __init__(self, log_queue: Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        log_entry = {
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'level': record.levelname,
            'message': self.format(record),
            'logger': record.name
        }
        self.log_queue.put(log_entry)


# 全局日志队列，用于捕获所有日志
GLOBAL_LOG_QUEUE = Queue()

# 配置日志捕获
def setup_log_capture():
    """设置日志捕获"""
    # 获取 HyperRAG 相关的 logger
    loggers_to_capture = [
        'hyper_rag',
        'hyperrag',
        'openai',
        'httpx',
        'httpcore'
    ]

    for logger_name in loggers_to_capture:
        logger = logging.getLogger(logger_name)
        handler = LogCaptureHandler(GLOBAL_LOG_QUEUE)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)


# 初始化日志捕获
setup_log_capture()


# Import HyperRAG
try:
    from hyperrag import HyperRAG, QueryParam
    from hyperrag.utils import EmbeddingFunc
    from hyperrag.llm import openai_embedding, openai_complete_if_cache
    HYPERRAG_AVAILABLE = True
except ImportError as e:
    print(f"HyperRAG not available: {e}")
    HYPERRAG_AVAILABLE = False

# Cache directory for databases
CACHE_DIR = project_root / "web-ui" / "backend" / "hyperrag_cache"
SETTINGS_FILE = project_root / "web-ui" / "backend" / "settings.json"

# ============================================
# 颜色配置 - 与 Web-UI 完全一致
# ============================================

ENTITY_TYPE_COLORS = {
    'PERSON': '#00C9C9',
    'CONCEPT': '#a68fff',
    'ORGANIZATION': '#F08F56',
    'LOCATION': '#16f69c',
    'EVENT': '#004ac9',
    'PRODUCT': '#f056d1',
    'DEFAULT': '#8566CC'
}

BUBBLE_COLORS = [
    '#F6BD16',
    '#00C9C9',
    '#F08F56',
    '#D580FF',
    '#FF3D00',
    '#16f69c',
    '#004ac9',
    '#f056d1',
    '#a680ff',
    '#c8ff00'
]


# ============================================
# HyperRAG LLM 和 Embedding 函数
# ============================================

def load_settings():
    """加载系统设置"""
    settings_path = str(SETTINGS_FILE) if not isinstance(SETTINGS_FILE, str) else SETTINGS_FILE
    if os.path.exists(settings_path):
        with open(settings_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    # 默认设置
    return {
        "apiKey": "",
        "modelProvider": "openai",
        "modelName": "gpt-4o-mini",
        "baseUrl": "https://api.openai.com/v1",
        "embeddingModel": "text-embedding-3-small",
        "embeddingDim": 1536,
        "maxTokens": 2000,
        "temperature": 0.7
    }


async def get_hyperrag_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs) -> str:
    """HyperRAG 专用的 LLM 函数"""
    settings = load_settings()
    model_name = settings.get("modelName", "gpt-4o-mini")
    api_key = settings.get("apiKey")
    base_url = settings.get("baseUrl")

    response = await openai_complete_if_cache(
        model_name,
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )
    return response


async def get_hyperrag_embedding_func(texts: list) -> list:
    """HyperRAG 专用的嵌入函数"""
    settings = load_settings()
    embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
    # 优先使用独立的 embedding 配置
    api_key = settings.get("embeddingApiKey") or settings.get("apiKey")
    base_url = settings.get("embeddingBaseUrl") or settings.get("baseUrl")

    embeddings = await openai_embedding(
        texts,
        model=embedding_model,
        api_key=api_key,
        base_url=base_url,
    )
    return embeddings


# ============================================
# HyperRAG 实例管理
# ============================================

hyperrag_instances = {}
hyperrag_working_dir = "gradio_hyperrag_cache"


def get_or_create_hyperrag(database: str = "default"):
    """获取或创建指定数据库的 HyperRAG 实例"""
    global hyperrag_instances

    if not HYPERRAG_AVAILABLE:
        raise RuntimeError("HyperRAG is not available")

    if database is None:
        database = "default"

    if database not in hyperrag_instances:
        db_working_dir = os.path.join(hyperrag_working_dir, database)
        Path(db_working_dir).mkdir(parents=True, exist_ok=True)

        settings = load_settings()
        embedding_dim = settings.get("embeddingDim", 1536)

        hyperrag_instances[database] = HyperRAG(
            working_dir=db_working_dir,
            llm_model_func=get_hyperrag_llm_func,
            embedding_func=EmbeddingFunc(
                embedding_dim=embedding_dim,
                max_token_size=8192,
                func=get_hyperrag_embedding_func
            ),
        )

    return hyperrag_instances[database]


# ============================================
# 数据加载函数
# ============================================

def get_available_databases() -> List[str]:
    """获取可用的数据库列表（同时从两个目录扫描）"""
    databases = []

    # 1. 从 web-ui 缓存目录扫描
    if CACHE_DIR.exists():
        for d in CACHE_DIR.iterdir():
            if d.is_dir() and (d / "hypergraph_chunk_entity_relation.hgdb").exists():
                databases.append(d.name)

    # 2. 从 gradio 工作目录扫描（文档嵌入产生的临时数据库）
    gradio_cache = Path(hyperrag_working_dir)
    if gradio_cache.exists():
        for d in gradio_cache.iterdir():
            # 检查是否有 hypergraph 文件
            hgdb_files = list(d.glob("*.hgdb"))
            if hgdb_files:
                db_name = f"[文档] {d.name}"
                databases.append(db_name)

    return sorted(databases)


def get_available_databases_str() -> str:
    """获取数据库列表的字符串表示"""
    databases = get_available_databases()
    if not databases:
        return "暂无可用数据库"

    result = []
    for db in databases:
        result.append(f"  • {db}")
    return "\n".join(result)


def refresh_database_list() -> str:
    """刷新数据库列表"""
    return get_available_databases_str()


def delete_database(db_name: str) -> str:
    """删除指定的数据库"""
    if not db_name or not db_name.strip():
        return "请输入数据库名称"

    db_name = db_name.strip()
    db_path = None

    # 确定数据库路径
    if db_name.startswith("[文档] "):
        # 从 gradio 缓存目录删除
        real_name = db_name.replace("[文档] ", "")
        db_path = Path(hyperrag_working_dir) / real_name
    else:
        # 从 web-ui 缓存目录删除
        db_path = CACHE_DIR / db_name

    if not db_path.exists():
        return f"数据库不存在: {db_name}"

    try:
        # 删除整个目录
        shutil.rmtree(db_path)
        # 同时清除 HyperRAG 实例缓存
        if db_name.startswith("[文档] "):
            cache_key = db_name.replace("[文档] ", "")
        else:
            cache_key = db_name

        if cache_key in hyperrag_instances:
            del hyperrag_instances[cache_key]

        return f"已删除数据库: {db_name}"
    except Exception as e:
        return f"删除失败: {str(e)}"


def load_database(db_name: str) -> Dict:
    """加载指定的数据库"""
    if not db_name:
        return None

    # 检查是否是 gradio 临时数据库（格式：[文档] temp_xxx）
    if db_name.startswith("[文档] "):
        # 从 gradio 缓存目录加载
        real_name = db_name.replace("[文档] ", "")
        db_path = Path(hyperrag_working_dir) / real_name / "hypergraph_chunk_entity_relation.hgdb"
    else:
        # 从 web-ui 缓存目录加载
        db_path = CACHE_DIR / db_name / "hypergraph_chunk_entity_relation.hgdb"

    if not db_path.exists():
        return None

    vertices, hyperedges = load_hypergraph_data(db_path)

    return {
        'vertices': vertices,
        'hyperedges': hyperedges,
        'db_name': db_name
    }


# ============================================
# G6 + BubbleSets 配置生成
# ============================================

def create_g6_options(data: Dict, vertex_id: str = None, show_labels: bool = True) -> Dict:
    """生成 G6 配置选项"""
    vertices = data.get('vertices', {})
    hyperedges = data.get('hyperedges', {})

    # 构建节点数据
    nodes = []
    for v_id, v_data in vertices.items():
        entity_type = v_data.get('entity_type', 'DEFAULT')
        label = v_data.get('entity_name', v_id)

        if vertex_id and v_id == vertex_id:
            node_color = "#000000"
            node_size = 35
        else:
            node_color = ENTITY_TYPE_COLORS.get(entity_type, ENTITY_TYPE_COLORS['DEFAULT'])
            node_size = 25

        nodes.append({
            'id': v_id,
            'data': {
                'label': label,
                'entity_type': entity_type,
                'cluster': entity_type,
                'description': v_data.get('description', '')
            },
            'style': {
                'fill': node_color,
                'labelText': label,
                'size': node_size,
                'stroke': '#ffffff',
                'lineWidth': 1.5,
            }
        })

    # 构建超边插件
    plugins = []

    for idx, (edge_key, edge_data) in enumerate(hyperedges.items()):
        vertices_list = edge_data.get('vertices', [])
        members = [v for v in vertices_list if v in vertices]

        if len(members) < 2:
            continue

        bubble_color = BUBBLE_COLORS[idx % len(BUBBLE_COLORS)]
        keywords = edge_data.get('keywords', '')

        plugin_config = {
            'type': 'bubble-sets',
            'key': f'bubble-sets-{idx}',
            'members': members,
            'fill': bubble_color,
            'fillOpacity': 0.15,
            'stroke': bubble_color,
            'strokeOpacity': 0.8,
            'maxRoutingIterations': 100,
            'maxMarchingIterations': 20,
            'pixelGroup': 4,
            'edgeR0': 10,
            'edgeR1': 60,
            'nodeR0': 15,
            'nodeR1': 50,
            'morphBuffer': 10,
            'threshold': 4,
            'memberInfluenceFactor': 1,
            'edgeInfluenceFactor': 4,
            'nonMemberInfluenceFactor': -0.8,
            'virtualEdges': True
        }

        if show_labels and keywords:
            plugin_config['label'] = True
            plugin_config['labelText'] = keywords
            plugin_config['labelFill'] = '#fff'
            plugin_config['labelBackground'] = True
            plugin_config['labelBackgroundFill'] = bubble_color
            plugin_config['labelBackgroundRadius'] = 5

        plugins.append(plugin_config)

    options = {
        'autoFit': 'center',
        'data': {
            'nodes': nodes,
            'edges': []
        },
        'node': {
            'type': 'circle',
            'style': {
                'labelFill': '#333',
                'labelFontSize': 11,
                'labelPlacement': 'bottom',
                'labelOffsetY': 4,
            }
        },
        'edge': {
            'style': {
                'size': 2
            }
        },
        'animate': False,
        'autoResize': True,
        'behaviors': [
            'zoom-canvas',
            'drag-canvas',
            'drag-element'
        ],
        'layout': {
            'type': 'force-atlas2',
            'preventOverlap': True,
            'kr': 80,
            'gravity': 20,
            'linkDistance': 10,
        },
        'plugins': plugins
    }

    return options


# ============================================
# HTML 生成函数
# ============================================

def create_full_graph_page(options: Dict, vertices_count: int, hyperedges_count: int) -> str:
    """创建完整超图页面"""
    options_json = json.dumps(options, ensure_ascii=False)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Full Hypergraph</title>
    <script src="https://cdn.jsdelivr.net/npm/@antv/g6@5/dist/g6.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ width: 100%; height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
        #g6-container {{ width: 100%; height: 100vh; background: #ffffff; }}
        #stats-bar {{
            position: fixed;
            top: 20px;
            left: 20px;
            background: rgba(255,255,255,0.95);
            padding: 12px 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            z-index: 1000;
            font-size: 14px;
        }}
        #loading {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: #999; font-size: 18px; }}
        #error {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; color: #ff4d4f; padding: 20px; max-width: 80%; background: white; border-radius: 8px; }}
        .stat-item {{ display: inline-block; margin-right: 20px; }}
        .stat-label {{ color: #666; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .stat-value {{ font-weight: 600; color: #333; font-size: 18px; }}
    </style>
</head>
<body>
    <div id="stats-bar">
        <span class="stat-item">
            <span class="stat-label">Vertices</span>
            <span class="stat-value">{vertices_count}</span>
        </span>
        <span class="stat-item">
            <span class="stat-label">Hyperedges</span>
            <span class="stat-value">{hyperedges_count}</span>
        </span>
    </div>
    <div id="g6-container"><div id="loading">加载中...</div></div>

    <script>
    (function() {{
        console.log("=== G6 Full Hypergraph START ===");
        var options = {options_json};
        console.log("Options:", options);

        function initGraph() {{
            if (typeof G6 === "undefined") {{
                console.error("G6 not loaded");
                document.getElementById("loading").innerHTML = "<span style='color:red'>G6 加载失败</span>";
                return;
            }}

            if (typeof G6.Graph === "undefined") return;

            console.log("G6 ready!");
            var container = document.getElementById("g6-container");

            try {{
                var graph = new G6.Graph({{
                    container: "g6-container",
                    width: window.innerWidth,
                    height: window.innerHeight,
                    ...options
                }});

                graph.render();
                console.log("Graph rendered!");

                var loading = document.getElementById("loading");
                if (loading) loading.style.display = "none";

                window.addEventListener("resize", function() {{
                    graph.changeSize(window.innerWidth, window.innerHeight);
                }});

            }} catch (e) {{
                console.error("Error:", e);
                container.innerHTML = '<div id="error"><h3>初始化失败</h3><p>' + e.message + '</p></div>';
            }}
        }}

        var retries = 0;
        var checkG6 = setInterval(function() {{
            if (typeof G6 !== "undefined") {{
                clearInterval(checkG6);
                initGraph();
            }} else if (retries >= 20) {{
                clearInterval(checkG6);
                console.error("G6 not loaded after 20 retries");
                document.getElementById("loading").innerHTML = "<span style='color:red'>G6 加载超时</span>";
            }}
            retries++;
        }}, 500);
    }})();
    </script>
</body>
</html>'''
    return html


def create_vertex_details_page(vertex_id: str, vertices: Dict, hyperedges: Dict, show_labels: bool) -> str:
    """创建顶点详情页面"""
    vertex = vertices.get(vertex_id)
    if not vertex:
        return "<div style='padding: 20px; text-align: center; color: #999;'>顶点不存在</div>"

    related_hyperedges = []
    related_vertices = {vertex_id}

    for idx, (edge_key, edge_data) in enumerate(hyperedges.items()):
        vertices_list = edge_data.get('vertices', [])
        if vertex_id in vertices_list:
            related_hyperedges.append({
                'id': idx,
                'key': edge_key,
                'members': vertices_list,
                'keywords': edge_data.get('keywords', ''),
                'summary': edge_data.get('summary', ''),
                'color': BUBBLE_COLORS[idx % len(BUBBLE_COLORS)]
            })
            related_vertices.update(vertices_list)

    sub_vertices = {}
    sub_hyperedges = {}

    for v_id in related_vertices:
        if v_id in vertices:
            sub_vertices[v_id] = vertices[v_id]

    for he in related_hyperedges:
        valid_members = [v for v in he['members'] if v in sub_vertices]
        if len(valid_members) >= 2:
            sub_hyperedges[he['key']] = {
                'vertices': valid_members,
                'keywords': he['keywords'],
                'summary': he['summary']
            }

    entity_type = vertex.get('entity_type', 'DEFAULT')
    entity_color = ENTITY_TYPE_COLORS.get(entity_type, ENTITY_TYPE_COLORS['DEFAULT'])
    description = vertex.get('description', '').replace('<SEP>', ' | ')

    data = {'vertices': sub_vertices, 'hyperedges': sub_hyperedges}
    options = create_g6_options(data, vertex_id, show_labels)
    options_json = json.dumps(options, ensure_ascii=False)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vertex Details - {vertex.get('entity_name', vertex_id)}</title>
    <script src="https://cdn.jsdelivr.net/npm/@antv/g6@5/dist/g6.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        .container {{ display: flex; height: 100vh; }}
        .graph-panel {{ flex: 1; position: relative; overflow: hidden; }}
        .info-panel {{
            width: 320px;
            background: #ffffff;
            border-left: 1px solid #e8e8e8;
            display: flex;
            flex-direction: column;
            box-shadow: -2px 0 8px rgba(0,0,0,0.05);
            z-index: 100;
        }}
        #g6-container {{ width: 100%; height: 100%; background: #f5f7fa; }}
        #loading {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: #999; font-size: 16px; }}
        #error {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; color: #ff4d4f; padding: 20px; }}

        .info-header {{ padding: 20px; border-bottom: 1px solid #e8e8e8; }}
        .info-title {{ font-size: 16px; font-weight: 600; color: #333; margin-bottom: 8px; }}
        .info-meta {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .info-tag {{ padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 500; }}
        .info-content {{ padding: 20px; overflow-y: auto; flex: 1; }}
        .info-section {{ margin-bottom: 24px; }}
        .info-section-title {{ font-size: 13px; font-weight: 600; color: #666; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }}
        .info-text {{ font-size: 14px; color: #333; line-height: 1.6; }}
        .hyperedge-list {{ display: flex; flex-direction: column; gap: 8px; }}
        .hyperedge-item {{ padding: 12px; border-radius: 6px; border-left: 4px solid #ddd; background: #fafafa; }}
        .hyperedge-keywords {{ font-weight: 500; color: #333; margin-bottom: 4px; }}
        .hyperedge-members {{ font-size: 12px; color: #999; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="graph-panel">
            <div id="g6-container"><div id="loading">加载中...</div></div>
        </div>
        <div class="info-panel">
            <div class="info-header">
                <div class="info-title">{vertex_id}</div>
                <div class="info-meta">
                    <span class="info-tag" style="background: {entity_color}; color: white;">{entity_type}</span>
                </div>
            </div>
            <div class="info-content">
                <div class="info-section">
                    <div class="info-section-title">Description</div>
                    <div class="info-text">{description or "No description available"}</div>
                </div>
                <div class="info-section">
                    <div class="info-section-title">Related Hyperedges ({len(related_hyperedges)})</div>
                    <div class="hyperedge-list">
                        {"".join([
                            f'<div class="hyperedge-item" style="border-left-color: {he["color"]};"><div class="hyperedge-keywords">{he["keywords"] or "Hyperedge " + str(he["id"]+1)}</div><div class="hyperedge-members">{len(he["members"])} members</div></div>'
                            for he in related_hyperedges
                        ])}
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
    (function() {{
        console.log("=== G6 Vertex Details START ===");
        var options = {options_json};

        function initGraph() {{
            if (typeof G6 === "undefined") {{
                console.error("G6 not loaded");
                document.getElementById("loading").innerHTML = "<span style='color:red'>G6 加载失败</span>";
                return;
            }}

            if (typeof G6.Graph === "undefined") return;

            console.log("G6 ready!");
            var container = document.getElementById("g6-container");

            try {{
                var graph = new G6.Graph({{
                    container: "g6-container",
                    width: container.clientWidth,
                    height: container.clientHeight,
                    ...options
                }});

                graph.render();
                console.log("Graph rendered!");

                var loading = document.getElementById("loading");
                if (loading) loading.style.display = "none";

                window.addEventListener("resize", function() {{
                    if (container && graph) {{
                        graph.changeSize(container.clientWidth, container.clientHeight);
                    }}
                }});

            }} catch (e) {{
                console.error("Error:", e);
                container.innerHTML = '<div id="error"><h3>初始化失败</h3><p>' + e.message + '</p></div>';
            }}
        }}

        var retries = 0;
        var checkG6 = setInterval(function() {{
            if (typeof G6 !== "undefined") {{
                clearInterval(checkG6);
                initGraph();
            }} else if (retries >= 20) {{
                clearInterval(checkG6);
                console.error("G6 not loaded after 20 retries");
                document.getElementById("loading").innerHTML = "<span style='color:red'>G6 加载超时</span>";
            }}
            retries++;
        }}, 500);
    }})();
    </script>
</body>
</html>'''
    return html


# ============================================
# 文档处理类 - 重构核心状态管理
# ============================================

class DocumentProcessor:
    """文档处理流程 - 使用真实的 HyperRAG"""

    def __init__(self):
        self.reset()

    def reset(self):
        """重置状态（包括删除临时数据库）"""
        # 删除当前文档的临时数据库
        if hasattr(self, 'current_doc') and self.current_doc:
            temp_db_name = f"temp_{self.current_doc}"
            temp_db_path = Path(hyperrag_working_dir) / temp_db_name
            if temp_db_path.exists():
                try:
                    shutil.rmtree(temp_db_path)
                except Exception as e:
                    print(f"删除临时数据库失败: {e}")
            # 清除 HyperRAG 实例缓存
            if temp_db_name in hyperrag_instances:
                del hyperrag_instances[temp_db_name]

        self.documents = []
        self.current_doc = None
        self.status = "pending"
        self.processing_logs = []
        self.capture_logs = True  # 是否捕获日志

    def add_log(self, message: str, level: str = "INFO"):
        """添加处理日志"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.processing_logs.append(f"[{timestamp}] [{level}] {message}")

    def upload_document(self, file_obj) -> Tuple[str, str]:
        """上传文档（支持 txt, md, pdf, docx）"""
        try:
            if file_obj is None:
                return None, "未选择文件"

            # 获取文件名
            if hasattr(file_obj, 'name'):
                file_name = getattr(file_obj, 'name', 'unknown.txt').split('/')[-1].split('\\')[-1]
            else:
                file_name = 'uploaded_file.txt'

            # 根据文件扩展名处理内容
            file_ext = Path(file_name).suffix.lower()

            if file_ext == '.docx':
                # 处理 .docx 文件
                if hasattr(file_obj, 'read'):
                    raw_content = file_obj.read()
                    # 使用 python-docx 提取文本
                    try:
                        from docx import Document as DocxDocument
                        # 保存临时文件
                        import tempfile
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as tmp:
                            tmp.write(raw_content)
                            tmp_path = tmp.name

                        # 读取 docx 内容
                        doc = DocxDocument(tmp_path)
                        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                        content = '\n\n'.join(paragraphs)

                        # 删除临时文件
                        os.unlink(tmp_path)
                    except ImportError:
                        # python-docx 未安装
                        return None, "需要安装 python-docx 库来处理 .docx 文件 (pip install python-docx)"
                    except Exception as e:
                        return None, f"解析 .docx 文件失败: {str(e)}"
                else:
                    return None, "无法读取文件内容"
            elif hasattr(file_obj, 'read'):
                # 处理其他文本格式，尝试多种编码
                raw_content = file_obj.read()
                if isinstance(raw_content, bytes):
                    # 尝试多种编码
                    encodings = ['utf-8', 'gbk', 'gb2312', 'big5', 'latin1']
                    content = None
                    for enc in encodings:
                        try:
                            content = raw_content.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                    if content is None:
                        return None, f"无法解码文件，尝试的编码: {', '.join(encodings)}"
                else:
                    content = raw_content
            elif isinstance(file_obj, bytes):
                # 尝试多种编码
                encodings = ['utf-8', 'gbk', 'gb2312', 'big5', 'latin1']
                content = None
                for enc in encodings:
                    try:
                        content = file_obj.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                if content is None:
                    return None, f"无法解码文件，尝试的编码: {', '.join(encodings)}"
            else:
                content = str(file_obj)

            # 使用时间戳确保每次上传都有唯一的 ID
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            doc_id = f"doc_{timestamp}"
            char_count = len(content)
            estimated_tokens = int(char_count * 0.75)

            self.processing_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 上传文档: {file_name}")
            self.processing_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 📄 文档大小: {char_count} 字符, ~{estimated_tokens} tokens")

            self.documents.append({
                "id": doc_id,
                "name": file_name,
                "size": len(content),
                "content": content,
                "status": "uploaded",
                "chunks": [],
                "entities": [],
                "hyperedges_data": {}
            })
            self.current_doc = doc_id
            self.status = "uploaded"
            return doc_id, f"已上传: {file_name} ({char_count} 字符)"
        except Exception as e:
            return None, f"上传失败: {str(e)}"

    def get_document_html(self, doc_id: str = None) -> str:
        """生成文档处理 HTML"""
        doc = next((d for d in self.documents if d["id"] == (doc_id or self.current_doc)), None)
        if not doc:
            return '<div style="padding: 40px; text-align: center; color: #999;">请先上传文档</div>'

        status_colors = {
            'pending': '#d9d9d9',
            'processing': '#faad14',
            'embedding': '#52c41a',
            'extracting': '#13c2c2',
            'done': '#389e0d',
            'uploaded': '#1890ff',
            'chunked': '#52c41a',
            'completed': '#389e0d',
            'error': '#ff4d4f'
        }

        status_color = status_colors.get(doc["status"], status_colors["pending"])

        # 生成顶点列表 HTML
        vertices_html = ''
        vertices = doc.get('vertices', {})
        if vertices:
            vertices_html = '<div class="vertices-list"><h4>提取的顶点 ({len(vertices)} 个)</h4>'
            for v_id, v_data in vertices.items():
                entity_type = v_data.get('entity_type', 'UNKNOWN')
                entity_color = ENTITY_TYPE_COLORS.get(entity_type, ENTITY_TYPE_COLORS['DEFAULT'])
                description = v_data.get('description', '')[:100]
                vertices_html += f'''
            <div class="entity-item">
                <span class="entity-badge" style="background: {entity_color};">{entity_type}</span>
                <span class="entity-name">{v_id}</span>
                <div class="entity-desc">{description}...</div>
            </div>'''
            vertices_html += '</div>'

        # 生成超边列表 HTML
        hyperedges_html = ''
        hyperedges = doc.get('hyperedges_data', {})
        if hyperedges:
            hyperedges_html = '<div class="hyperedges-list"><h4>构建的超边 ({len(hyperedges)} 条)</h4>'
            for he_id, he_data in hyperedges.items():
                vertices_list = he_data.get('vertices', [])
                keywords = he_data.get('keywords', '')
                description = he_data.get('description', '')[:80]
                vertices_str = ", ".join(vertices_list)
                hyperedges_html += f'''
            <div class="hyperedge-item">
                <div class="hyperedge-content">
                    <strong>顶点:</strong> {vertices_str}<br>
                    <strong>关键词:</strong> {keywords}<br>
                    <strong>描述:</strong> {description}...
                </div>
            </div>'''
            hyperedges_html += '</div>'

        # 统计信息
        stats_html = ''
        if vertices or hyperedges:
            stats_html = f'''
            <div class="stats-box">
                <h4>📊 处理统计</h4>
                <div class="stats-grid">
                    <div class="stat-item">
                        <div class="stat-value">{len(vertices)}</div>
                        <div class="stat-label">顶点数</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value">{len(hyperedges)}</div>
                        <div class="stat-label">超边数</div>
                    </div>
                </div>
            </div>'''

        # 处理日志 - 捕获所有系统日志
        logs_html = '<div class="logs-box"><h4>📋 处理日志</h4>'

        # 添加处理状态日志
        for log in self.processing_logs:
            logs_html += f'<div class="log-item">{log}</div>'

        # 捕获全局日志队列中的新日志
        while not GLOBAL_LOG_QUEUE.empty():
            log_entry = GLOBAL_LOG_QUEUE.get()
            # 过滤掉一些不需要的日志
            if log_entry['logger'] in ['httpx', 'httpcore']:
                if 'HTTP Request' in log_entry['message']:
                    # 简化 HTTP 请求日志
                    if '200 OK' in log_entry['message']:
                        continue  # 跳过成功的请求日志
            logs_html += f'<div class="log-item log-{log_entry["level"].lower()}">[{log_entry["timestamp"]}] {log_entry["message"]}</div>'

        logs_html += '</div>'

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Document Processing - Hyper-RAG</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fa; }}
        .container {{ display: flex; height: 100vh; }}
        .main-panel {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; }}
        .side-panel {{ width: 400px; background: #fff; border-right: 1px solid #e8e8e8; padding: 20px; overflow-y: auto; }}
        .vertices-list {{ margin-top: 20px; }}
        .entity-item {{
            padding: 10px;
            border-radius: 6px;
            background: #fafafa;
            margin-bottom: 8px;
            border-left: 3px solid #ddd;
        }}
        .entity-badge {{
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 500;
            color: #fff;
            margin-right: 8px;
        }}
        .entity-name {{ font-weight: 600; color: #333; }}
        .entity-desc {{ font-size: 12px; color: #999; margin-top: 4px; }}
        .hyperedges-list {{ margin-top: 20px; }}
        .hyperedge-item {{
            padding: 12px;
            border-radius: 6px;
            background: #f6ffed;
            margin-bottom: 8px;
            border-left: 3px solid #52c41a;
        }}
        .hyperedge-content {{ font-size: 12px; color: #333; }}
        .stats-box {{
            margin-top: 20px;
            padding: 16px;
            background: #f5f7fa;
            border-radius: 8px;
        }}
        .stats-box h4 {{ margin: 0 0 12px 0; font-size: 14px; color: #333; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }}
        .stat-item {{
            text-align: center;
            padding: 12px;
            background: white;
            border-radius: 6px;
        }}
        .stat-value {{ font-size: 20px; font-weight: 600; color: #1890ff; }}
        .stat-label {{ font-size: 12px; color: #666; margin-top: 4px; }}
        .logs-box {{ margin-top: 20px; }}
        .logs-box h4 {{ margin: 0 0 12px 0; font-size: 14px; color: #333; }}
        .log-item {{
            padding: 6px 10px;
            background: #f5f5f5;
            border-radius: 4px;
            margin-bottom: 4px;
            font-size: 11px;
            color: #333;
            font-family: 'Courier New', monospace;
            white-space: pre-wrap;
            word-break: break-all;
        }}
        .log-info {{ border-left: 3px solid #1890ff; }}
        .log-warning {{ border-left: 3px solid #faad14; background: #fffbe6; }}
        .log-error {{ border-left: 3px solid #ff4d4f; background: #fff1f0; }}
        .hint {{ margin-top: 20px; padding: 16px; background: #e6f7ff; border-radius: 8px; font-size: 13px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="side-panel">
            <h3 style="margin-top:0;">📄 文档处理</h3>
            <div style="margin-top: auto; padding: 16px; background: #fffbe6; border-radius: 8px;">
                <strong>当前状态:</strong> <span class="status-badge" style="background: {status_color}; color: white; padding: 4px 8px; border-radius: 4px;">{doc["status"]}</span>
            </div>
            {stats_html}
            {logs_html}
            <div class="hint">
                💡 使用 HyperRAG 真实处理: 调用 LLM 进行实体提取
            </div>
        </div>
        <div class="main-panel" style="background: white;">
            <h2 style="padding: 20px; border-bottom: 1px solid #e8e8e8; margin: 0;">{doc["name"]}</h2>
            <div style="padding: 20px; overflow-y: auto; flex: 1;">
                {vertices_html}
                {hyperedges_html}
            </div>
        </div>
    </div>
</body>
</html>'''
        return html


# ============================================
# Gradio 应用与异步调度
# ============================================

with gr.Blocks(title="Hyper-RAG Hypergraph Visualizer") as demo:
    # 【核心修复】：为每个会话创建一个独立的处理状态，避免多用户冲突
    user_session = gr.State(lambda: DocumentProcessor())

    gr.Markdown("""
    # 🔷 Hyper-RAG Hypergraph Visualizer

    使用 **AntV G6 BubbleSets** 的超图可视化工具 - 完全复刻 Web-UI 效果

    - G6 v5 (CDN 加载)
    - BubbleSets 插件用于超边可视化
    - iframe srcdoc 解决 Gradio script 标签问题
    - **更新：文档嵌入模式** - 使用真实 HyperRAG LLM 处理
    - **更新：异步非阻塞处理** - 避免界面假死
    - **更新：多用户状态隔离** - 每个用户独立会话
    - **更新：实时日志捕获** - 显示详细处理日志
    """)

    with gr.Tabs():
        # --- Tab 1: 超图视图 ---
        with gr.Tab("📊 超图视图"):
            # 数据库管理折叠面板
            with gr.Accordion("🗂️ 数据库管理", open=False):
                with gr.Row():
                    with gr.Column(scale=2):
                        db_list_display = gr.Textbox(
                            label="可用数据库",
                            value=get_available_databases_str(),
                            lines=6,
                            interactive=False
                        )
                    with gr.Column(scale=1):
                        refresh_db_btn = gr.Button("🔄 刷新列表", size="sm")
                        delete_db_btn = gr.Button("🗑️ 删除选中数据库", variant="stop", size="sm")
                        db_name_input = gr.Textbox(
                            label="要删除的数据库名称",
                            placeholder="输入 [文档] temp_xxx 或 Glyci",
                            interactive=True
                        )
                        db_status = gr.Textbox(label="操作状态", value="", interactive=False)

            with gr.Row():
                with gr.Column(scale=1, min_width=250):
                    db_list = get_available_databases()
                    with gr.Row():
                        db_selector = gr.Dropdown(
                            choices=db_list,
                            label="📁 选择数据库",
                            value=None if not db_list else db_list[0],
                            info="选择要可视化的超图数据库",
                            scale=4
                        )
                        refresh_dropdown_btn = gr.Button("🔄", size="sm", scale=1)

                    page_mode = gr.Radio(
                        choices=["Vertex Details", "Full Hypergraph"],
                        value="Vertex Details",
                        label="📊 显示模式",
                        info="Vertex Details: 查看单个顶点的邻居; Full Hypergraph: 显示整个超图"
                    )

                    vertex_selector = gr.Dropdown(
                        choices=[],
                        label="🔍 选择顶点",
                        value=None,
                        info="选择要查看详情的顶点 (仅 Vertex Details 模式)"
                    )

                    show_labels = gr.Checkbox(
                        value=True,
                        label="🏷️ 显示超边标签",
                        info="在气泡上显示关键词"
                    )

                    load_btn = gr.Button("🚀 加载超图", variant="primary", size="lg")

                    status_info = gr.Textbox(
                        label="状态",
                        value="就绪",
                        interactive=False
                    )

                with gr.Column(scale=5):
                    output_html = gr.HTML(
                        value='<div style="display:flex;align-items:center;justify-content:center;height:400px;color:#999;border:2px dashed #d9d9d9;border-radius:8px;background:#fafafa;">请选择数据库并点击加载按钮</div>'
                    )

            def update_vertex_list(db_name: str):
                if not db_name:
                    return gr.Dropdown(choices=[], value=None)
                data = load_database(db_name)
                if not data:
                    return gr.Dropdown(choices=[], value=None)
                vertices = list(data['vertices'].keys())
                vertices.sort()
                return gr.Dropdown(choices=vertices, value=vertices[0] if vertices else None)

            def load_graph(db_name: str, page_mode: str, vertex_id: str, show_lbl: bool):
                if not db_name:
                    return gr.HTML(value='<div style="padding:40px;text-align:center;color:#ff4d4f;">请先选择数据库</div>'), "错误: 未选择数据库"

                data = load_database(db_name)
                if not data:
                    return gr.HTML(value=f'<div style="padding:40px;text-align:center;color:#ff4d4f;">加载数据库失败: {db_name}</div>'), f"错误: 加载数据库失败 {db_name}"

                vertices = data['vertices']
                hyperedges = data['hyperedges']
                v_count = len(vertices)
                he_count = len(hyperedges)

                if page_mode == "Full Hypergraph":
                    inner_html = create_full_graph_page(
                        create_g6_options(data, None, show_lbl),
                        v_count,
                        he_count
                    )
                    status = f"已加载: {db_name} (完整超图: {v_count} 顶点, {he_count} 超边)"
                    height = "900px"
                else:
                    if not vertex_id:
                        return gr.HTML(value='<div style="padding:40px;text-align:center;color:#ff4d4f;">请先选择顶点</div>'), "错误: 未选择顶点"

                    inner_html = create_vertex_details_page(vertex_id, vertices, hyperedges, show_lbl)
                    status = f"已加载: {db_name} - {vertex_id} 的详情"
                    height = "900px"

                safe_html = html_lib.escape(inner_html)
                iframe_html = f'''<iframe style="width: 100%; height: {height}; border: none; border-radius: 8px;" srcdoc="{safe_html}" sandbox="allow-scripts allow-same-origin"></iframe>'''

                return gr.HTML(value=iframe_html), status

            db_selector.change(update_vertex_list, inputs=[db_selector], outputs=[vertex_selector])

            # 刷新下拉列表按钮
            refresh_dropdown_btn.click(
                lambda: gr.Dropdown(choices=get_available_databases()),
                inputs=[],
                outputs=[db_selector]
            )
            page_mode.change(
                fn=lambda pm: gr.Textbox(
                    value="Vertex Details: 需要选择顶点 | Full Hypergraph: 显示所有顶点" if pm == "Vertex Details" else "显示完整超图"
                ),
                inputs=[page_mode],
                outputs=[status_info]
            )

            load_btn.click(
                load_graph,
                inputs=[db_selector, page_mode, vertex_selector, show_labels],
                outputs=[output_html, status_info]
            )

            # 数据库管理按钮绑定
            refresh_db_btn.click(
                lambda: (get_available_databases_str(), gr.Dropdown(choices=get_available_databases())),
                inputs=[],
                outputs=[db_list_display, db_selector]
            )

            def delete_and_refresh(db_name: str):
                msg = delete_database(db_name)
                return msg, get_available_databases_str(), gr.Dropdown(choices=get_available_databases())

            delete_db_btn.click(
                delete_and_refresh,
                inputs=[db_name_input],
                outputs=[db_status, db_list_display, db_selector]
            )

        # --- Tab 2: 文档模式 (全新异步架构) ---
        with gr.Tab("📄 文档模式"):
            gr.Markdown("""
            ### 📄 文档嵌入处理

            此模式展示文档如何被 HyperRAG 处理为超图数据的过程：

            **处理流程**:
            1. 📤 文档上传
            2. ✂️ 文本分块 (Chunking - 1200 tokens/块, 100 tokens 重叠)
            3. 📊 向量化 (Embedding)
            4. 🏷️ 实体抽取 (Entity Extraction - **调用 LLM**)
            5. 🔗 存入超图数据库

            **使用真实的 HyperRAG 处理**，包括：
            - 调用 LLM 进行智能实体提取
            - 实体描述摘要
            - 超边关键词提取
            - 向量嵌入

            *上传一个文档开始体验吧！*
            """)

            with gr.Row():
                with gr.Column(scale=1):
                    file_upload = gr.File(
                        label="📤 上传文档",
                        file_types=[".txt", ".md", ".pdf", ".docx"],
                        type="binary"
                    )

                    process_btn = gr.Button("▶️ 开始处理", variant="primary", size="lg")

                    reset_btn = gr.Button("🔄 重置", variant="secondary")

                    save_btn = gr.Button("💾 保存到正式数据库", variant="secondary", visible=False)

                    status_display = gr.Textbox(
                        label="处理状态",
                        value="等待上传文档...",
                        interactive=False
                    )

                with gr.Column(scale=4):
                    doc_output = gr.HTML(
                        value='<div style="display:flex;align-items:center;justify-content:center;height:400px;color:#999;border:2px dashed #d9d9d9;border-radius:8px;background:#fafafa;">请上传文档并点击"开始处理"</div>'
                    )

            # 【核心修复】：完全异步的生成器函数，防止界面假死
            async def process_document_async(file_obj, processor):
                if file_obj is None:
                    yield processor.get_document_html(), "未选择文档", processor, gr.update(visible=False)
                    return

                # 1. 执行上传并更新界面
                doc_id, msg = processor.upload_document(file_obj)
                if not doc_id:
                    yield processor.get_document_html(), msg, processor, gr.update(visible=False)
                    return

                # 第一次 yield：告诉界面已经上传成功，准备开始
                yield processor.get_document_html(doc_id), "文件上传成功，正在初始化 RAG...", processor, gr.update(visible=False)

                if not HYPERRAG_AVAILABLE:
                    processor.processing_logs.append("❌ 错误：HyperRAG 模块未正确导入")
                    processor.status = "error"
                    yield processor.get_document_html(doc_id), "HyperRAG 不可用", processor, gr.update(visible=False)
                    return

                doc = next((d for d in processor.documents if d["id"] == doc_id), None)

                # 2. 开始处理并更新界面
                processor.add_log("开始 HyperRAG 处理...")
                processor.status = "processing"

                try:
                    # 获取 RAG 实例
                    temp_db_name = f"temp_{doc_id}"
                    rag = get_or_create_hyperrag(temp_db_name)

                    # 清空全局日志队列（避免显示旧日志）
                    while not GLOBAL_LOG_QUEUE.empty():
                        GLOBAL_LOG_QUEUE.get()

                    # 创建后台任务来处理文档
                    processing_complete = False
                    processing_error = None

                    async def process_in_background():
                        nonlocal processing_complete, processing_error
                        try:
                            await rag.ainsert(doc['content'])
                            processing_complete = True
                        except Exception as e:
                            processing_error = str(e)
                            processing_complete = True

                    # 启动后台任务
                    bg_task = asyncio.create_task(process_in_background())

                    # 持续监控日志并 yield 更新
                    last_log_count = 0
                    no_new_logs_count = 0

                    while not processing_complete:
                        # 捕获新日志
                        new_logs = []
                        while not GLOBAL_LOG_QUEUE.empty():
                            log_entry = GLOBAL_LOG_QUEUE.get()
                            # 过滤掉 HTTP 请求日志
                            message = log_entry.get('message', '')
                            if not ('HTTP Request' in message and '200 OK' in message):
                                # 简化一些日志
                                simplified_msg = message
                                if '|████' in message or '|' in message and '%' in message:
                                    # 这是进度条日志
                                    new_logs.append({
                                        'timestamp': log_entry['timestamp'],
                                        'level': log_entry['level'],
                                        'message': simplified_msg,
                                        'is_progress': True
                                    })
                                else:
                                    new_logs.append({
                                        'timestamp': log_entry['timestamp'],
                                        'level': log_entry['level'],
                                        'message': simplified_msg,
                                        'is_progress': False
                                    })

                        # 添加新日志到处理器
                        for log in new_logs:
                            if log['is_progress']:
                                processor.processing_logs.append(f"[{log['timestamp']}] {log['message']}")
                            else:
                                # 过滤一些不需要的日志
                                msg = log['message']
                                if any(kw in msg for kw in ['Load KV full_docs', 'Load KV text_chunks', 'Load KV llm_response_cache',
                                                            'Inserting', 'Loaded hypergraph from', 'Logger initialized',
                                                            'Writing hypergraph']):
                                    processor.processing_logs.append(f"[{log['timestamp']}] {msg}")

                        # yield 更新
                        if new_logs:
                            no_new_logs_count = 0
                            yield processor.get_document_html(doc_id), f"处理中... (已捕获 {len(processor.processing_logs)} 条日志)", processor, gr.update(visible=False)
                        else:
                            no_new_logs_count += 1
                            # 每 5 次检查也 yield 一次，保持连接活跃
                            if no_new_logs_count >= 5:
                                yield processor.get_document_html(doc_id), f"处理中... (等待新日志)", processor, gr.update(visible=False)
                                no_new_logs_count = 0

                        # 短暂等待，避免 CPU 占用过高
                        await asyncio.sleep(0.3)

                    # 等待后台任务完成
                    await bg_task

                    # 检查是否有错误
                    if processing_error:
                        processor.add_log(f"❌ 处理失败: {processing_error}")
                        doc["status"] = "error"
                        processor.status = "error"
                        yield processor.get_document_html(doc_id), f"处理发生错误: {processing_error}", processor, gr.update(visible=False)
                        return

                    # 获取处理后的数据
                    hg = rag.chunk_entity_relation_hypergraph._hg
                    vertices_ids = hg.all_v
                    hyperedge_tuples = hg.all_e

                    # 构建顶点字典
                    vertices_data = {}
                    for v_id in vertices_ids:
                        vertices_data[v_id] = hg.v(v_id)

                    # 构建超边字典
                    hyperedges_data = {}
                    for e_tuple in hyperedge_tuples:
                        e_data = hg.e(e_tuple)
                        if e_data:
                            # 将元组转换为字符串作为键
                            edge_key = "|#|".join(e_tuple)
                            # 处理 keywords 中的 SEP 分隔符
                            if 'keywords' in e_data:
                                e_data = dict(e_data)  # 创建副本
                                e_data['keywords'] = e_data['keywords'].replace("<SEP>", ",")
                            hyperedges_data[edge_key] = e_data

                    processor.add_log(f"✅ 处理完成！顶点: {len(vertices_data)}, 超边: {len(hyperedges_data)}")
                    doc["vertices"] = vertices_data
                    doc["hyperedges_data"] = hyperedges_data
                    doc["status"] = "completed"
                    processor.status = "completed"

                    # 最终 yield：处理完成，展示结果
                    final_msg = f"完成！提取了 {len(vertices_data)} 个顶点, {len(hyperedges_data)} 条超边"
                    yield processor.get_document_html(doc_id), final_msg, processor, gr.update(visible=True)

                except Exception as e:
                    processor.add_log(f"处理失败: {str(e)}")
                    doc["status"] = "error"
                    processor.status = "error"
                    yield processor.get_document_html(doc_id), f"处理发生错误: {str(e)}", processor, gr.update(visible=False)

            def save_database(processor):
                """保存当前文档的数据库到正式目录"""
                if not processor.current_doc:
                    return "没有文档可保存", gr.update(visible=False)

                doc = next((d for d in processor.documents if d["id"] == processor.current_doc), None)
                if not doc or doc.get("status") != "completed":
                    return "文档未完成处理", gr.update(visible=False)

                # 获取临时数据库路径
                temp_db_name = f"temp_{processor.current_doc}"
                temp_dir = Path(hyperrag_working_dir) / temp_db_name

                # 查找 .hgdb 文件
                hgdb_files = list(temp_dir.glob("*.hgdb"))
                if not hgdb_files:
                    return "未找到数据库文件", gr.update(visible=False)

                # 使用文档名称作为数据库名称
                db_name = doc["name"].split('.')[0]  # 去掉扩展名
                db_name = "".join(c for c in db_name if c.isalnum() or c in ('_', '-')).strip('_')

                # 创建正式数据库目录
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                target_dir = CACHE_DIR / db_name
                target_dir.mkdir(parents=True, exist_ok=True)

                # 复制数据库文件
                target_path = target_dir / "hypergraph_chunk_entity_relation.hgdb"
                shutil.copy2(hgdb_files[0], target_path)

                processor.add_log(f"数据库已保存到: {db_name}")
                return f"已保存到数据库: {db_name}", gr.update(visible=False)

            def reset_flow(processor):
                processor.reset()
                return processor.get_document_html(), "已重置", processor, gr.update(visible=False)

            def on_file_change(f):
                if f is None:
                    return gr.Textbox(value="未选择文件")
                file_name = getattr(f, 'name', None) if hasattr(f, 'name') else str(f)
                if not file_name:
                    file_name = "已选择文件"
                return gr.Textbox(value=f"已选择: {file_name}")

            # 绑定事件
            file_upload.change(
                fn=on_file_change,
                inputs=[file_upload],
                outputs=[status_display]
            )

            process_btn.click(
                fn=process_document_async,
                inputs=[file_upload, user_session],
                outputs=[doc_output, status_display, user_session, save_btn]
            )

            save_btn.click(
                fn=save_database,
                inputs=[user_session],
                outputs=[status_display, save_btn]
            )

            reset_btn.click(
                fn=reset_flow,
                inputs=[user_session],
                outputs=[doc_output, status_display, user_session, save_btn]
            )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
