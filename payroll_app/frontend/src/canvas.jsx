/**
 * canvas.jsx — React Flow canvas with all workboard nodes.
 *
 * Node positions match the two-lane layout from the design:
 *   Top lane    = Week 1
 *   Bottom lane = Week 2
 *   Left        = shared inputs (Employees, Timesheets)
 *   Right       = exports
 *
 * Each node calls onNodeOpen(nodeId) when clicked or ▶ pressed.
 */
import { useCallback, useEffect } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState, MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import WorkboardNode from './nodes/WorkboardNode'

const nodeTypes = { workboard: WorkboardNode }

// ── Node definitions ──────────────────────────────────────────────────────────
// [id, label, color, x, y, width, badge, hasInput, hasOutput]
const NODE_DEFS = [
  // Shared
  ['employees',         'Employees',           'purple', 20,   295, 170, null,   false, true],
  ['timesheets',        'Timesheets',          'green',  20,   155, 170, null,   false, true],

  // Week 1 — top lane
  ['w1_payroll_pdf',    'Payroll PDF',         'blue',   230,  50,  155, 'Wk 1', true,  true],
  ['w1_travel_pdf',     'Travel PDF',          'blue',   230,  130, 155, 'Wk 1', true,  true],
  ['w1_approved_hours', 'Approved Hours',      'blue',   430,  80,  165, 'Wk 1', true,  true],
  ['w1_receipts',       'Receipts',            'red',    625,  30,  145, 'Wk 1', true,  true],
  ['w1_reconcile',      'Reconcile',           'orange', 625,  110, 165, 'Wk 1', true,  true],
  ['w1_invoice',        'Verified Invoice',    'green',  835,  80,  165, 'Wk 1', true,  true],
  ['w1_invoice_export', 'Invoice Export',      'green',  1050, 50,  155, 'Wk 1', true,  true],

  // Week 2 — bottom lane
  ['w2_payroll_pdf',    'Payroll PDF',         'blue',   230,  370, 155, 'Wk 2', true,  true],
  ['w2_travel_pdf',     'Travel PDF',          'blue',   230,  450, 155, 'Wk 2', true,  true],
  ['w2_approved_hours', 'Approved Hours',      'blue',   430,  400, 165, 'Wk 2', true,  true],
  ['w2_receipts',       'Receipts',            'red',    625,  350, 145, 'Wk 2', true,  true],
  ['w2_reconcile',      'Reconcile',           'orange', 625,  430, 165, 'Wk 2', true,  true],
  ['w2_invoice',        'Verified Invoice',    'green',  835,  400, 165, 'Wk 2', true,  true],
  ['w2_invoice_export', 'Invoice Export',      'green',  1050, 370, 155, 'Wk 2', true,  true],

  // Merge + exports
  ['merge',              'Merge Reconciliation','teal',  1255, 230, 185, null,   true,  true],
  ['modified_timesheets','Modified Timesheets', 'teal',  1490, 230, 175, null,   true,  true],
  ['export_sage50',      'Sage50 CSV',          'green', 1715, 160, 155, null,   true,  false],
  ['export_summary',     'Summary CSV',         'green', 1715, 245, 155, null,   true,  false],
  ['export_drewedit',    'DrewEdit XLSX',       'green', 1715, 330, 155, null,   true,  false],
]

// ── Edge definitions ──────────────────────────────────────────────────────────
const EDGE_DEFS = [
  ['timesheets',        'w1_approved_hours'],
  ['timesheets',        'w2_approved_hours'],
  ['w1_payroll_pdf',    'w1_approved_hours'],
  ['w1_travel_pdf',     'w1_approved_hours'],
  ['w1_approved_hours', 'w1_reconcile'],
  ['w1_receipts',       'w1_reconcile'],
  ['w1_reconcile',      'w1_invoice'],
  ['w1_invoice',        'w1_invoice_export'],
  ['w1_invoice_export', 'merge'],
  ['w2_payroll_pdf',    'w2_approved_hours'],
  ['w2_travel_pdf',     'w2_approved_hours'],
  ['w2_approved_hours', 'w2_reconcile'],
  ['w2_receipts',       'w2_reconcile'],
  ['w2_reconcile',      'w2_invoice'],
  ['w2_invoice',        'w2_invoice_export'],
  ['w2_invoice_export', 'merge'],
  ['merge',             'modified_timesheets'],
  ['modified_timesheets','export_sage50'],
  ['modified_timesheets','export_summary'],
  ['modified_timesheets','export_drewedit'],
  ['employees',         'timesheets'],
  ['employees',         'w1_approved_hours'],
  ['employees',         'w2_approved_hours'],
]

const EDGE_STYLE = {
  type: 'smoothstep',
  animated: false,
  style: { stroke: '#374151', strokeWidth: 2 },
  markerEnd: { type: MarkerType.ArrowClosed, color: '#374151' },
}

const STATE_SUMMARY = {
  idle:     'No data yet',
  partial:  'In progress',
  complete: 'Complete',
}

function buildNodes(nodeStates, selectedId, onNodeOpen) {
  return NODE_DEFS.map(([id, label, color, x, y, width, badge, hasInput, hasOutput]) => ({
    id,
    type: 'workboard',
    position: { x, y },
    style: { width },
    selected: id === selectedId,
    data: {
      label,
      color,
      badge,
      state:    nodeStates?.[id] || 'idle',
      summary:  STATE_SUMMARY[nodeStates?.[id]] || 'No data yet',
      hasInput,
      hasOutput,
      onOpen:   () => onNodeOpen(id),
    },
  }))
}

function buildEdges(nodeStates) {
  return EDGE_DEFS.map(([src, tgt], i) => ({
    id: `e-${src}-${tgt}`,
    source: src,
    target: tgt,
    ...EDGE_STYLE,
    style: {
      ...EDGE_STYLE.style,
      stroke: nodeStates?.[tgt] === 'complete' ? '#166534'
            : nodeStates?.[tgt] === 'partial'  ? '#78350f'
            : '#374151',
    },
    markerEnd: {
      ...EDGE_STYLE.markerEnd,
      color: nodeStates?.[tgt] === 'complete' ? '#22c55e'
           : nodeStates?.[tgt] === 'partial'  ? '#f59e0b'
           : '#374151',
    },
  }))
}

export default function WorkboardCanvas({ nodeStates, selectedNodeId, onNodeOpen }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  useEffect(() => {
    setNodes(buildNodes(nodeStates, selectedNodeId, onNodeOpen))
    setEdges(buildEdges(nodeStates))
  }, [nodeStates, selectedNodeId])

  const onNodeClick = useCallback((_, node) => {
    onNodeOpen(node.id)
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
        minZoom={0.3}
        maxZoom={1.5}
        nodesDraggable={false}
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
            const state = n.data?.state
            return state === 'complete' ? '#166534' : state === 'partial' ? '#78350f' : '#21262d'
          }}
          maskColor="rgba(13,17,23,0.7)"
          style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 8 }}
        />
      </ReactFlow>
    </div>
  )
}
