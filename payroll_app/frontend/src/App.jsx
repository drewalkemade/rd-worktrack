/**
 * App.jsx — Root component.
 *
 * Layout:
 *   Topbar   — period selector
 *   Workspace
 *     Canvas — React Flow node graph (fills available width)
 *     Panel  — slides in on right when a node is selected
 */
import { useState, useEffect, useCallback } from 'react'
import WorkboardCanvas from './canvas'
import EmployeesPanel  from './panels/EmployeesPanel'
import TimesheetsPanel from './panels/TimesheetsPanel'
import { getPeriods, getNodeStates } from './api'

const NODE_LABELS = {
  employees:          '👥 Employees',
  timesheets:         '📋 Timesheets',
  w1_payroll_pdf:     '📄 Wk 1 — Payroll PDF',
  w1_travel_pdf:      '✈  Wk 1 — Travel PDF',
  w1_approved_hours:  '📊 Wk 1 — Approved Hours',
  w1_receipts:        '🧾 Wk 1 — Receipts',
  w1_reconcile:       '🔄 Wk 1 — Reconcile',
  w1_invoice:         '💰 Wk 1 — Invoice',
  w1_invoice_export:  '📤 Wk 1 — Invoice Export',
  w2_payroll_pdf:     '📄 Wk 2 — Payroll PDF',
  w2_travel_pdf:      '✈  Wk 2 — Travel PDF',
  w2_approved_hours:  '📊 Wk 2 — Approved Hours',
  w2_receipts:        '🧾 Wk 2 — Receipts',
  w2_reconcile:       '🔄 Wk 2 — Reconcile',
  w2_invoice:         '💰 Wk 2 — Invoice',
  w2_invoice_export:  '📤 Wk 2 — Invoice Export',
  merge:              '🔗 Merge Reconciliation',
  modified_timesheets:'📊 Modified Timesheets',
  export_sage50:      '📥 Sage50 CSV',
  export_summary:     '📥 Summary CSV',
  export_drewedit:    '📥 DrewEdit XLSX',
}

export default function App() {
  const [periods,    setPeriods]    = useState([])
  const [periodId,   setPeriodId]   = useState(null)
  const [nodeStates, setNodeStates] = useState({})
  const [activeNode, setActiveNode] = useState(null)
  const [loading,    setLoading]    = useState(true)

  useEffect(() => {
    getPeriods()
      .then(ps => {
        setPeriods(ps)
        if (ps.length) setPeriodId(ps[0].id)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!periodId) return
    getNodeStates(periodId).then(setNodeStates).catch(() => setNodeStates({}))
  }, [periodId])

  const refreshStates = useCallback(() => {
    if (!periodId) return
    getNodeStates(periodId).then(setNodeStates).catch(() => {})
  }, [periodId])

  const handleNodeOpen = useCallback((nodeId) => {
    setActiveNode(prev => prev === nodeId ? null : nodeId)
  }, [])

  const handleImportDone = useCallback((newPeriodId) => {
    if (newPeriodId && newPeriodId !== periodId) {
      getPeriods().then(ps => {
        setPeriods(ps)
        setPeriodId(newPeriodId)
      }).catch(() => {})
    } else {
      refreshStates()
    }
  }, [periodId, refreshStates])

  const renderPanel = () => {
    if (!activeNode) return null

    if (activeNode === 'employees') {
      return <EmployeesPanel onClose={() => setActiveNode(null)} />
    }
    if (activeNode === 'timesheets') {
      return (
        <TimesheetsPanel
          periodId={periodId}
          onClose={() => setActiveNode(null)}
          onImportDone={handleImportDone}
        />
      )
    }

    // Placeholder for nodes not yet implemented
    return (
      <>
        <div className="panel-header">
          <h2>{NODE_LABELS[activeNode] || activeNode}</h2>
          <button className="close-btn" onClick={() => setActiveNode(null)}>×</button>
        </div>
        <div className="panel-body" style={{ color: '#8b949e', fontSize: 13, paddingTop: 24 }}>
          <div style={{ fontSize: 28, marginBottom: 12 }}>🚧</div>
          <strong style={{ color: '#e2e8f0' }}>Coming next</strong>
          <p style={{ marginTop: 8, lineHeight: 1.7 }}>
            This node is on the roadmap. We're building one node at a time,
            starting with Employees → Timesheets → Approved Hours.
          </p>
        </div>
      </>
    )
  }

  return (
    <>
      <div className="topbar">
        <h1>⚙️ R&D Controls — Payroll Workboard</h1>

        {loading ? (
          <span className="period-label">Loading…</span>
        ) : periods.length === 0 ? (
          <span className="period-label" style={{ color: '#f59e0b' }}>
            No periods — open Timesheets node to import your first file
          </span>
        ) : (
          <select
            value={periodId ?? ''}
            onChange={e => { setPeriodId(Number(e.target.value)); setActiveNode(null) }}
          >
            {periods.map(p => (
              <option key={p.id} value={p.id}>
                Wk ending {p.week1_ending}
                {p.week2_ending ? `  +  ${p.week2_ending}` : '  (wk 2 pending)'}
              </option>
            ))}
          </select>
        )}

        <span className="period-label" style={{ marginLeft: 'auto', fontSize: 11 }}>
          {activeNode
            ? `▸ ${NODE_LABELS[activeNode] || activeNode}`
            : 'Click any node to open it'}
        </span>
      </div>

      <div className="workspace">
        <WorkboardCanvas
          nodeStates={nodeStates}
          selectedNodeId={activeNode}
          onNodeOpen={handleNodeOpen}
        />

        {activeNode && (
          <div className="side-panel">
            {renderPanel()}
          </div>
        )}
      </div>
    </>
  )
}
