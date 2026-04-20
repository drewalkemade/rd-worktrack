/**
 * canvas.jsx — React Flow canvas with all workboard nodes.
 *
 * Layout:
 *   Left        = shared inputs (Employees, Timesheets)
 *   Top lane    = Week 1
 *   Bottom lane = Week 2
 *   Right       = exports
 *
 * PDF nodes (Payroll PDF, Travel PDF) are clickable — they show the imported
 * filename on the node and open a focused panel showing only the extracted
 * data from that PDF.
 *
 * Reconciliation is split into three nodes per week:
 *   Compare  — run weekly verification, see approved vs timesheet side-by-side
 *   Correct  — apply day-level corrections, handle Sunday exceptions
 *   Verify   — final per-employee sign-off after corrections
 *
 * Node states from the API are { state, summary } objects.
 * state   = "idle" | "partial" | "complete"
 * summary = short label (or filename for PDF nodes)
 */
import { useCallback, useEffect } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState, MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import WorkboardNode from './nodes/WorkboardNode'

const nodeTypes = { workboard: WorkboardNode }

// Named outputs for nodes that fan out to multiple targets.
const NODE_OUTPUTS = {
  timesheets: [
    { id: 'week1', label: 'Wk 1' },
    { id: 'week2', label: 'Wk 2' },
  ],
}

// ── Node definitions ──────────────────────────────────────────────────────────
// [id, label, color, x, y, width, badge, hasInput, hasOutput, infoOnly]
const NODE_DEFS = [
  // Shared
  ['employees',         'Employees',         'purple', 20,   290, 170, null,   false, true,  false],
  ['timesheets',        'Timesheets',        'green',  20,   150, 170, null,   false, true,  false],

  // Week 1 — top lane
  ['w1_payroll_pdf',    'Payroll PDF',       'blue',   225,  40,  135, 'Wk 1', true,  true,  false],
  ['w1_travel_pdf',     'Travel PDF',        'blue',   225,  120, 135, 'Wk 1', true,  true,  false],
  ['w1_approved_hours', 'Approved Hours',    'blue',   410,  70,  165, 'Wk 1', true,  true,  false],
  ['w1_receipts',       'Receipts',          'red',    610,  30,  145, 'Wk 1', true,  true,  false],
  ['w1_compare',        'Compare',           'orange', 610,  120, 150, 'Wk 1', true,  true,  false],
  ['w1_correct',        'Resolve',           'orange', 815,  70,  150, 'Wk 1', true,  true,  false],
  ['w1_verify',         'Verify',            'orange', 1020, 70,  150, 'Wk 1', true,  true,  false],
  ['w1_invoice',        'Invoice',           'green',  1225, 70,  155, 'Wk 1', true,  true,  false],
  ['w1_invoice_export', 'Invoice Export',    'green',  1435, 40,  155, 'Wk 1', true,  true,  false],

  // Week 2 — bottom lane
  ['w2_payroll_pdf',    'Payroll PDF',       'blue',   225,  370, 135, 'Wk 2', true,  true,  false],
  ['w2_travel_pdf',     'Travel PDF',        'blue',   225,  450, 135, 'Wk 2', true,  true,  false],
  ['w2_approved_hours', 'Approved Hours',    'blue',   410,  400, 165, 'Wk 2', true,  true,  false],
  ['w2_receipts',       'Receipts',          'red',    610,  360, 145, 'Wk 2', true,  true,  false],
  ['w2_compare',        'Compare',           'orange', 610,  450, 150, 'Wk 2', true,  true,  false],
  ['w2_correct',        'Resolve',           'orange', 815,  400, 150, 'Wk 2', true,  true,  false],
  ['w2_verify',         'Verify',            'orange', 1020, 400, 150, 'Wk 2', true,  true,  false],
  ['w2_invoice',        'Invoice',           'green',  1225, 400, 155, 'Wk 2', true,  true,  false],
  ['w2_invoice_export', 'Invoice Export',    'green',  1435, 370, 155, 'Wk 2', true,  true,  false],

  // Merge + exports
  ['merge',              'Merge',            'teal',   1640, 215, 155, null,   true,  true,  false],
  ['modified_timesheets','Modified Timesheets','teal', 1850, 215, 180, null,   true,  true,  false],
  ['export_sage50',      'Sage50 CSV',        'green', 2085, 145, 155, null,   true,  false, false],
  ['export_summary',     'Summary CSV',       'green', 2085, 230, 155, null,   true,  false, false],
  ['export_drewedit',    'DrewEdit XLSX',     'green', 2085, 315, 155, null,   true,  false, false],
]

// ── Edge definitions ──────────────────────────────────────────────────────────
// [source, target, sourceHandle?]
const EDGE_DEFS = [
  // Shared → lanes
  ['timesheets',        'w1_approved_hours', 'week1'],
  ['timesheets',        'w2_approved_hours', 'week2'],
  ['employees',         'timesheets'],
  ['employees',         'w1_approved_hours'],
  ['employees',         'w2_approved_hours'],

  // Week 1 flow
  ['w1_payroll_pdf',    'w1_approved_hours'],
  ['w1_travel_pdf',     'w1_approved_hours'],
  ['w1_approved_hours', 'w1_compare'],
  ['w1_receipts',       'w1_verify'],
  ['w1_compare',        'w1_correct'],
  ['w1_correct',        'w1_verify'],
  ['w1_verify',         'w1_invoice'],
  ['w1_invoice',        'w1_invoice_export'],
  ['w1_invoice_export', 'merge'],

  // Week 2 flow
  ['w2_payroll_pdf',    'w2_approved_hours'],
  ['w2_travel_pdf',     'w2_approved_hours'],
  ['w2_approved_hours', 'w2_compare'],
  ['w2_receipts',       'w2_verify'],
  ['w2_compare',        'w2_correct'],
  ['w2_correct',        'w2_verify'],
  ['w2_verify',         'w2_invoice'],
  ['w2_invoice',        'w2_invoice_export'],
  ['w2_invoice_export', 'merge'],

  // Exports
  ['merge',             'modified_timesheets'],
  ['modified_timesheets','export_sage50'],
  ['modified_timesheets','export_summary'],
  ['modified_timesheets','export_drewedit'],
]

const EDGE_STYLE = {
  type: 'smoothstep',
  animated: false,
  style: { stroke: '#374151', strokeWidth: 2 },
  markerEnd: { type: MarkerType.ArrowClosed, color: '#374151' },
}

// Extract state string and summary from node state values.
// The API returns { state, summary } objects; handle plain strings for safety.
function nsState(ns) {
  if (!ns) return 'idle'
  if (typeof ns === 'object') return ns.state || 'idle'
  return ns
}
function nsSummary(ns) {
  if (!ns) return 'No data yet'
  if (typeof ns === 'object') return ns.summary || 'No data yet'
  const MAP = { idle: 'No data yet', partial: 'In progress', complete: 'Complete' }
  return MAP[ns] || 'No data yet'
}

function buildNodes(nodeStates, selectedId, onNodeOpen) {
  return NODE_DEFS.map(([id, label, color, x, y, width, badge, hasInput, hasOutput, infoOnly]) => ({
    id,
    type: 'workboard',
    position: { x, y },
    style: { width },
    selected: id === selectedId,
    data: {
      label,
      color,
      badge,
      state:    nsState(nodeStates?.[id]),
      summary:  nsSummary(nodeStates?.[id]),
      hasInput,
      hasOutput,
      outputs:  NODE_OUTPUTS[id] || null,
      infoOnly,
      onOpen:   infoOnly ? undefined : () => onNodeOpen(id),
    },
  }))
}

function buildEdges(nodeStates) {
  return EDGE_DEFS.map(([src, tgt, sourceHandle]) => {
    const tgtState = nsState(nodeStates?.[tgt])
    return {
      id: `e-${src}-${tgt}`,
      source: src,
      target: tgt,
      ...(sourceHandle ? { sourceHandle } : {}),
      ...EDGE_STYLE,
      style: {
        ...EDGE_STYLE.style,
        stroke: tgtState === 'complete' ? '#166534'
              : tgtState === 'partial'  ? '#78350f'
              : '#374151',
      },
      markerEnd: {
        ...EDGE_STYLE.markerEnd,
        color: tgtState === 'complete' ? '#22c55e'
             : tgtState === 'partial'  ? '#f59e0b'
             : '#374151',
      },
    }
  })
}

export default function WorkboardCanvas({ nodeStates, selectedNodeId, onNodeOpen }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  useEffect(() => {
    setNodes(prev => {
      if (prev.length === 0) {
        return buildNodes(nodeStates, selectedNodeId, onNodeOpen)
      }
      return prev.map(node => {
        const infoOnly = NODE_DEFS.find(d => d[0] === node.id)?.[9] ?? false
        return {
          ...node,
          selected: node.id === selectedNodeId,
          data: {
            ...node.data,
            state:   nsState(nodeStates?.[node.id]),
            summary: nsSummary(nodeStates?.[node.id]),
            onOpen:  infoOnly ? undefined : () => onNodeOpen(node.id),
          },
        }
      })
    })
    setEdges(buildEdges(nodeStates))
  }, [nodeStates, selectedNodeId])

  const onNodeClick = useCallback((_, node) => {
    if (!node.data?.infoOnly) onNodeOpen(node.id)
  }, [onNodeOpen])

  return (
    <div className="canvas-wrap">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.2}
        maxZoom={1.5}
        nodesDraggable={true}
        nodesConnectable={false}
        elementsSelectable={true}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1f2937" gap={22} size={1} />
        <Controls
          style={{ background: '#21262d', border: '1px solid #30363d', borderRadius: 8 }}
          showInteractive={false}
        />
        <MiniMap
          nodeColor={n => {
            const st = nsState(n.data?.state)
            return st === 'complete' ? '#166534' : st === 'partial' ? '#78350f' : '#21262d'
          }}
          maskColor="rgba(13,17,23,0.7)"
          style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 8 }}
        />
      </ReactFlow>
    </div>
  )
}
