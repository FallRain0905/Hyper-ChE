# Hyper-RAG Hypergraph Visualizer

A Streamlit-based web application for visualizing hypergraph data from the Hyper-RAG system using **D3.js bubble-sets** style visualization.

## Features

- 🔷 **Full Hypergraph**: View complete hypergraph with bubble-sets style hyperedge visualization
- 🔍 **Vertex Details**: Select a vertex to see its properties with side panel (matching Web-UI style)
- ⚖️ **Graph Comparison**: Compare traditional graph structure vs hypergraph structure

## Visualization Style

This visualizer now uses **D3.js bubble-sets** style for hyperedge visualization, matching the style of the main Web-UI:

- **Bubble-Sets**: Hyperedges are shown as semi-transparent ellipses/bubbles enclosing related vertices
- **Dashed Borders**: Hyperedge boundaries are indicated with dashed colored lines
- **Multi-Node Support**: True hypergraph visualization showing multiple vertices in a single hyperedge
- **Interactive**: Drag nodes, zoom in/out, and hover for details

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
streamlit run app.py
```

## Usage

### Import Data

You can import hypergraph data in two ways:

1. **Upload .hgdb file**: Use the file uploader in the sidebar to upload a hypergraph database file.

2. **Load from cache**: Select a database from the project's hyperrag_cache directory.

### Pages

#### 1. Full Hypergraph
Displays the complete hypergraph with:
- All vertices as nodes with entity-type coloring
- All hyperedges as bubble-sets (semi-transparent bubbles)
- Statistics: vertex count, hyperedge count
- Interactive zoom, pan, drag features
- Toggle for hyperedge labels

#### 2. Vertex Details
Select any vertex to view:
- **Left**: Interactive hypergraph showing the vertex and its related hyperedges
- **Right Panel**:
  - Vertex information (ID, entity name, type)
  - Entity type colored tags
  - Description
  - Additional properties
  - List of related hyperedges with keywords
  - Statistics (related vertices/hyperedges count)

This layout matches the Web-UI's Vertex Details page.

#### 3. Graph Comparison
Side-by-side comparison showing:
- **Left (Graph Structure)**: Traditional graph where hyperedges are converted to pairwise edges
- **Right (Hypergraph Structure)**: Hypergraph with labeled hyperedges (pairwise edges for comparison)

> **Note**: For true bubble-sets visualization, use the Full Hypergraph page.

## Visualization Settings

In the sidebar, you can toggle:
- **Show Hyperedge Labels**: Display labels on bubble-sets for hyperedges

## Color Coding

### Entity Types
| Type | Color |
|------|--------|
| PERSON | Cyan (#00C9C9) |
| CONCEPT | Purple (#a68fff) |
| ORGANIZATION | Orange (#F08F56) |
| LOCATION | Blue (#16f69c) |
| EVENT | Dark Blue (#004ac9) |
| PRODUCT | Magenta (#f056d1) |
| Default | Blue (#1890ff) |

### Hyperedges
A rotating palette of 11 colors is used to distinguish different hyperedges:
```
#F6BD16, #00C9C9, #F08F56, #FFA726, #FA8C16,
#722ED1, #a680ff, #c8ff00, #ffeb3b, #ff6b6b, #6366f1
```

## Technical Details

### Data Format
The application reads `.hgdb` pickle files containing:
- `v_data`: Vertex data dictionary
- `v_inci`: Vertex incidence dictionary
- `e_data`: Hyperedge data dictionary

### Visualization
- **D3.js v7**: JavaScript library for creating bubble-sets style visualization
- **Force-Directed Layout**: Automatic positioning with physics simulation
- **HTML Components**: Streamlit components for embedding D3.js visualizations
- **PyVis**: Kept for backward compatibility (used in Graph Comparison page)

## File Structure

```
streamlit/
├── .streamlit/
│   └── config.toml       # Streamlit configuration
├── app.py                 # Main Streamlit application
├── utils.py              # Utility functions for data loading
├── visualize.py           # Graph visualization functions (D3.js & PyVis)
├── requirements.txt        # Python dependencies
└── README.md             # This file
```

## Comparison with Web-UI

| Feature | Streamlit | Web-UI |
|---------|-----------|--------|
| Hyperedge Visualization | D3.js bubble-sets ✅ | AntV Graphin bubble-sets ✅ |
| Vertex Details Layout | Side panel ✅ | Side panel ✅ |
| Entity Type Colors | Consistent ✅ | Consistent ✅ |
| Full Graph View | ✅ | ✅ |
| Graph Comparison | ✅ | ❌ |

## Configuration

Edit `.streamlit/config.toml` to customize:
- Theme colors
- Fonts
- Logger settings
