"""
Graph visualization functions using D3.js (Bubble Sets - Web-UI 完全复刻版本)
"""
import networkx as nx
from pyvis.network import Network
from typing import Dict, List, Tuple, Optional
import json

# Web-UI 完全一致的配色方案
BUBBLE_COLORS = [
    '#F6BD16', '#00C9C9', '#F08F56', '#D580FF',
    '#FF3D00', '#16f69c', '#004ac9', '#f056d1',
    '#a680ff', '#c8ff00'
]

ENTITY_TYPE_COLORS = {
    'PERSON': '#00C9C9',
    'CONCEPT': '#a68fff',
    'ORGANIZATION': '#F08F56',  # 修正拼写错误
    'LOCATION': '#16f69c',
    'EVENT': '#004ac9',
    'PRODUCT': '#f056d1',
    'DEFAULT': '#8566CC'
}


def create_d3_bubble_sets_hypergraph(
    vertices: Dict[str, Dict],
    hyperedges: Dict[str, Dict],
    highlight_vertex: Optional[str] = None,
    show_hyperedge_labels: bool = True,
    width: int = 800,
    height: int = 700
) -> str:
    """
    Web-UI 完全复刻的 Bubble Sets 可视化
    """
    # Web-UI 配色
    entity_type_colors = ENTITY_TYPE_COLORS
    bubble_colors = BUBBLE_COLORS

    # 准备顶点数据（添加聚类信息）
    vertices_data = []
    vertex_map = {}
    entity_clusters = {}  # 按实体类型分组

    for idx, (vertex_id, vertex_data) in enumerate(vertices.items()):
        entity_type = vertex_data.get('entity_type', 'default').upper()
        color = entity_type_colors.get(entity_type, entity_type_colors['DEFAULT'])

        # 构建聚类分组
        if entity_type not in entity_clusters:
            entity_clusters[entity_type] = []
        entity_clusters[entity_type].append(idx)

        vertices_data.append({
            'id': vertex_id,
            'name': vertex_id,
            'entity_type': entity_type,
            'description': vertex_data.get('description', ''),
            'additional_properties': vertex_data.get('additional_properties', ''),
            'color': color,
            'cluster': entity_type,
            'highlight': highlight_vertex == vertex_id
        })
        vertex_map[vertex_id] = idx

    # 准备超边数据
    hyperedges_data = []
    for idx, (edge_id, edge_data) in enumerate(hyperedges.items()):
        vertices_list = edge_data.get('vertices', [])
        member_indices = [vertex_map[v] for v in vertices_list if v in vertex_map]

        if member_indices:
            hyperedges_data.append({
                'id': f"he_{idx}",
                'members': member_indices,
                'label': edge_data.get('keywords', f'HE-{idx+1}'),
                'color': bubble_colors[idx % len(bubble_colors)],
                'keywords': edge_data.get('keywords', ''),
                'weight': edge_data.get('weight', 5)
            })

    vertices_json = json.dumps(vertices_data)
    hyperedges_json = json.dumps(hyperedges_data)
    entity_clusters_json = json.dumps(entity_clusters)
    show_labels_str = str(show_hyperedge_labels).lower()

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Bubble Sets Hypergraph - Web-UI Style</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            margin: 0;
            padding: 0;
            background-color: #fafafa;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            overflow: hidden;
        }}
        #container {{
            width: {width}px;
            height: {height}px;
            position: relative;
        }}
        svg {{
            width: 100%;
            height: 100%;
        }}

        /* 节点样式 - Web-UI 风格 */
        .node {{
            cursor: pointer;
            transition: opacity 0.2s ease;
        }}
        .node circle {{
            stroke-width: 2px;
            stroke: #fff;
        }}
        .node text {{
            font-size: 12px;
            font-weight: 600;
            pointer-events: none;
            text-anchor: middle;
            fill: #333;
            /* 文字光晕，保证在彩色气泡中清晰可见 */
            paint-order: stroke;
            stroke: rgba(255, 255, 255, 0.9);
            stroke-width: 3px;
            stroke-linecap: round;
            stroke-linejoin: round;
        }}
        .node:hover circle {{
            stroke: #000;
            stroke-width: 3px;
        }}
        .node.highlighted circle {{
            fill: #000 !important;
            stroke: #fff !important;
            stroke-width: 4px;
            r: 30 !important;
        }}
        .node.highlighted text {{
            font-weight: 700;
            fill: #000;
        }}

        /* Bubble Sets 样式 - 完全复刻 Web-UI */
        .bubble-path {{
            fill-opacity: 0.25;      /* 透明度增加，更容易看到 */
            stroke-opacity: 0.6;      /* 边框透明度增加，更容易看到 */
            stroke-width: 70px;      /* 超大描边，形成完美包裹 */
            stroke-linejoin: round;  /* 折角变圆角 */
            stroke-linecap: round;   /* 端点变圆角 */
            cursor: pointer;
            transition: all 0.25s ease;
        }}
        .bubble-path:hover {{
            fill-opacity: 0.4;       /* 悬浮时更明显 */
            stroke-opacity: 0.8;
            stroke-width: 80px;       /* 悬浮时边框更粗 */
        }}

        /* Tooltip 样式 */
        .tooltip {{
            position: absolute;
            background: rgba(255, 255, 255, 0.95);
            color: #333;
            padding: 12px;
            border-radius: 6px;
            font-size: 13px;
            max-width: 300px;
            pointer-events: none;
            z-index: 1000;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
            border: 1px solid #e8e8e8;
            font-family: inherit;
        }}
        .tooltip h4 {{
            margin: 0 0 8px 0;
            font-size: 16px;
            color: #1890ff;
            border-bottom: 1px solid #e8e8e8;
            padding-bottom: 4px;
        }}
        .tooltip p {{
            margin: 6px 0;
            line-height: 1.5;
            color: #555;
        }}
        .tooltip strong {{
            color: #1890ff;
        }}

        /* 控件样式 */
        .legend {{
            position: absolute;
            bottom: 20px;
            left: 20px;
            background: rgba(255, 255, 255, 0.95);
            padding: 16px;
            border-radius: 8px;
            border: 1px solid #e8e8e8;
            font-size: 12px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            max-width: 250px;
            max-height: 300px;
            overflow-y: auto;
        }}
        .legend-title {{
            margin: 0 0 12px 0;
            font-size: 14px;
            font-weight: 700;
            color: #333;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin: 8px 0;
            padding: 4px;
            border-radius: 4px;
            background: #f5f5f5;
            cursor: pointer;
            transition: background 0.2s;
        }}
        .legend-item:hover {{
            background: #e8e8e8;
        }}
        .legend-color {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
            margin-right: 12px;
            border: 1px solid rgba(0, 0, 0, 0.1);
        }}
        .legend-label {{
            font-size: 12px;
            color: #333;
        }}
        .legend-count {{
            margin-left: auto;
            background: #1890ff;
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
        }}

        /* 缩放控件 */
        .zoom-controls {{
            position: absolute;
            top: 20px;
            right: 20px;
            display: flex;
            gap: 8px;
        }}
        .zoom-btn {{
            background: white;
            border: 1px solid #d9d9d9;
            padding: 8px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            color: #555;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            transition: all 0.2s;
            min-width: 40px;
        }}
        .zoom-btn:hover {{
            background: #fff;
            border-color: #1890ff;
            color: #1890ff;
        }}

        /* 加载状态 */
        .loading-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255, 255, 255, 0.9);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 100;
        }}
        .loading-spinner {{
            width: 40px;
            height: 40px;
            border: 3px solid #e8e8e8;
            border-top-color: #1890ff;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }}
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
    </style>
</head>
<body>
    <div id="container">
        <svg id="graph"></svg>
        <div id="tooltip" class="tooltip" style="display: none;"></div>
        <div class="zoom-controls">
            <button class="zoom-btn" onclick="zoomIn()" title="放大">+</button>
            <button class="zoom-btn" onclick="zoomOut()">−</button>
            <button class="zoom-btn" onclick="resetZoom()">⟲</button>
            <button class="zoom-btn" onclick="fitToView()">⛶</button>
        </div>
        <div class="legend" id="legend">
            <div class="legend-title">📊 图例</div>
        </div>
    </div>

    <script>
        // 数据
        const vertices = {vertices_json};
        const hyperedges = {hyperedges_json};
        const entityClusters = {entity_clusters_json};
        const showLabels = {show_labels_str};

        console.log('Vertices count:', vertices.length);
        console.log('Hyperedges count:', hyperedges.length);
        console.log('First vertex:', vertices[0]);

        const svg = d3.select('#graph');
        const width = {width};
        const height = {height};
        const tooltip = d3.select('#tooltip');

        // 为节点设置初始位置（围绕中心随机分布）
        vertices.forEach(v => {{
            v.x = width / 2 + (Math.random() - 0.5) * 200;
            v.y = height / 2 + (Math.random() - 0.5) * 200;
        }});

        // 图层顺序：气泡 → 标签 → 节点
        const mainGroup = svg.append('g');
        const bubblesGroup = mainGroup.append('g').attr('class', 'bubbles');
        const labelsGroup = mainGroup.append('g').attr('class', 'bubble-labels');
        const nodesGroup = mainGroup.append('g').attr('class', 'nodes');

        // 缩放
        const zoom = d3.zoom()
            .scaleExtent([0.1, 5])
            .on('zoom', (event) => {{
                mainGroup.attr('transform', event.transform);
            }});
        svg.call(zoom);

        // Force Atlas2 风格的力导向布局
        const simulation = d3.forceSimulation(vertices)
            .force('charge', d3.forceManyBody().strength(-600))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collide', d3.forceCollide().radius(45))
            .force('x', d3.forceX(width / 2).strength(0.03))
            .force('y', d3.forceY(height / 2).strength(0.03))
            .velocityDecay(0.25)  // 减缓衰减，让气泡有更多时间形成
            .alpha(1)  // 设置初始能量
            .alphaMin(0.01);  // 降低最小alpha，让仿真持续更久

        // 绘制节点
        const node = nodesGroup.selectAll('.node')
            .data(vertices)
            .enter()
            .append('g')
            .attr('class', d => d.highlight ? 'node highlighted' : 'node')
            .call(d3.drag()
                .on('start', dragstarted)
                .on('drag', dragged)
                .on('end', dragended));

        console.log('Created nodes:', node.size());

        node.append('circle')
            .attr('r', d => d.highlight ? 30 : 22)
            .attr('fill', d => d.color)
            .attr('stroke', d => d3.color(d.color).darker(0.3));

        node.append('text')
            .attr('dy', 5)
            .text(d => d.name);

        // 设置节点初始位置（立即显示）
        node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);

        // Bubble Sets 路径计算 - Web-UI 风格
        function computeBubblePath(nodes) {{
            if (!nodes || nodes.length === 0) return "";

            // 单个节点：画一条长度为0的线（靠圆角stroke撑开成圆）
            if (nodes.length === 1) {{
                return `M ${{nodes[0].x}},${{nodes[0].y}} L ${{nodes[0].x + 0.01}},${{nodes[0].y}}`;
            }}

            // 两个节点：直接连线（靠圆角stroke形成药丸形状）
            if (nodes.length === 2) {{
                return `M ${{nodes[0].x}},${{nodes[0].y}} L ${{nodes[1].x}},${{nodes[1].y}}`;
            }}

            // 三个及以上：凸包
            let points = nodes.map(n => [n.x, n.y]);

            // 去重
            points = points.filter((p, i) => {{
                return points.findIndex(q => q[0] === p[0] && q[1] === p[1]) === i;
            }});

            let hull = d3.polygonHull(points);

            if (!hull) {{
                // 如果凸包失败，返回所有点的路径
                const lineGen = d3.line();
                return lineGen(points) + " Z";
            }}

            // 使用平滑曲线
            const lineGen = d3.line()
                .curve(d3.curveCatmullRomClosed)
                .alpha(0.3);
            return lineGen(hull);
        }}

        // 创建气泡
        console.log('Creating bubbles, hyperedges count:', hyperedges.length);
        const bubbles = hyperedges.map((he, i) => {{
            const group = bubblesGroup.append('g')
                .attr('data-id', i);

            const path = group.append('path')
                .attr('class', 'bubble-path')
                .attr('fill', he.color)
                .attr('stroke', he.color);

            // 交互：悬浮时提升到顶层，淡化其他气泡
            path.on('mouseover', function() {{
                d3.select(this.parentNode).raise();

                // 淡化其他气泡
                bubblesGroup.selectAll('.bubble')
                    .filter((d, j) => j !== i)
                    .style('opacity', 0.15);
                d3.select(this.parentNode).style('opacity', 1);
            }});

            path.on('mouseout', function() {{
                bubblesGroup.selectAll('.bubble').style('opacity', 1);
            }});

            const labelGroup = labelsGroup.append('g')
                .attr('class', 'bubble-label-group')
                .attr('data-id', i);

            const labelText = labelGroup.append('text')
                .attr('class', 'bubble-label')
                .style('fill', d3.color(he.color).darker(1.5));

            if (showLabels) {{
                labelText.text(he.label);
            }}

            return {{
                id: i,
                path: path,
                labelGroup: labelGroup,
                members: he.members,
                data: he
            }};
        }});

        console.log('Created', bubbles.length, 'bubbles');
        console.log('First bubble members:', bubbles[0]?.members);

        // 初始绘制气泡（在仿真开始前）
        bubbles.forEach(bubble => {{
            const members = bubble.members.map(idx => vertices[idx]);
            const pathStr = computeBubblePath(members);
            bubble.path.attr('d', pathStr);
            console.log('Bubble', bubble.id, 'path:', pathStr.substring(0, 50) + '...');
        }});

        // 动画循环
        simulation.on('tick', () => {{
            node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);

            // 更新气泡
            bubbles.forEach(bubble => {{
                const members = bubble.members.map(idx => vertices[idx]);
                bubble.path.attr('d', computeBubblePath(members));

                // 更新标签位置（气泡上方）
                if (showLabels && members.length > 0) {{
                    const centerX = members.reduce((sum, m) => sum + m.x, 0) / members.length;
                    const minY = d3.min(members, d => d.y) - 40;
                    bubble.labelGroup.attr('transform', `translate(${{centerX}},${{minY}})`);
                }}
            }});
        }});

        // 悬停提示
        node.on('mouseover', function(event, d) {{
            let content = `<h4>${{d.name}}</h4>`;
            content += `<p><strong>类型:</strong> <span style="background:${{d.color}};color:#fff;padding:2px 6px;border-radius:3px;">${{d.entity_type}}</span></p>`;

            if (d.description) {{
                const shortDesc = d.description.split('<SEP>')[0].substring(0, 100);
                content += `<p><strong>描述:</strong> ${{shortDesc}}...</p>`;
            }}

            if (d.additional_properties) {{
                const props = d.additional_properties.split('<SEP>').filter(p => p.trim()).slice(0, 2);
                if (props.length > 0) {{
                    content += `<p><strong>属性:</strong></p>`;
                    props.forEach(p => {{
                        content += `<p style="margin:2px 0 2px 10px;">• ${{p}}</p>`;
                    }});
                }}
            }}

            tooltip.html(content)
                .style('display', 'block')
                .style('left', (event.pageX + 15) + 'px')
                .style('top', (event.pageY - 10) + 'px');
        }}).on('mouseout', () => {{
            tooltip.style('display', 'none');
        }});

        // 拖拽控制
        function dragstarted(event, d) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }}

        function dragged(event, d) {{
            d.fx = event.x;
            d.fy = event.y;
        }}

        function dragended(event, d) {{
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }}

        // 缩放控制
        function zoomIn() {{
            svg.transition().call(zoom.scaleBy, 1.4);
        }}

        function zoomOut() {{
            svg.transition().call(zoom.scaleBy, 0.7);
        }}

        function resetZoom() {{
            svg.transition().call(zoom.transform, d3.zoomIdentity);
        }}

        function fitToView() {{
            if (vertices.length === 0) return;

            const xExtent = d3.extent(vertices, d => d.x);
            const yExtent = d3.extent(vertices, d => d.y);
            const padding = 50;

            const k = Math.min(
                width / (xExtent[1] - xExtent[0] + padding * 2),
                height / (yExtent[1] - yExtent[0] + padding * 2)
            );

            const tx = width / 2 - (xExtent[0] + xExtent[1]) / 2 * k;
            const ty = height / 2 - (yExtent[0] + yExtent[1]) / 2 * k;

            svg.transition().call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(k));
        }}

        // 构建图例
        function buildLegend() {{
            const legend = d3.select('#legend');

            // 统计实体类型
            const entityCounts = {{}};
            vertices.forEach(v => {{
                entityCounts[v.entity_type] = (entityCounts[v.entity_type] || 0) + 1;
            }});

            const colorMap = {{}};
            Object.entries(ENTITY_TYPE_COLORS).forEach(([type, color]) => {{
                colorMap[type] = color;
            }});

            // 添加实体类型项
            Object.entries(entityCounts).forEach(([type, count]) => {{
                const itemGroup = legend.append('div').attr('class', 'legend-item');
                itemGroup.append('div')
                    .attr('class', 'legend-color')
                    .style('background-color', colorMap[type] || ENTITY_TYPE_COLORS['DEFAULT']);
                itemGroup.append('div')
                    .attr('class', 'legend-label')
                    .text(type);
                itemGroup.append('div')
                    .attr('class', 'legend-count')
                    .text(count);
            }});

            // 添加超边统计
            if (hyperedges.length > 0) {{
                legend.append('div')
                    .style('margin-top: 12px; padding-top: 12px; border-top: 1px dashed #ddd;')
                    .text(`🔷 超边数量: ${{hyperedges.length}}`);
            }}
        }}

        // 初始化
        buildLegend();

        // 适应视图
        setTimeout(fitToView, 500);
    </script>
</body>
</html>
"""
    return html


def create_d3_vertex_details(
    vertices: Dict[str, Dict],
    hyperedges: Dict[str, Dict],
    selected_vertex: str,
    width: int = 1200,
    height: int = 650
) -> str:
    """
    顶点详情页面 - Web-UI 风格
    左侧：超图可视化，右侧：顶点信息面板
    """
    # 获取顶点数据
    vertex_data = vertices.get(selected_vertex, {})
    entity_type = vertex_data.get('entity_type', 'default').upper()
    entity_color = ENTITY_TYPE_COLORS.get(entity_type, ENTITY_TYPE_COLORS['DEFAULT'])
    description = vertex_data.get('description', '').replace('<SEP>', ' | ')
    additional_props = vertex_data.get('additional_properties', '')
    properties_list = [p for p in additional_props.split('<SEP>') if p.strip()]

    # 获取相关超边
    related_hyperedges = []
    related_vertices = {selected_vertex}

    for idx, (edge_id, edge_data) in enumerate(hyperedges.items()):
        vertices_list = edge_data.get('vertices', [])
        if selected_vertex in vertices_list:
            related_hyperedges.append({
                'id': idx,
                'members': vertices_list,
                'label': edge_data.get('keywords', f'HE-{idx+1}'),
                'color': BUBBLE_COLORS[idx % len(BUBBLE_COLORS)],
                'keywords': edge_data.get('keywords', ''),
                'summary': edge_data.get('summary', ''),
                'weight': edge_data.get('weight', 5)
            })
            related_vertices.update(vertices_list)

    # 准备顶点数据
    vertices_data = []
    vertex_map = {}
    for idx, vertex_id in enumerate(related_vertices):
        v_data = vertices.get(vertex_id, {})
        v_type = v_data.get('entity_type', 'default').upper()
        v_color = ENTITY_TYPE_COLORS.get(v_type, ENTITY_TYPE_COLORS['DEFAULT'])

        vertices_data.append({
            'id': vertex_id,
            'name': vertex_id,
            'entity_type': v_type,
            'description': v_data.get('description', ''),
            'color': v_color,
            'highlight': vertex_id == selected_vertex
        })
        vertex_map[vertex_id] = idx

    # 准备超边数据
    hyperedges_data = []
    for he in related_hyperedges:
        member_indices = [vertex_map[v] for v in he['members'] if v in vertex_map]
        if member_indices:
            he_copy = he.copy()
            he_copy['members'] = member_indices
            hyperedges_data.append(he_copy)

    vertices_json = json.dumps(vertices_data)
    hyperedges_json = json.dumps(hyperedges_data)
    related_hyperedges_json = json.dumps(related_hyperedges)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Vertex Details - {selected_vertex}</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: #fafafa;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        .header {{
            background: linear-gradient(135deg, #1890ff 0%, #096dd9 100%);
            color: white;
            padding: 16px 24px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }}
        .header h1 {{
            margin: 0;
            font-size: 20px;
            font-weight: 600;
            color: white;
        }}
        .main-container {{
            display: flex;
            flex: 1;
            overflow: hidden;
        }}
        .graph-container {{
            flex: 1;
            position: relative;
            background: #fff;
        }}
        .side-panel {{
            width: 380px;
            background: #fff;
            border-left: 1px solid #e8e8e8;
            display: flex;
            flex-direction: column;
            box-shadow: -2px 0 8px rgba(0, 0, 0, 0.05);
            z-index: 10;
        }}
        #graph {{
            width: 100%;
            height: 100%;
        }}
        .panel-content {{
            padding: 24px;
            overflow-y: auto;
            flex: 1;
        }}
        .panel-section {{
            margin-bottom: 24px;
        }}
        .panel-section h3 {{
            margin: 0 0 16px 0;
            color: #333;
            font-size: 16px;
            font-weight: 700;
            border-bottom: 2px solid #e8e8e8;
            padding-bottom: 8px;
        }}
        .info-row {{
            display: flex;
            margin-bottom: 14px;
            align-items: flex-start;
        }}
        .info-label {{
            font-weight: 600;
            color: #666;
            min-width: 100px;
            font-size: 13px;
        }}
        .info-value {{
            color: #333;
            flex: 1;
            font-size: 13px;
            font-family: monospace;
            background: #f5f5f5;
            padding: 6px 10px;
            border-radius: 4px;
        }}
        .type-tag {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 6px;
            color: white;
            font-weight: 600;
            font-size: 12px;
            background: {entity_color};
        }}
        .description {{
            background: #f0f5ff;
            padding: 14px;
            border-radius: 6px;
            border-left: 4px solid #1890ff;
            line-height: 1.6;
            font-size: 13px;
            color: #333;
        }}
        .properties-list {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        .properties-list li {{
            background: #f5f5f5;
            padding: 10px 14px;
            border-radius: 4px;
            margin-bottom: 8px;
            border-left: 4px solid #52c41a;
            font-size: 13px;
            color: #555;
        }}
        .hyperedge-card {{
            background: #fff;
            padding: 14px;
            border-radius: 8px;
            margin-bottom: 12px;
            border-left: 5px solid;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
            border-top: 1px solid #f0f0f0;
            border-right: 1px solid #f0f0f0;
            border-bottom: 1px solid #f0f0f0;
        }}
        .hyperedge-card h4 {{
            margin: 0 0 8px 0;
            font-size: 14px;
            color: #333;
        }}
        .hyperedge-card p {{
            margin: 6px 0;
            font-size: 12px;
            color: #666;
            line-height: 1.5;
        }}
        .stats {{
            display: flex;
            gap: 16px;
            margin-bottom: 24px;
        }}
        .stat-item {{
            background: linear-gradient(135deg, #1890ff 0%, #096dd9 100%);
            color: white;
            padding: 16px;
            border-radius: 8px;
            text-align: center;
            flex: 1;
            box-shadow: 0 2px 6px rgba(24, 144, 255, 0.2);
        }}
        .stat-value {{
            font-size: 28px;
            font-weight: 800;
            margin-bottom: 4px;
        }}
        .stat-label {{
            font-size: 11px;
            font-weight: 600;
            opacity: 0.9;
        }}
        .node {{
            cursor: pointer;
        }}
        .node circle {{
            stroke-width: 2px;
            stroke: #fff;
        }}
        .node.highlighted circle {{
            fill: #000 !important;
            stroke: #fff !important;
            stroke-width: 4px;
            r: 35 !important;
        }}
        .node text {{
            font-size: 12px;
            font-weight: 600;
            text-anchor: middle;
            fill: #333;
            paint-order: stroke;
            stroke: rgba(255, 255, 255, 0.9);
            stroke-width: 3px;
        }}
        .bubble-path {{
            fill-opacity: 0.25;
            stroke-opacity: 0.6;
            stroke-width: 70px;
            stroke-linejoin: round;
            stroke-linecap: round;
            cursor: pointer;
            transition: all 0.25s ease;
        }}
        .bubble-path:hover {{
            fill-opacity: 0.4;
            stroke-opacity: 0.8;
            stroke-width: 80px;
        }}
        .bubble-label {{
            font-size: 10px;
            font-weight: 700;
            text-anchor: middle;
            fill: #555;
            pointer-events: none;
            paint-order: stroke;
            stroke: rgba(255, 255, 255, 0.95);
            stroke-width: 2px;
        }}
        .zoom-controls {{
            position: absolute;
            top: 15px;
            left: 15px;
            display: flex;
            gap: 8px;
        }}
        .zoom-btn {{
            background: white;
            border: 1px solid #d9d9d9;
            padding: 8px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            color: #555;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        .zoom-btn:hover {{
            background: #f0f5ff;
            border-color: #1890ff;
            color: #1890ff;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 顶点详情 - {selected_vertex}</h1>
    </div>
    <div class="main-container">
        <div class="graph-container">
            <svg id="graph"></svg>
            <div class="zoom-controls">
                <button class="zoom-btn" onclick="zoomIn()">+</button>
                <button class="zoom-btn" onclick="zoomOut()">−</button>
                <button class="zoom-btn" onclick="resetZoom()">⟲</button>
            </div>
        </div>
        <div class="side-panel">
            <div class="panel-content">
                <div class="stats">
                    <div class="stat-item">
                        <div class="stat-value">{len(vertices_data)-1}</div>
                        <div class="stat-label">相关顶点</div>
                    </div>
                    <div class="stat-item" style="background: linear-gradient(135deg, #52c41a 0%, #389e0d 100%);">
                        <div class="stat-value">{len(related_hyperedges)}</div>
                        <div class="stat-label">关联超边</div>
                    </div>
                </div>
                <div class="panel-section">
                    <h3>📋 顶点信息</h3>
                    <div class="info-row">
                        <span class="info-label">顶点 ID:</span>
                        <span class="info-value">{selected_vertex}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">实体类型:</span>
                        <span><span class="type-tag">{entity_type}</span></span>
                    </div>
                </div>
                <div class="panel-section">
                    <h3>📝 语义描述</h3>
                    <div class="description">{description or '暂无描述'}</div>
                </div>
                {f'''<div class="panel-section">
                    <h3>🏷️ 提取属性</h3>
                    <ul class="properties-list">
                        {"".join(f'<li>{prop}</li>' for prop in properties_list)}
                    </ul>
                </div>''' if properties_list else ''}
                <div class="panel-section">
                    <h3>🔷 关联超边</h3>
                    <div id="hyperedges-list"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const vertices = {vertices_json};
        const hyperedges = {hyperedges_json};
        const relatedHyperedges = {related_hyperedges_json};

        const svg = d3.select('#graph');
        const container = svg.node().parentNode;
        let graphWidth = container.clientWidth;
        let graphHeight = container.clientHeight;

        // 为节点设置初始位置
        vertices.forEach(v => {{
            v.x = graphWidth / 2 + (Math.random() - 0.5) * 200;
            v.y = graphHeight / 2 + (Math.random() - 0.5) * 200;
        }});

        const mainGroup = svg.append('g');
        const bubblesGroup = mainGroup.append('g').attr('class', 'bubbles');
        const labelsGroup = mainGroup.append('g').attr('class', 'bubble-labels');
        const nodesGroup = mainGroup.append('g').attr('class', 'nodes');

        const zoom = d3.zoom().scaleExtent([0.1, 5]).on('zoom', e => mainGroup.attr('transform', e.transform));
        svg.call(zoom);

        const simulation = d3.forceSimulation(vertices)
            .force('charge', d3.forceManyBody().strength(-700))
            .force('center', d3.forceCenter(graphWidth / 2, graphHeight / 2))
            .force('collide', d3.forceCollide().radius(d => d.highlight ? 70 : 50))
            .force('x', d3.forceX(graphWidth / 2).strength(0.05))
            .force('y', d3.forceY(graphHeight / 2).strength(0.05))
            .velocityDecay(0.25)
            .alpha(1)
            .alphaMin(0.01);

        const node = nodesGroup.selectAll('.node').data(vertices).enter().append('g')
            .attr('class', d => d.highlight ? 'node highlighted' : 'node')
            .call(d3.drag().on('start', dragstarted).on('drag', dragged).on('end', dragended));

        node.append('circle')
            .attr('r', d => d.highlight ? 35 : 25)
            .attr('fill', d => d.color)
            .attr('stroke', d => d.highlight ? '#000' : d3.color(d.color).darker(0.3));

        node.append('text').attr('dy', 5).text(d => d.name);

        // 设置节点初始位置
        node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);

        function computeBubblePath(nodes) {{
            if (!nodes || nodes.length === 0) return "";
            if (nodes.length === 1) {{
                return `M ${{nodes[0].x}},${{nodes[0].y}} L ${{nodes[0].x + 0.01}},${{nodes[0].y}}`;
            }}
            if (nodes.length === 2) {{
                return `M ${{nodes[0].x}},${{nodes[0].y}} L ${{nodes[1].x}},${{nodes[1].y}}`;
            }}
            let points = nodes.map(n => [n.x, n.y]);
            // 去重
            points = points.filter((p, i) => {{
                return points.findIndex(q => q[0] === p[0] && q[1] === p[1]) === i;
            }});
            let hull = d3.polygonHull(points);
            if (!hull) {{
                const lineGen = d3.line();
                return lineGen(points) + " Z";
            }}
            const lineGen = d3.line().curve(d3.curveCatmullRomClosed).alpha(0.3);
            return lineGen(hull);
        }}

        const bubbles = hyperedges.map((he, i) => {{
            const group = bubblesGroup.append('g');
            const path = group.append('path').attr('class', 'bubble-path').attr('fill', he.color).attr('stroke', he.color);
            path.on('mouseover', function() {{ d3.select(this.parentNode).raise(); }});

            const labelGroup = labelsGroup.append('g').attr('class', 'bubble-label-group');
            labelGroup.append('text').attr('class', 'bubble-label').style('fill', d3.color(he.color).darker(1.5)).text(he.label);

            return {{ path: path, labelGroup: labelGroup, members: he.members, data: he }};
        }});

        // 初始绘制气泡
        bubbles.forEach(bubble => {{
            const members = bubble.members.map(idx => vertices[idx]);
            bubble.path.attr('d', computeBubblePath(members));
        }});

        simulation.on('tick', () => {{
            node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
            bubbles.forEach(bubble => {{
                const members = bubble.members.map(idx => vertices[idx]);
                bubble.path.attr('d', computeBubblePath(members));
                if (members.length > 0) {{
                    const centerX = members.reduce((sum, m) => sum + m.x, 0) / members.length;
                    const minY = d3.min(members, d => d.y) - 40;
                    bubble.labelGroup.attr('transform', `translate(${{centerX}},${{minY}})`);
                }}
            }});
        }});

        const hList = document.getElementById('hyperedges-list');
        relatedHyperedges.forEach((he, i) => {{
            const card = document.createElement('div');
            card.className = 'hyperedge-card';
            card.style.borderLeftColor = he.color;
            card.innerHTML = `
                <h4>${{he.label}}</h4>
                <p><strong>关键词:</strong> ${{he.keywords || 'N/A'}}</p>
                <p><strong>成员:</strong> ${{he.members.join(', ')}}</p>
            `;
            hList.appendChild(card);
        }});

        function dragstarted(event, d) {{ if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }}
        function dragged(event, d) {{ d.fx = event.x; d.fy = event.y; }}
        function dragended(event, d) {{ if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }}
        function zoomIn() {{ svg.transition().call(zoom.scaleBy, 1.3); }}
        function zoomOut() {{ svg.transition().call(zoom.scaleBy, 0.7); }}
        function resetZoom() {{ svg.transition().call(zoom.transform, d3.zoomIdentity); }}
    </script>
</body>
</html>
"""
    return html


def create_pyvis_graph_comparison(
    vertices: Dict[str, Dict],
    hyperedges: Dict[str, Dict]
) -> str:
    """
    图形对比页面 - 返回两个完整 HTML
    """
    entity_type_colors = ENTITY_TYPE_COLORS
    bubble_colors = BUBBLE_COLORS

    def build_network(is_hyper=False):
        net = Network(
            height="600px",
            width="100%",
            bgcolor="#fafcff" if not is_hyper else "#f0fdf4",
            font_color="#333",
            directed=False,
            notebook=False
        )
        net.set_options('{"physics": {"forceAtlas2Based": {"gravitationalConstant": -30, "centralGravity": 0.01, "springLength": 150}}}')

        for v_id, v_data in vertices.items():
            color = entity_type_colors.get(v_data.get('entity_type', 'default').upper(), entity_type_colors['DEFAULT'])
            net.add_node(v_id, label=str(v_id), color=color, size=20)

        edge_index = 0
        for edge_id, edge_data in hyperedges.items():
            v_list = edge_data.get('vertices', [])
            e_color = bubble_colors[edge_index % len(bubble_colors)]
            keywords = edge_data.get('keywords', f'HE-{edge_index}')
            for i in range(len(v_list) - 1):
                if v_list[i] in vertices and v_list[i + 1] in vertices:
                    if is_hyper:
                        net.add_edge(v_list[i], v_list[i+1], color=e_color, width=3, title=f"Hyperedge: {keywords}", label=f"HE-{edge_index}")
                    else:
                        net.add_edge(v_list[i], v_list[i+1], color=e_color, width=2)
            edge_index += 1
        return net

    return json.dumps({
        "graph": build_network(False).generate_html(),
        "hyper": build_network(True).generate_html()
    })


def create_networkx_graph(vertices: Dict[str, Dict], hyperedges: Dict[str, Dict]) -> nx.Graph:
    """创建 NetworkX 图"""
    G = nx.Graph()
    for v_id, v_data in vertices.items():
        G.add_node(v_id, entity_type=v_data.get('entity_type', 'default'), description=v_data.get('description', ''))
    for edge_data in hyperedges.values():
        v_list = edge_data.get('vertices', [])
        for i in range(len(v_list) - 1):
            if v_list[i] in vertices and v_list[i+1] in vertices:
                G.add_edge(v_list[i], v_list[i+1])
    return G
