"""
Utility functions for loading and processing hypergraph data
"""
import pickle
from pathlib import Path
from typing import Dict, Tuple, List, Set, Any
from collections import defaultdict


def load_hypergraph_data(file_path: Path) -> tuple:
    """
    Load hypergraph database from .hgdb pickle file

    Args:
        file_path: Path to the .hgdb file

    Returns:
        Tuple of (vertices_dict, hyperedges_dict) or (None, None) on failure
    """
    try:
        with open(file_path, "rb") as f:
            data = pickle.load(f)

        # Data structure from HypergraphDB:
        # - v_data: vertex data dict {vertex_name: {entity_name, entity_type, description, additional_properties}}
        # - v_inci: vertex incidence dict {vertex_name: set(hyperedge_tuples)}
        # - e_data: hyperedge data dict {hyperedge_tuple: {keywords, summary}}

        v_data = data.get("v_data", {})
        v_inci = data.get("v_inci", {})
        e_data = data.get("e_data", {})

        # Convert vertex data format
        vertices = {}
        for vertex_name, vertex_info in v_data.items():
            vertices[vertex_name] = {
                'entity_name': vertex_info.get('entity_name', vertex_name),
                'entity_type': vertex_info.get('entity_type', 'default'),
                'description': vertex_info.get('description', ''),
                'additional_properties': vertex_info.get('additional_properties', '')
            }

        # Convert hyperedge data
        hyperedges = {}
        for edge_tuple, edge_info in e_data.items():
            # edge_tuple might be a tuple or tuple converted to string
            if isinstance(edge_tuple, str):
                # Parse string like "('v1', 'v2', 'v3')"
                import ast
                edge_tuple = ast.literal_eval(edge_tuple)

            # Convert tuple of vertex names to our format
            vertices_list = list(edge_tuple)
            edge_id = '|*|'.join(vertices_list)

            hyperedges[edge_id] = {
                'vertices': vertices_list,
                'keywords': edge_info.get('keywords', ''),
                'summary': edge_info.get('summary', '')
            }

        return vertices, hyperedges

    except Exception as e:
        print(f"Error loading hypergraph data: {e}")
        return None, None


def get_vertex_details(vertices: Dict[str, Dict], vertex_id: str) -> Dict:
    """
    Get vertex details by ID

    Args:
        vertices: Dictionary of vertices
        vertex_id: Vertex ID to look up

    Returns:
        Vertex data dictionary
    """
    return vertices.get(vertex_id, {})


def get_related_hyperedges(hyperedges: Dict[str, Dict], vertex_id: str) -> List[Tuple]:
    """
    Get all hyperedges that contain the specified vertex

    Args:
        hyperedges: Dictionary of hyperedges
        vertex_id: Vertex to search for

    Returns:
        List of hyperedge tuples containing the vertex
    """
    related = []
    vertex_id_str = str(vertex_id)

    for edge_id, edge_data in hyperedges.items():
        vertices_list = edge_data.get('vertices', [])
        if vertex_id_str in vertices_list:
            # Convert to tuple for consistency
            related.append(tuple(vertices_list))

    return related


def convert_hyperedges_to_graph_edges(hyperedges: Dict[str, Dict]) -> List[Tuple]:
    """
    Convert hyperedges to traditional graph edges (pairwise)

    For each hyperedge with vertices [v1, v2, v3, ...],
    creates edges: [(v1, v2), (v2, v3), (v3, v4), ...]

    Args:
        hyperedges: Dictionary of hyperedges

    Returns:
        List of edge tuples
    """
    graph_edges = []

    for edge_id, edge_data in hyperedges.items():
        vertices_list = edge_data.get('vertices', [])

        # Create pairwise edges between consecutive vertices
        for i in range(len(vertices_list) - 1):
            edge = (vertices_list[i], vertices_list[i + 1])
            graph_edges.append(edge)

    return graph_edges


def get_entity_type_colors() -> Dict[str, str]:
    """
    Get entity type color mapping

    Returns:
        Dictionary mapping entity types to hex colors
    """
    return {
        'PERSON': '#00C9C9',
        'CONCEPT': '#a68fff',
        'ORGANIZATION': '#F08F56',
        'LOCATION': '#16f69c',
        'EVENT': '#004ac9',
        'PRODUCT': '#f056d1',
        'default': '#1890ff'
    }



def get_entity_type_colors_light() -> Dict[str, str]:
    """
    Get lighter entity type colors for vertices (so hyperedges stand out)

    Returns:
        Dictionary mapping entity types to lighter hex colors
    """
    return {
        'PERSON': '#5FD9E8',      # Light cyan
        'CONCEPT': '#B8B3FF',      # Light purple
        'ORGANIZATION': '#FFB366',   # Light orange
        'LOCATION': '#FFD699',      # Light blue
        'EVENT': '#5FB7FF',       # Light blue
        'PRODUCT': '#E06BFF',       # Light magenta
        'default': '#87CEEB'        # Light blue-gray
    }


def get_hyperedge_colors() -> List[str]:
    """
    Get list of colors for hyperedges

    Returns:
        List of hex color strings
    """
    return [
        '#F6BD16',
        '#00C9C9',
        '#F08F56',
        '#FFA726',
        '#FA8C16',
        '#722ED1',
        '#a680ff',
        '#c8ff00',
        '#ffeb3b',
        '#ff6b6b',
        '#6366f1'
    ]


def get_hyperedge_colors_darker() -> List[str]:
    """
    Get list of darker colors for hyperedges (to make them more visible)

    Returns:
        List of hex color strings
    """
    return [
        "#B76B00",      # Darker yellow
        "#009680",      # Darker cyan
        "#E86A00",      # Darker orange
        "#D95800",      # Darker orange-red
        "#006634",      # Darker green
        "#F5222D",      # Darker red
        "#8B4513",      # Darker brown
        "#4A5A8C",      # Darker blue
        "#4A6E90",      # Darker teal
        "#8B3A3A",      # Darker maroon
        "#3B4485"       # Darker indigo
    ]
