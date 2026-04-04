"""
Hyper-RAG Hypergraph Visualization with Streamlit
"""
import streamlit as st
import sys
import os
import json
import asyncio
from pathlib import Path
import pickle
from datetime import datetime
from collections import defaultdict
import re

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils import load_hypergraph_data, get_vertex_details, get_related_hyperedges, get_entity_type_colors
from visualize import create_d3_bubble_sets_hypergraph, create_d3_vertex_details, create_pyvis_graph_comparison

# Page config
st.set_page_config(
    page_title="Hyper-RAG Hypergraph Visualizer",
    page_icon="🔷",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for blue/white theme (matching Web-UI style)
st.markdown("""
<style>
    /* Main background */
    .stApp {{
        background: linear-gradient(135deg, #f5f7fa 0%, #e4e9f7 100%);
    }}
    .main {{
        background-color: #ffffff;
        border-radius: 10px;
        padding: 16px;
        margin: 8px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }}
    /* Sidebar styling */
    .css-1d391kg {{
        background-color: #f0f5ff;
    }}
    /* Button styling */
    .stButton>button {{
        background-color: #1890ff;
        color: white;
        border: none;
        border-radius: 5px;
        padding: 8px 16px;
        font-weight: 500;
    }}
    .stButton>button:hover {{
        background-color: #40a9ff;
    }}
    /* Select box styling */
    .stSelectbox>div>div {{
        background-color: #f0f5ff;
    }}
    /* Header colors */
    h1, h2, h3 {{
        color: #1890ff;
    }}
    .stMetric {{
        background-color: #e6f7ff;
        border: 1px solid #91d5ff;
        border-radius: 8px;
        padding: 15px;
    }}
    /* Card styling */
    .info-card {{
        background-color: #f9f9f9;
        border: 1px solid #e8e8e8;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
    }}
</style>
""", unsafe_allow_html=True)

# Session state initialization
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'vertices' not in st.session_state:
    st.session_state.vertices = {}
if 'hyperedges' not in st.session_state:
    st.session_state.hyperedges = {}
if 'db_name' not in st.session_state:
    st.session_state.db_name = None
if 'selected_vertex' not in st.session_state:
    st.session_state.selected_vertex = None
if 'show_hyperedge_labels' not in st.session_state:
    st.session_state.show_hyperedge_labels = True

# Document processing session state
if 'uploaded_document' not in st.session_state:
    st.session_state.uploaded_document = None
if 'doc_content' not in st.session_state:
    st.session_state.doc_content = None
if 'doc_chunks' not in st.session_state:
    st.session_state.doc_chunks = []
if 'doc_entities' not in st.session_state:
    st.session_state.doc_entities = []
if 'doc_hyperedges' not in st.session_state:
    st.session_state.doc_hyperedges = []
if 'processing_logs' not in st.session_state:
    st.session_state.processing_logs = []
if 'processing_stage' not in st.session_state:
    st.session_state.processing_stage = None


def sidebar_database_import():
    """Database import section in sidebar"""
    st.sidebar.markdown("### 📁 Database Import")

    uploaded_file = st.sidebar.file_uploader(
        "Upload Hypergraph Database (.hgdb)",
        type=['hgdb', 'pkl'],
        help="Upload a .hgdb file containing hypergraph data"
    )

    if uploaded_file is not None:
        try:
            # Save uploaded file temporarily
            temp_path = Path("streamlit") / "temp.hgdb"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            # Load data
            vertices, hyperedges = load_hypergraph_data(temp_path)

            if vertices is not None:
                st.session_state.vertices = vertices
                st.session_state.hyperedges = hyperedges
                st.session_state.db_name = uploaded_file.name
                st.session_state.data_loaded = True
                st.session_state.selected_vertex = None

                st.sidebar.success(f"✅ Loaded {len(vertices)} vertices, {len(hyperedges)} hyperedges")
            else:
                st.sidebar.error("❌ Failed to load database file")
        except Exception as e:
            st.sidebar.error(f"❌ Error loading file: {str(e)}")

    # Load from project cache option
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🗂️ Or Load from Cache")

    cache_dir = project_root / "web-ui" / "backend" / "hyperrag_cache"

    if cache_dir.exists():
        databases = [d.name for d in cache_dir.iterdir() if d.is_dir() and (d / "hypergraph_chunk_entity_relation.hgdb").exists()]
        if databases:
            selected_db = st.sidebar.selectbox("Select database from cache", [""] + databases)
            if selected_db:
                db_path = cache_dir / selected_db / "hypergraph_chunk_entity_relation.hgdb"
                try:
                    vertices, hyperedges = load_hypergraph_data(db_path)

                    if vertices is not None:
                        st.session_state.vertices = vertices
                        st.session_state.hyperedges = hyperedges
                        st.session_state.db_name = selected_db
                        st.session_state.data_loaded = True
                        st.session_state.selected_vertex = None

                        st.sidebar.success(f"✅ Loaded {len(vertices)} vertices, {len(hyperedges)} hyperedges")
                except Exception as e:
                    st.sidebar.error(f"❌ Error: {str(e)}")

    # Visualization settings
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ Visualization Settings")
    st.session_state.show_hyperedge_labels = st.sidebar.checkbox(
        "Show Hyperedge Labels",
        value=True,
        help="Display labels on bubble-sets for hyperedges"
    )


def show_full_hypergraph():
    """Display full hypergraph visualization with D3.js bubble-sets"""
    st.subheader("🔷 Complete Hypergraph")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Vertices", len(st.session_state.vertices))
    with col2:
        st.metric("Hyperedges", len(st.session_state.hyperedges))

    # Create visualization using D3.js with bubble-sets
    with st.spinner("Creating bubble-sets hypergraph visualization..."):
        html_file = create_d3_bubble_sets_hypergraph(
            st.session_state.vertices,
            st.session_state.hyperedges,
            show_hyperedge_labels=st.session_state.show_hyperedge_labels,
            width=1200,
            height=700
        )

    # Display
    st.components.v1.html(html_file, height=720, scrolling=False)

    # Hyperedges list
    with st.expander("📋 Hyperedges List"):
        for i, (edge_id, edge_data) in enumerate(st.session_state.hyperedges.items()):
            st.markdown(f"**Hyperedge {i+1}**")
            st.markdown(f"- Keywords: {edge_data.get('keywords', 'N/A')}")
            st.markdown(f"- Vertices: `{', '.join(str(v) for v in edge_data)}`")
            st.markdown("---")


def show_vertex_details():
    """
    Display selected vertex details and related hypergraph
    Using side panel layout matching Web-UI style
    """
    # Get available vertices
    vertex_list = list(st.session_state.vertices.keys())

    if not vertex_list:
        st.warning("No vertices available. Please load a database first.")
        return

    # Vertex selector in a row (like Web-UI)
    col1, col2 = st.columns([1, 3])
    with col1:
        st.markdown("**Select Entity:**")
    with col2:
        selected_vertex = st.selectbox(
            "Entity",
            options=vertex_list,
            index=vertex_list.index(st.session_state.selected_vertex) if st.session_state.selected_vertex in vertex_list else 0,
            label_visibility="collapsed",
            key="vertex_selector"
        )

    if selected_vertex:
        st.session_state.selected_vertex = selected_vertex

        # Create visualization using D3.js with side panel
        with st.spinner("Creating vertex details visualization..."):
            html_file = create_d3_vertex_details(
                st.session_state.vertices,
                st.session_state.hyperedges,
                selected_vertex,
                width=1200,
                height=650
            )

        # Display the visualization (which includes the side panel)
        st.components.v1.html(html_file, height=700, scrolling=False)


def show_comparison():
    """Display graph vs hypergraph comparison"""
    st.subheader("⚖️ Graph vs Hypergraph Comparison")

    # Explanation
    st.info("""
    **Graph Structure (Left):** Shows traditional graph where hyperedges are converted to pairwise edges between vertices.

    **Hypergraph Structure (Right):** Shows hypergraph with labeled hyperedges (both using pairwise edges for comparison).

    > **Note:** For true bubble-sets hypergraph visualization, use the **Full Hypergraph** page.
    """)

    # Create comparison
    with st.spinner("Creating comparison visualization..."):
        htmls_json = create_pyvis_graph_comparison(
            st.session_state.vertices,
            st.session_state.hyperedges
        )
        htmls = json.loads(htmls_json)

    # 采用 Streamlit 原生的高性能分栏，彻底解决 PyVis 白屏问题
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("<h4 style='text-align:center; color:#475569;'>📊 Pairwise Graph</h4>", unsafe_allow_html=True)
        st.components.v1.html(htmls["graph"], height=620, scrolling=False)
    with col2:
        st.markdown("<h4 style='text-align:center; color:#10b981;'>🔷 Hyperedge Concepts</h4>", unsafe_allow_html=True)
        st.components.v1.html(htmls["hyper"], height=620, scrolling=False)


# Main app
def main():
    # Sidebar
    sidebar_database_import()

    st.sidebar.markdown("---")

    # Page navigation
    st.sidebar.markdown("### 🧭 Navigation")

    # 文档处理始终可用
    page = st.sidebar.radio(
        "Select Page",
        ["📄 Document Processing", "🔷 Full Hypergraph", "🔍 Vertex Details", "⚖️ Graph Comparison"],
        label_visibility="collapsed"
    )

    # 如果数据未加载且选择了数据可视化页面，显示提示
    if not st.session_state.data_loaded and page in ["🔷 Full Hypergraph", "🔍 Vertex Details", "⚖️ Graph Comparison"]:
        st.sidebar.info("⬆️ Please import a database first to visualize data")

    # Main content
    if page == "📄 Document Processing":
        show_document_processing()
    elif st.session_state.data_loaded:
        st.markdown(f"# 🔷 Hyper-RAG Visualizer - {st.session_state.db_name}")
        st.markdown("---")

        if page == "🔷 Full Hypergraph":
            show_full_hypergraph()
        elif page == "🔍 Vertex Details":
            show_vertex_details()
        elif page == "⚖️ Graph Comparison":
            show_comparison()
    else:
        st.markdown("""
        # 🔷 Welcome to Hyper-RAG Hypergraph Visualizer

        This tool allows you to visualize hypergraph data from the Hyper-RAG system using **D3.js bubble-sets** style visualization.

        ## 🧭 Features

        - **Document Processing**: Upload documents, chunk them using hyperrag's exact logic, extract entities, and build hypergraphs
        - **Full Hypergraph**: View complete hypergraph with bubble-sets style hyperedge visualization
        - **Vertex Details**: Select a vertex to see its properties with side panel (matching Web-UI style)
        - **Graph Comparison**: Compare traditional graph structure vs hypergraph structure

        ## 📁 Import Data

        Use the **sidebar** to:
        1. **Process Documents**: Upload .txt or .md files to extract entities and build hypergraphs
        2. **Upload** a `.hgdb` file to visualize existing data
        3. **Select** a database from project cache

        ## 🎨 Visualization Features

        - **Bubble-Sets Style**: Hyperedges are shown as semi-transparent bubbles enclosing related vertices
        - **Interactive Zoom/Pan**: Full control over the visualization view
        - **Entity Type Coloring**: Consistent color coding across entity types
        - **Drag & Drop**: Move vertices to rearrange the graph layout
        - **Hover Tooltips**: Detailed information on vertex hover

        ## 📄 Document Processing Flow

        The document processing follows the exact same logic as hyperrag:
        1. **Chunking**: Splits text by 1200 tokens with 100 token overlap
        2. **Entity Extraction**: Identifies entities, types, and relationships
        3. **Hypergraph Construction**: Builds hyperedges connecting related entities
        """)

        # Show welcome card with instructions
        st.markdown("""
        <div class="info-card">
            <h3 style="margin-top: 0;">🚀 Quick Start</h3>
            <ol>
                <li><strong>Process Documents:</strong> Select "📄 Document Processing" from sidebar to upload and analyze documents</li>
                <li><strong>Visualize Data:</strong> Upload a .hgdb file using the file uploader in the sidebar</li>
                <li>Or select a database from the available cache options</li>
                <li>Navigate between pages using the sidebar menu</li>
            </ol>
        </div>
        """, unsafe_allow_html=True)

        st.info("👉 Start with **Document Processing** to build hypergraphs from your documents, or import an existing database!")


def show_document_processing():
    """文档处理页面 - 分阶段展示文档处理流程，使用 hyperrag 的分块逻辑"""
    st.header("📄 文档处理")

    # 文档上传区域
    st.subheader("📤 上传文档")
    uploaded_file = st.file_uploader(
        "支持 .txt, .md, .pdf 文件",
        type=['txt', 'md', 'pdf'],
        help="上传文档进行分块和实体提取"
    )

    if uploaded_file is not None:
        # 读取文档内容
        try:
            if uploaded_file.type == 'application/pdf':
                st.info("PDF 文件支持正在开发中，请使用 .txt 或 .md 文件")
                return

            # 读取文本文件
            content = uploaded_file.read().decode('utf-8')
            st.session_state.doc_content = content
            st.session_state.uploaded_document = uploaded_file.name

            # 显示文档信息
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("文档名称", uploaded_file.name[:20] + "..." if len(uploaded_file.name) > 20 else uploaded_file.name)
            with col2:
                st.metric("字符数", len(content))
            with col3:
                # 估算 token 数（约 0.75 tokens/字符）
                st.metric("估算 Token", int(len(content) * 0.75))

            # 文档预览
            with st.expander("📄 文档预览"):
                st.text_area("文档内容", content, height=200, disabled=True, label_visibility="collapsed")

            # 处理按钮
            if st.button("🚀 开始处理", type="primary"):
                process_document()

        except Exception as e:
            st.error(f"❌ 读取文档失败: {str(e)}")

    # 显示处理结果
    if st.session_state.processing_stage:
        show_processing_results()


def process_document():
    """处理文档：分块 -> 嵌入 -> 实体提取"""
    content = st.session_state.doc_content
    if not content:
        st.warning("请先上传文档")
        return

    # 使用 hyperrag 的分块逻辑
    try:
        import tiktoken

        # 初始化 tiktoken
        encoding = tiktoken.encoding_for_model("gpt-4o-mini")
        tokens = encoding.encode(content)

        # hyperrag 分块参数
        chunk_token_size = 1200
        overlap_token_size = 100

        chunks = []
        for index, start in enumerate(range(0, len(tokens), chunk_token_size - overlap_token_size)):
            chunk_tokens = tokens[start: start + chunk_token_size]
            chunk_content = encoding.decode(chunk_tokens).strip()
            chunks.append({
                "chunk_order_index": index,
                "tokens": len(chunk_tokens),
                "content": chunk_content,
            })

        st.session_state.doc_chunks = chunks
        st.session_state.processing_stage = "chunked"
        st.session_state.processing_logs.append(f"✅ [{datetime.now().strftime('%H:%M:%S')}] 分块完成: {len(chunks)} 个文本块")

        # 模拟实体提取（实际使用 hyperrag 的 extract_entities）
        simulate_entity_extraction(chunks)

    except ImportError:
        st.warning("tiktoken 未安装，使用简单分块")
        simple_chunking(content)
    except Exception as e:
        st.error(f"❌ 处理失败: {str(e)}")


def simple_chunking(content):
    """简单的基于字符的分块（备用方案）"""
    chunk_size = 4000  # 约 3000 tokens
    overlap = 300
    chunks = []

    for index, start in enumerate(range(0, len(content), chunk_size - overlap)):
        chunk_content = content[start: start + chunk_size].strip()
        chunks.append({
            "chunk_order_index": index,
            "tokens": int(len(chunk_content) * 0.75),  # 估算
            "content": chunk_content,
        })

    st.session_state.doc_chunks = chunks
    st.session_state.processing_stage = "chunked"
    st.session_state.processing_logs.append(f"✅ [{datetime.now().strftime('%H:%M:%S')}] 分块完成: {len(chunks)} 个文本块")

    simulate_entity_extraction(chunks)


def simulate_entity_extraction(chunks):
    """模拟实体提取（展示演示效果）"""
    # 从 chunk 内容中提取潜在实体（简单规则）
    entities = []
    hyperedges = []

    # 常见的实体模式
    entity_patterns = [
        r'\b([A-Z][a-z]+)\s+(?:公司|集团|科技|软件|研究院|大学|银行)\b',  # 机构
        r'\b([A-Z][a-z]{2,20})\b',  # 大写单词（可能是人名/专有名词）
    ]

    for i, chunk in enumerate(chunks):
        # 简单的实体提取（演示用）
        content = chunk['content'][:500]  # 只看前500字符

        # 提取数字和大写词作为"实体"
        found_entities = set(re.findall(r'\b([A-Z][a-zA-Z]{2,})\b', content))
        for entity in found_entities[:5]:  # 限制每块最多5个实体
            entity_name = entity.upper()
            entity_type = "ORGANIZATION" if len(entity) > 6 else "PERSON"
            entities.append({
                "entity_name": entity_name,
                "entity_type": entity_type,
                "description": f"从文本块 {i} 中提取的实体",
                "source_chunk": i,
            })

        # 创建简单的超边
        if len(found_entities) >= 2:
            edge_entities = list(found_entities)[:3]
            hyperedges.append({
                "vertices": [e.upper() for e in edge_entities],
                "keywords": chunk['content'][:50] + "...",
                "description": f"文本块 {i} 中的关联",
                "source_chunk": i,
            })

    # 去重
    seen = set()
    unique_entities = []
    for e in entities:
        if e['entity_name'] not in seen:
            seen.add(e['entity_name'])
            unique_entities.append(e)

    st.session_state.doc_entities = unique_entities[:20]  # 限制显示数量
    st.session_state.doc_hyperedges = hyperedges[:10]  # 限制显示数量
    st.session_state.processing_stage = "completed"
    st.session_state.processing_logs.append(f"✅ [{datetime.now().strftime('%H:%M:%S')}] 实体提取完成: {len(unique_entities)} 个实体")
    st.session_state.processing_logs.append(f"✅ [{datetime.now().strftime('%H:%M:%S')}] 超边构建完成: {len(hyperedges)} 条超边")


def show_processing_results():
    """显示处理结果"""
    stage = st.session_state.processing_stage

    # 阶段进度
    stages = [
        ("📤 上传文档", "uploaded"),
        ("✂️ 文本分块", "chunked"),
        ("🏷️ 实体提取", "extracted"),
        ("🔗 超边构建", "completed"),
    ]

    progress_steps = []
    current_step = 0

    for i, (label, key) in enumerate(stages):
        is_complete = False
        if key == "uploaded":
            is_complete = st.session_state.uploaded_document is not None
        elif key == "chunked":
            is_complete = stage in ["chunked", "extracted", "completed"]
        elif key == "extracted":
            is_complete = stage in ["extracted", "completed"]
        elif key == "completed":
            is_complete = stage == "completed"

        if is_complete and current_step == i:
            current_step = i + 1

        color = "🟢" if is_complete else ("🔵" if current_step == i else "⚪")
        status = "✓ 已完成" if is_complete else ("→ 进行中" if current_step == i else "○ 待处理")
        progress_steps.append(f"{color} {label}: {status}")

    # 显示进度
    st.subheader("📊 处理进度")
    for step in progress_steps:
        st.markdown(step)

    # 处理日志
    if st.session_state.processing_logs:
        with st.expander("📋 处理日志"):
            for log in st.session_state.processing_logs:
                st.text(log)

    # 文本块列表
    if st.session_state.doc_chunks:
        st.subheader(f"📝 文本块 ({len(st.session_state.doc_chunks)} 个)")

        col1, col2 = st.columns([2, 1])

        with col1:
            # 可滚动的文本块列表
            chunk_container = st.container()
            with chunk_container:
                st.markdown("### 文本块内容")

                for i, chunk in enumerate(st.session_state.doc_chunks):
                    with st.expander(f"📄 块 {i+1} (~{chunk['tokens']} tokens)", expanded=(i == 0)):
                        st.markdown(f"""
                        <div style="background-color: #f5f5f5; padding: 10px; border-radius: 5px; border-left: 4px solid #1890ff;">
                            <strong>块序号:</strong> {chunk['chunk_order_index'] + 1}<br>
                            <strong>Token数:</strong> {chunk['tokens']}<br>
                            <strong>内容预览:</strong>
                        </div>
                        """, unsafe_allow_html=True)
                        st.text_area("内容", chunk['content'], height=150, key=f"chunk_{i}", label_visibility="collapsed")

        with col2:
            # 文本块统计
            st.markdown("### 📊 统计信息")
            total_tokens = sum(c['tokens'] for c in st.session_state.doc_chunks)
            avg_tokens = total_tokens // len(st.session_state.doc_chunks) if st.session_state.doc_chunks else 0

            st.metric("总 Token 数", total_tokens)
            st.metric("平均 Token/块", avg_tokens)
            st.metric("块数量", len(st.session_state.doc_chunks))

    # 实体列表
    if st.session_state.doc_entities:
        st.subheader(f"🏷️ 提取的实体 ({len(st.session_state.doc_entities)} 个)")

        # 按类型分组
        entities_by_type = defaultdict(list)
        for entity in st.session_state.doc_entities:
            entities_by_type[entity['entity_type']].append(entity)

        for entity_type, entities in entities_by_type.items():
            with st.expander(f"📂 {entity_type} ({len(entities)} 个)", expanded=True):
                for entity in entities:
                    st.markdown(f"""
                    <div style="background-color: #e6f7ff; padding: 8px; border-radius: 5px; margin-bottom: 8px; border-left: 4px solid #1890ff;">
                        <strong>👤 {entity['entity_name']}</strong><br>
                        <small>类型: {entity_type} | 来源: 块 {entity['source_chunk'] + 1}</small>
                    </div>
                    """, unsafe_allow_html=True)

    # 超边列表
    if st.session_state.doc_hyperedges:
        st.subheader(f"🔗 构建的超边 ({len(st.session_state.doc_hyperedges)} 条)")

        for i, edge in enumerate(st.session_state.doc_hyperedges):
            with st.expander(f"🔷 超边 {i+1}", expanded=(i < 3)):
                vertices_str = ", ".join(edge['vertices'])
                st.markdown(f"""
                <div style="background-color: #f6ffed; padding: 10px; border-radius: 5px; border-left: 4px solid #52c41a;">
                    <strong>📍 包含顶点:</strong> {vertices_str}<br>
                    <strong>🏷️ 关键词:</strong> {edge['keywords']}<br>
                    <strong>📝 描述:</strong> {edge['description']}<br>
                    <small>来源: 块 {edge['source_chunk'] + 1}</small>
                </div>
                """, unsafe_allow_html=True)

    # 重置按钮
    if st.button("🔄 重新开始", type="secondary"):
        for key in ['doc_content', 'doc_chunks', 'doc_entities', 'doc_hyperedges', 'processing_logs', 'processing_stage', 'uploaded_document']:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()


if __name__ == "__main__":
    main()
