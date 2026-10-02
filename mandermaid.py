"""Mandermaid: semanticMap DSL -> deterministic coordinates -> SVG/HTML.
Python 3.10+, standard library only.
"""
from __future__ import annotations
import argparse
import html
import json
import math
from pathlib import Path
import sys
import unicodedata
from semantic_map_parser import parse, ParseError

DIRECTIONS = ('north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest')
VECTORS = {d: (math.sin(i * math.pi / 4), -math.cos(i * math.pi / 4)) for i, d in enumerate(DIRECTIONS)}


def solve(matrix, rhs):
    """Solve the positive-definite reduced graph Laplacian without dependencies."""
    a = [list(row) + [value] for row, value in zip(matrix, rhs)]
    n = len(a)
    for i in range(n):
        pivot = max(range(i, n), key=lambda j: abs(a[j][i]))
        a[i], a[pivot] = a[pivot], a[i]
        if abs(a[i][i]) < 1e-10:
            raise ValueError('layout system is singular')
        divisor = a[i][i]
        a[i] = [v / divisor for v in a[i]]
        for j in range(i + 1, n):
            factor = a[j][i]
            a[j] = [v - factor * w for v, w in zip(a[j], a[i])]
    result = [0.0] * n
    for i in reversed(range(n)):
        result[i] = a[i][-1] - sum(a[i][j] * result[j] for j in range(i + 1, n))
    return result


def node_width(label):
    units = sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in label)
    return max(112, units * 8 + 36)


def layout(model, unit=180.0):
    """Keep direction/distance as preferred relative offsets, independent of focus.
    Inconsistent cycles minimize squared offset error; return diagnostic residuals.
    Missing directions use a deterministic unoccupied octant, never alter the model.
    """
    if not math.isfinite(unit) or unit < 80:
        raise ValueError('unit must be a finite number >= 80')
    ids = sorted(n['id'] for n in model['nodes'])
    placements = model['placements']
    occupied = {}
    for p in placements:
        if p['direction']:
            occupied.setdefault(p['anchor'], set()).add(p['direction'])
            opposite = DIRECTIONS[(DIRECTIONS.index(p['direction']) + 4) % 8]
            occupied.setdefault(p['target'], set()).add(opposite)
    resolved = []
    # Canonical ordering keeps results stable when input statements are reordered.
    for p in sorted(placements, key=lambda p: (p['anchor'], p['target'], p['direction'] or '', p['distance'])):
        direction = p['direction']
        if direction is None:
            used = occupied.setdefault(p['anchor'], set())
            direction = next((d for d in DIRECTIONS if d not in used), DIRECTIONS[len(used) % 8])
            used.add(direction)
        dx, dy = VECTORS[direction]
        resolved.append({**p, 'resolved_direction': direction, 'dx': dx * unit * p['distance'], 'dy': dy * unit * p['distance']})
    adjacent = {node_id: set() for node_id in ids}
    for p in resolved:
        adjacent[p['anchor']].add(p['target'])
        adjacent[p['target']].add(p['anchor'])
    components = []
    unseen = set(ids)
    while unseen:
        seed = min(unseen)
        stack, component = [seed], set()
        while stack:
            node_id = stack.pop()
            if node_id in component:
                continue
            component.add(node_id)
            stack.extend(adjacent[node_id] - component)
        unseen -= component
        components.append(sorted(component))
    positions, cursor = {}, 0.0
    for component in components:
        # A numerical gauge only; not a semantic root.
        root, *free = component
        index = {node_id: i for i, node_id in enumerate(free)}
        matrix = [[0.0] * len(free) for _ in free]
        rx, ry = [0.0] * len(free), [0.0] * len(free)
        for p in resolved:
            if p['anchor'] not in component:
                continue
            coefficients = [(node_id, sign) for node_id, sign in ((p['anchor'], -1), (p['target'], 1)) if node_id != root]
            for node_id, sign in coefficients:
                i = index[node_id]
                rx[i] += sign * p['dx']
                ry[i] += sign * p['dy']
                for other, other_sign in coefficients:
                    matrix[i][index[other]] += sign * other_sign
        sx, sy = solve(matrix, rx), solve(matrix, ry)
        local = {root: (0.0, 0.0), **{node_id: (sx[i], sy[i]) for node_id, i in index.items()}}
        minimum = min(x for x, y in local.values())
        maximum = max(x for x, y in local.values())
        for node_id, (x, y) in local.items():
            positions[node_id] = (x - minimum + cursor, y)
        cursor += maximum - minimum + unit * 2
    warnings = []
    for p in resolved:
        ax, ay = positions[p['anchor']]
        bx, by = positions[p['target']]
        residual = math.hypot(bx - ax - p['dx'], by - ay - p['dy']) / unit
        p['residual'] = round(residual, 6)
        if residual > 0.05:
            warnings.append(f"placement {p['anchor']} -> {p['target']}: offset error {residual:.2f} units")
    labels = {n['id']: n['label'] for n in model['nodes']}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if abs(positions[a][0] - positions[b][0]) < (node_width(labels[a]) + node_width(labels[b])) / 2 + 8 and abs(positions[a][1] - positions[b][1]) < 56:
                warnings.append(f'overlapping nodes: {a}, {b}')
    return {'positions': {k: {'x': x, 'y': y} for k, (x, y) in positions.items()}, 'placements': resolved, 'warnings': warnings, 'unit': unit}


def render_svg(model, result, focus=None):
    labels = {n['id']: n['label'] for n in model['nodes']}
    focus = focus if focus is not None else model['focus']
    if focus is not None and focus not in labels:
        raise ValueError(f'unknown focus: {focus}')
    original = result['positions']
    if not original:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="240"><text x="40" y="80">Mandermaid: empty map</text></svg>'
    if focus:
        ox, oy = original[focus]['x'], original[focus]['y']
    else:
        ox = (min(p['x'] for p in original.values()) + max(p['x'] for p in original.values())) / 2
        oy = (min(p['y'] for p in original.values()) + max(p['y'] for p in original.values())) / 2
    positions = {k: (p['x'] - ox, p['y'] - oy) for k, p in original.items()}
    rx = max(abs(x) + node_width(labels[k]) / 2 for k, (x, y) in positions.items()) + 65
    ry = max(abs(y) + 26 for x, y in positions.values()) + 65
    width, height = max(640, 2 * rx), max(480, 2 * ry + 100)
    left, top = -width / 2, -(height - 100) / 2 - 100
    escape = html.escape
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc" width="{width:.0f}" height="{height:.0f}" viewBox="{left} {top} {width} {height}">',
             '<title id="title">Mandermaid semantic map</title>',
             f'<desc id="desc">Focus: {escape(labels.get(focus, "none"))}. Dashed lines: placement constraints. Solid lines: links.</desc>',
             f'<rect x="{left}" y="{top}" width="{width}" height="{height}" fill="#f7f9fc"/>',
             f'<text x="{left + 32}" y="{top + 38}" font-family="sans-serif" font-size="23" font-weight="700" fill="#172b4d">Mandermaid</text>',
             f'<text x="{left + 32}" y="{top + 66}" font-family="sans-serif" font-size="13" fill="#52657d">Focus: {escape(labels.get(focus, "none"))} · dashed: placement · solid: link</text>']
    def segment(a, b):
        ax, ay = positions[a]; bx, by = positions[b]
        dx, dy = bx - ax, by - ay
        def trim(node_id):
            return min(node_width(labels[node_id]) / 2 / abs(dx) if dx else float('inf'), 24 / abs(dy) if dy else float('inf'), 0.5)
        ta, tb = trim(a), trim(b)
        return ax + ta * dx, ay + ta * dy, bx - tb * dx, by - tb * dy
    for p in result['placements']:
        x1, y1, x2, y2 = segment(p['anchor'], p['target'])
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#a9b8ce" stroke-width="1.4" stroke-dasharray="5 5"/>')
        direction = p['direction'] or 'auto'
        caption = f'{direction} · {p["distance"]}'
        x, y = (x1 + x2) / 2, (y1 + y2) / 2 - 9
        caption_width = len(caption) * 6 + 8
        parts.append(f'<rect x="{x-caption_width/2}" y="{y-11}" width="{caption_width}" height="15" rx="3" fill="#f7f9fc"/>')
        parts.append(f'<text x="{x}" y="{y}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#63758e">{caption}</text>')
    for link in model['links']:
        x1, y1, x2, y2 = segment(link['source'], link['target'])
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#446a9a" stroke-width="2"/>')
    for node_id, (x, y) in positions.items():
        selected = node_id == focus
        w = node_width(labels[node_id])
        parts.append(f'<g data-node-id="{escape(node_id)}"><rect x="{x - w/2}" y="{y - 24}" width="{w}" height="48" rx="12" fill="{"#275bd6" if selected else "#ffffff"}" stroke="{"#275bd6" if selected else "#c3cfdf"}" stroke-width="1.5"/><text x="{x}" y="{y + 5}" text-anchor="middle" font-family="sans-serif" font-size="15" fill="{"#ffffff" if selected else "#243954"}">{escape(labels[node_id])}</text></g>')
    parts.append('</svg>')
    return '\n'.join(parts)


def render_html(model, result):
    views = {n['id']: render_svg(model, result, n['id']) for n in model['nodes']}
    data = json.dumps(views, ensure_ascii=False).replace('<', '\\u003c')
    chosen = model['focus'] or next(iter(views), '')
    options = ''.join(f'<option value="{html.escape(n["id"])}" {"selected" if n["id"] == chosen else ""}>{html.escape(n["label"])}</option>' for n in model['nodes'])
    warnings = ''.join(f'<li>{html.escape(w)}</li>' for w in result['warnings'])
    return f'''<!doctype html><html lang="ja"><meta charset="utf-8"><title>Mandermaid preview</title>
<style>body{{margin:0;background:#f7f9fc;color:#243954;font:15px system-ui,sans-serif}}header{{padding:16px 24px;background:white;border-bottom:1px solid #dce3ee;display:flex;gap:20px;align-items:center}}select{{font:inherit;padding:6px 12px}}#map{{padding:16px}}svg{{display:block;max-width:100%;height:auto;margin:auto}}.note{{margin:16px 24px;font-size:13px;color:#63758e}}</style>
<header><b>Mandermaid</b><label>Focus <select id="focus">{options}</select></label></header>
<p class="note">ノードをクリック、またはFocusを選択して視点を切り替えます。方角と距離の関係は維持します。</p>
<div id="map"></div><ul>{warnings}</ul>
<script>const views={data};const selector=document.getElementById('focus');const map=document.getElementById('map');function show(){{map.innerHTML=views[selector.value]||'';map.querySelectorAll('[data-node-id]').forEach(node=>{{node.style.cursor='pointer';node.onclick=()=>{{selector.value=node.dataset.nodeId;show()}}}})}}selector.onchange=show;show();</script></html>'''


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('file', type=Path)
    cli.add_argument('-o', '--output', type=Path, default=Path('map.svg'))
    cli.add_argument('--focus', help='override display focus without modifying input')
    cli.add_argument('--unit', type=float, default=180.0, help='pixels per distance unit (default: 180)')
    cli.add_argument('--layout-json', type=Path, help='also save coordinates and diagnostics')
    args = cli.parse_args()
    try:
        model = parse(args.file.read_text(encoding='utf-8'))
        result = layout(model, args.unit)
        if args.focus:
            if args.focus not in result['positions']:
                raise ValueError(f'unknown focus: {args.focus}')
            model['focus'] = args.focus
        output = render_html(model, result) if args.output.suffix.lower() == '.html' else render_svg(model, result)
        args.output.write_text(output, encoding='utf-8')
        if args.layout_json:
            args.layout_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        for warning in result['warnings']:
            print(f'warning: {warning}', file=sys.stderr)
        print(args.output)
        return 0
    except (OSError, ParseError, ValueError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
