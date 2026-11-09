"""Small, styled HTML previews; values are escaped before rendering."""
from __future__ import annotations
from html import escape


def render_preview(data: dict | None, target: dict | None = None) -> str:
    if not data:
        return '<div class="dg-placeholder">Start writing <code>result = ...</code> in solution.py</div>'
    kind = data.get('kind')
    if kind == 'scalar':
        return ('<div class="dg-scalar"><span>' + escape(str(data.get('value', ''))) + '</span>'
                '<small>' + escape(str(data.get('type', 'scalar'))) + '</small></div>')
    cols = data.get('columns', [])
    rows = data.get('rows', [])
    index = data.get('index', [])
    mismatch = target is not None and target.get('kind') == kind
    result = ['<div class="dg-table-wrap"><table class="dg-table"><thead><tr>',
              '<th class="dg-index-head">' + escape(str(data.get('index_name', 'index'))) + '</th>']
    for j, col in enumerate(cols):
        differ = mismatch and (j >= len(target.get('columns', [])) or col != target['columns'][j])
        result.append('<th' + (' class="dg-diff"' if differ else '') + '>' + escape(str(col)) + '</th>')
    result.append('</tr></thead><tbody>')
    for i, row in enumerate(rows):
        bad_index = mismatch and (i >= len(target.get('index', [])) or index[i] != target['index'][i])
        result.append('<tr><th class="dg-index' + (' dg-diff' if bad_index else '') + '">' + escape(str(index[i])) + '</th>')
        for j, cell in enumerate(row):
            differs = mismatch and (i >= len(target.get('rows', [])) or
                j >= len(target['rows'][i]) or cell != target['rows'][i][j])
            result.append('<td' + (' class="dg-diff"' if differs else '') + '>' + escape(str(cell)) + '</td>')
        result.append('</tr>')
    result.append('</tbody></table></div>')
    if data.get('truncated'):
        result.append('<div class="dg-truncation">Preview truncated; grading uses full object.</div>')
    return ''.join(result)
