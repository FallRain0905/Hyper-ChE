"""
Hyper-RAG Hypergraph Visualizer - Gradio with AntV G6
完全复刻 Web-UI 的超图显示效果

使用 CDN + iframe srcdoc 避免 Gradio 的 script 标签屏蔽问题
"""
import gradio as gr
from pathlib import Path
import json
import html as html_lib
from typing import Dict, List
import sys
import importlib.util

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import utils from streamlit directory
utils_path = project_root / "streamlit" / "utils.py"
spec = importlib.util.spec_from_file_location("utils", utils_path)
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)
load_hypergraph_data = utils.load_hypergraph_data

# Cache directory for databases
CACHE_DIR = project_root / "web-ui" / "backend" / "hyperrag_cache"

# ============================================
# 颜色配置 - 与 Web-UI 完全一致
# ============================================

# 实体类型颜色 (Web-UI: HyperGraph/index.tsx)
ENTITY_TYPE_COLORS = {
    'PERSON': '#00C9C9',
    'CONCEPT': '#a68fff',
    'ORGANIZATION': '#F08F56',
    'LOCATION': '#16f69c',
    'EVENT': '#004ac9',
    'PRODUCT': '#f056d1',
    'DEFAULT': '#8566CC'
}

# 超边颜色 (Web-UI: HyperGraph/index.tsx)
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
# 数据加载函数
# ============================================

def get_available_databases() -> List[str]:
    """获取可用的数据库列表"""
    if not CACHE_DIR.exists():
        return []
    return [
        d.name for d in CACHE_DIR.iterdir()
        if d.is_dir() and (d / "hypergraph_chunk_entity_relation.hgdb").exists()
    ]


def load_database(db_name: str) -> Dict:
    """加载指定的数据库"""
    if not db_name:
        return None

    db_path = CACHE_DIR / db_name / "hypergraph_chunk_entity_relation.hgdb"
    vertices, hyperedges = load_hypergraph_data(db_path)

    return {
        'vertices': vertices,
        'hyperedges': hyperedges,
        'db_name': db_name
    }


def get_vertices(vertices: Dict) -> List[str]:
    """获取顶点列表"""
    if not vertices:
        return []
    return list(vertices.keys())


# ============================================
# G6 + BubbleSets 配置生成
# ============================================

def create_g6_options(data: Dict, vertex_id: str = None, show_labels: bool = True) -> Dict:
    """
    生成 G6 配置选项
    完全匹配 Web-UI 的配置逻辑
    """
    vertices = data.get('vertices', {})
    hyperedges = data.get('hyperedges', {})

    # 构建节点数据
    nodes = []
    for v_id, v_data in vertices.items():
        entity_type = v_data.get('entity_type', 'DEFAULT')
        nodes.append({
            'id': v_id,
            'data': {
                'label': v_id,
                'entity_type': entity_type,
                'cluster': entity_type,
                'description': v_data.get('description', '')
            }
        })

    # 构建超边插件 - G6 BubbleSets
    plugins = []

    for idx, (edge_key, edge_data) in enumerate(hyperedges.items()):
        vertices_list = edge_data.get('vertices', [])
        # 确保 members 是有效的节点 ID 列表
        members = [v for v in vertices_list if v in vertices]

        if len(members) < 2:
            continue  # 至少需要2个节点才能形成超边

        bubble_color = BUBBLE_COLORS[idx % len(BUBBLE_COLORS)]
        keywords = edge_data.get('keywords', '')

        # G6 BubbleSets 插件配置 - 与 Web-UI 完全一致
        plugin_config = {
            'type': 'bubble-sets',
            'key': f'bubble-sets-{idx}',
            'members': members,
            'fill': bubble_color,
            'fillOpacity': 0.1,  # 半透明填充
            'stroke': bubble_color,
            'strokeOpacity': 1.0,
            # BubbleSets 算法参数 - 与 Web-UI 完全一致
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

        # 如果需要显示标签，添加标签配置
        if show_labels and keywords:
            plugin_config['label'] = True
            plugin_config['labelText'] = keywords
            plugin_config['labelBackground'] = True
            plugin_config['labelBackgroundFill'] = bubble_color
            plugin_config['labelFill'] = '#fff'
            plugin_config['labelPadding'] = 4

        plugins.append(plugin_config)

    # 构建 G6 完整配置 - 参考 Web-UI
    current_id_json = json.dumps(vertex_id)
    colors_json = json.dumps(ENTITY_TYPE_COLORS)

    options = {
        'autoFit': 'center',
        'data': {
            'nodes': nodes,
            'edges': []
        },
        'node': {
            'style': {
                'size': 25,
                'labelText': 'd => d.data?.label || d.id',
                'labelFill': '#333',
                'labelFontSize': 12,
                'labelOffsetX': 0,
                'labelOffsetY': 0,
                # 顶点颜色逻辑 - 与 Web-UI 完全一致
                'fill': f'd => {{ const currentId = {current_id_json}; if (d.id === currentId) {{ return "#000000"; }} const entityType = d.data?.entity_type; if (entityType) {{ const colors = {colors_json}; return colors[entityType] || "#8566CC"; }} return "#8566CC"; }}'
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
            'type': 'force',
            'preventOverlap': True,
            'nodeStrength': -300,
            'linkDistance': 150,
            'gravity': 20
        },
        'plugins': plugins
    }

    return options


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
        console.log("Graph options:", options);

        function initGraph() {{
            if (typeof G6 === "undefined") {{
                console.error("G6 not loaded");
                document.getElementById("loading").innerHTML = "<span style='color:red'>G6 加载失败</span>";
                return;
            }}

            if (typeof G6.Graph === "undefined") {{
                console.error("G6.Graph not available");
                return;
            }}

            console.log("G6 ready, version:", G6.version);
            var container = document.getElementById("g6-container");

            try {{
                var graph = new G6.Graph({{
                    container: "g6-container",
                    width: window.innerWidth,
                    height: window.innerHeight,
                    ...options
                }});

                graph.render();
                console.log("Graph rendered successfully!");
                console.log("Nodes:", options.data.nodes.length);
                console.log("Plugins:", options.plugins.length);

                var loading = document.getElementById("loading");
                if (loading) loading.style.display = "none";

                window.addEventListener("resize", function() {{
                    graph.changeSize(window.innerWidth, window.innerHeight);
                }});

                console.log("=== SUCCESS ===");
            }} catch (e) {{
                console.error("Error:", e);
                console.error("Stack:", e.stack);
                container.innerHTML = '<div id="error"><h3>初始化失败</h3><p>' + e.message + '</p><pre>' + e.stack + '</pre></div>';
            }}
        }}

        // 等待 G6 加载
        var retries = 0;
        var checkG6 = setInterval(function() {{
            if (typeof G6 !== "undefined") {{
                clearInterval(checkG6);
                console.log("G6 loaded after", retries, "retries");
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
    """创建顶点详情页面 - 模仿 Web-UI 右侧面板布局"""
    vertex = vertices.get(vertex_id)
    if not vertex:
        return "<div style='padding: 20px; text-align: center; color: #999;'>顶点不存在</div>"

    # 获取相关超边
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

    # 准备子图数据（只包含相关顶点和超边）
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

    # 构建顶点信息
    entity_type = vertex.get('entity_type', 'DEFAULT')
    entity_color = ENTITY_TYPE_COLORS.get(entity_type, ENTITY_TYPE_COLORS['DEFAULT'])
    description = vertex.get('description', '').replace('<SEP>', ' | ')

    # G6 配置
    data = {'vertices': sub_vertices, 'hyperedges': sub_hyperedges}
    options = create_g6_options(data, vertex_id, show_labels)
    options_json = json.dumps(options, ensure_ascii=False)

    # 构建 HTML - 模仿 Web-UI 布局
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

        /* 信息面板样式 - 模仿 Web-UI */
        .info-header {{ padding: 20px; border-bottom: 1px solid #e8e8e8; }}
        .info-title {{ font-size: 16px; font-weight: 600; color: #333; margin-bottom: 8px; }}
        .info-meta {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .info-tag {{ padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 500; }}
        .info-content {{ padding: 20px; overflow-y: auto; flex: 1; }}
        .info-section {{ margin-bottom: 24px; }}
        .info-section-title {{ font-size: 13px; font-weight: 600; color: #666; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }}
        .info-text {{ font-size: 14px; color: #333; line-height: 1.6; }}
        .hyperedge-list {{ display: flex; flex-direction: column; gap: 8px; }}
        .hyperedge-item {{
            padding: 12px;
            border-radius: 6px;
            border-left: 4px solid #ddd;
            background: #fafafa;
        }}
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
                            f'<div class="hyperedge-item" style="border-left-color: {he["color"]};">' +
                            f'<div class="hyperedge-keywords">{he["keywords"] or "Hyperedge " + str(he["id"]+1)}</div>' +
                            f'<div class="hyperedge-members">{len(he["members"])} members</div>' +
                            '</div>'
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
# Gradio 应用
# ============================================

with gr.Blocks(title="Hyper-RAG Hypergraph Visualizer") as demo:
    gr.Markdown("""
    # 🔷 Hyper-RAG Hypergraph Visualizer

    使用 **AntV G6 BubbleSets** 的超图可视化工具 - 完全复刻 Web-UI 效果

    - G6 v5 (CDN 加载)
    - BubbleSets 插件用于超边可视化
    - iframe srcdoc 解决 Gradio script 标签问题
    """)

    with gr.Row():
        with gr.Column(scale=1, min_width=250):
            # 数据库选择
            db_list = get_available_databases()
            db_selector = gr.Dropdown(
                choices=db_list,
                label="📁 选择数据库",
                value=None if not db_list else db_list[0],
                info="选择要可视化的超图数据库"
            )

            # 页面模式选择
            page_mode = gr.Radio(
                choices=["Vertex Details", "Full Hypergraph"],
                value="Vertex Details",
                label="📊 显示模式",
                info="Vertex Details: 查看单个顶点的邻居; Full Hypergraph: 显示整个超图"
            )

            # 顶点选择
            vertex_selector = gr.Dropdown(
                choices=[],
                label="🔍 选择顶点",
                value=None,
                info="选择要查看详情的顶点 (仅 Vertex Details 模式)"
            )

            # 超边标签显示
            show_labels = gr.Checkbox(
                value=True,
                label="🏷️ 显示超边标签",
                info="在气泡上显示关键词"
            )

            # 加载按钮
            load_btn = gr.Button("🚀 加载超图", variant="primary", size="lg")

            # 状态信息
            status_info = gr.Textbox(
                label="状态",
                value="就绪",
                interactive=False
            )

        with gr.Column(scale=5):
            # 图形显示区域
            output_html = gr.HTML(
                value='<div style="display:flex;align-items:center;justify-content:center;height:400px;color:#999;border:2px dashed #d9d9d9;border-radius:8px;background:#fafafa;">请选择数据库并点击加载按钮</div>'
            )

    # 获取顶点列表
    def update_vertex_list(db_name: str):
        if not db_name:
            return gr.Dropdown(choices=[], value=None)
        data = load_database(db_name)
        if not data:
            return gr.Dropdown(choices=[], value=None)
        vertices = list(data['vertices'].keys())
        # 排序并返回
        vertices.sort()
        return gr.Dropdown(choices=vertices, value=vertices[0] if vertices else None)

    # 加载图形 - 使用 iframe srcdoc 解决 Gradio script 标签屏蔽问题
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

        print(f"Loading graph: {db_name}, mode={page_mode}, vertex={vertex_id}")
        print(f"  - Vertices: {v_count}")
        print(f"  - Hyperedges: {he_count}")

        if page_mode == "Full Hypergraph":
            # 显示完整超图
            inner_html = create_full_graph_page(
                create_g6_options(data, None, show_lbl),
                v_count,
                he_count
            )
            status = f"已加载: {db_name} (完整超图: {v_count} 顶点, {he_count} 超边)"
            height = "900px"
        else:
            # 显示顶点详情
            if not vertex_id:
                return gr.HTML(value='<div style="padding:40px;text-align:center;color:#ff4d4f;">请先选择顶点</div>'), "错误: 未选择顶点"

            inner_html = create_vertex_details_page(vertex_id, vertices, hyperedges, show_lbl)
            status = f"已加载: {db_name} - {vertex_id} 的详情"
            height = "900px"

        # 使用 iframe srcdoc 包装 HTML，解决 Gradio script 标签不执行问题
        safe_html = html_lib.escape(inner_html)
        iframe_html = f'''<iframe style="width: 100%; height: {height}; border: none; border-radius: 8px;" srcdoc="{safe_html}" sandbox="allow-scripts allow-same-origin"></iframe>'''

        return gr.HTML(value=iframe_html), status

    # 事件绑定
    db_selector.change(update_vertex_list, inputs=[db_selector], outputs=[vertex_selector])
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

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
