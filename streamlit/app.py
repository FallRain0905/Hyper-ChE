"""
Hyper-RAG Hypergraph Visualization with Streamlit
"""
import streamlit as st
import sys
import os
import json
from pathlib import Path
import pickle

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
    if st.session_state.data_loaded:
        page = st.sidebar.radio(
            "Select Page",
            ["🔷 Full Hypergraph", "🔍 Vertex Details", "⚖️ Graph Comparison"],
            label_visibility="collapsed"
        )
    else:
        page = None
        st.sidebar.info("⬆️ Please import a database first")

    # Main content
    if st.session_state.data_loaded:
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

        ## 📁 Import Data

        Use the **sidebar** to:
        1. **Upload** a `.hgdb` file, or
        2. **Select** a database from project cache

        ## 🧭 Features

        - **Full Hypergraph**: View complete hypergraph with bubble-sets style hyperedge visualization
        - **Vertex Details**: Select a vertex to see its properties with side panel (matching Web-UI style)
        - **Graph Comparison**: Compare traditional graph structure vs hypergraph structure

        ## 🎨 Visualization Features

        - **Bubble-Sets Style**: Hyperedges are shown as semi-transparent bubbles enclosing related vertices
        - **Interactive Zoom/Pan**: Full control over the visualization view
        - **Entity Type Coloring**: Consistent color coding across entity types
        - **Drag & Drop**: Move vertices to rearrange the graph layout
        - **Hover Tooltips**: Detailed information on vertex hover
        """)

        # Show welcome card with instructions
        st.markdown("""
        <div class="info-card">
            <h3 style="margin-top: 0;">🚀 Quick Start</h3>
            <ol>
                <li>Upload a hypergraph database file (.hgdb) using the file uploader in the sidebar</li>
                <li>Or select a database from the available cache options</li>
                <li>Navigate between pages using the sidebar menu</li>
            </ol>
        </div>
        """, unsafe_allow_html=True)

        st.info("⬆️ Import a database from sidebar to get started!")


if __name__ == "__main__":
    main()
