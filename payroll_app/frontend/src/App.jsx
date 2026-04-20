/**
 * App.jsx — Root component.
 *
 * Layout:
 *   Topbar   — period selector
 *   Workspace
 *     Canvas — React Flow node graph (fills available width)
 *     Panel  — slides in on right when a node is selected
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import WorkboardCanvas    from './canvas'
import EmployeesPanel     from './panels/EmployeesPanel'
import TimesheetsPanel    from './panels/TimesheetsPanel'
import ApprovedHoursPanel from './panels/ApprovedHoursPanel'
import PayrollPdfPanel    from './panels/PayrollPdfPanel'
import TravelPdfPanel     from './panels/TravelPdfPanel'
import ComparePanel       from './panels/ComparePanel'
import ResolvePanel       from './panels/ResolvePanel'
import VerifyPanel               from './panels/VerifyPanel'
import InvoicePanel              from './panels/InvoicePanel'
import MergePanel                from './panels/MergePanel'
import ModifiedTimesheetsPanel   from './panels/ModifiedTimesheetsPanel'
import ExportPanel               from './panels/ExportPanel'
import ReceiptsPanel      from './panels/ReceiptsPanel'
import DebugPanel         from './panels/DebugPanel'
import { getPeriods, getNodeStates } from './api'

const NODE_LABELS = {
  employees:           '👥 Employees',
  timesheets:          '📋 Timesheets',
  w1_payroll_pdf:      '📄 Wk 1 — Payroll PDF',
  w1_travel_pdf:       '🚗 Wk 1 — Travel PDF',
  w1_approved_hours:   '📊 Wk 1 — Approved Hours',
  w1_receipts:         '🧾 Wk 1 — Receipts',
  w1_compare:          '🔍 Wk 1 — Compare',
  w1_correct:          '⚖️  Wk 1 — Resolve',
  w1_verify:           '✅ Wk 1 — Verify',
  w1_invoice:          '💰 Wk 1 — Invoice',
  w1_invoice_export:   '📤 Wk 1 — Invoice Export',
  w2_payroll_pdf:      '📄 Wk 2 — Payroll PDF',
  w2_travel_pdf:       '🚗 Wk 2 — Travel PDF',
  w2_approved_hours:   '📊 Wk 2 — Approved Hours',
  w2_receipts:         '🧾 Wk 2 — Receipts',
  w2_compare:          '🔍 Wk 2 — Compare',
  w2_correct:          '⚖️  Wk 2 — Resolve',
  w2_verify:           '✅ Wk 2 — Verify',
  w2_invoice:          '💰 Wk 2 — Invoice',
  w2_invoice_export:   '📤 Wk 2 — Invoice Export',
  merge:               '🔗 Merge',
  modified_timesheets: '📊 Modified Timesheets',
  export_sage50:       '📥 Sage50 CSV',
  export_summary:      '📥 Summary CSV',
  export_drewedit:     '📥 DrewEdit XLSX',
}

export default function App() {
  const [periods,      setPeriods]    = useState([])
  const [periodId,     setPeriodId]   = useState(null)
  const [nodeStates,   setNodeStates] = useState({})
  const [activeNode,   setActiveNode] = useState(null)
  const [showDebug,    setShowDebug]  = useState(false)
  const [loading,      setLoading]    = useState(true)
  const [panelWidth,   setPanelWidth] = useState(760)

  // Resize handle drag state
  const dragging   = useRef(false)
  const dragStartX = useRef(0)
  const dragStartW = useRef(0)

  const onResizeStart = useCallback((e) => {
    dragging.current   = true
    dragStartX.current = e.clientX
    dragStartW.current = panelWidth
    e.currentTarget.classList.add('dragging')

    const onMove = (e) => {
      if (!dragging.current) return
      const delta = dragStartX.current - e.clientX   // drag left = wider
      setPanelWidth(Math.max(380, Math.min(1400, dragStartW.current + delta)))
    }
    const onUp = (e) => {
      dragging.current = false
      e.target.classList?.remove('dragging')
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [panelWidth])

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
    const close = () => setActiveNode(null)

    if (activeNode === 'employees') {
      return <EmployeesPanel onClose={close} />
    }

    if (activeNode === 'timesheets') {
      return (
        <TimesheetsPanel
          periodId={periodId}
          onClose={close}
          onImportDone={handleImportDone}
        />
      )
    }

    if (activeNode === 'w1_payroll_pdf') {
      const ns = nodeStates?.w1_payroll_pdf
      const filename = ns?.state === 'complete' ? ns.summary : null
      return (
        <PayrollPdfPanel periodId={periodId} weekNum={1} filename={filename} onClose={close} />
      )
    }
    if (activeNode === 'w2_payroll_pdf') {
      const ns = nodeStates?.w2_payroll_pdf
      const filename = ns?.state === 'complete' ? ns.summary : null
      return (
        <PayrollPdfPanel periodId={periodId} weekNum={2} filename={filename} onClose={close} />
      )
    }

    if (activeNode === 'w1_travel_pdf') {
      const ns = nodeStates?.w1_travel_pdf
      const filename = ns?.state === 'complete' ? ns.summary : null
      return (
        <TravelPdfPanel periodId={periodId} weekNum={1} filename={filename} onClose={close} />
      )
    }
    if (activeNode === 'w2_travel_pdf') {
      const ns = nodeStates?.w2_travel_pdf
      const filename = ns?.state === 'complete' ? ns.summary : null
      return (
        <TravelPdfPanel periodId={periodId} weekNum={2} filename={filename} onClose={close} />
      )
    }

    if (activeNode === 'w1_approved_hours') {
      return (
        <ApprovedHoursPanel periodId={periodId} weekNum={1} onClose={close} onDone={refreshStates} />
      )
    }
    if (activeNode === 'w2_approved_hours') {
      return (
        <ApprovedHoursPanel periodId={periodId} weekNum={2} onClose={close} onDone={refreshStates} />
      )
    }

    if (activeNode === 'w1_compare') {
      return (
        <ComparePanel periodId={periodId} weekNum={1} onClose={close} onDone={refreshStates} />
      )
    }
    if (activeNode === 'w2_compare') {
      return (
        <ComparePanel periodId={periodId} weekNum={2} onClose={close} onDone={refreshStates} />
      )
    }

    if (activeNode === 'w1_receipts') {
      return <ReceiptsPanel periodId={periodId} weekNum={1} onClose={close} />
    }
    if (activeNode === 'w2_receipts') {
      return <ReceiptsPanel periodId={periodId} weekNum={2} onClose={close} />
    }

    if (activeNode === 'w1_correct') {
      return <ResolvePanel periodId={periodId} weekNum={1} onClose={close} onDone={refreshStates} />
    }
    if (activeNode === 'w2_correct') {
      return <ResolvePanel periodId={periodId} weekNum={2} onClose={close} onDone={refreshStates} />
    }

    if (activeNode === 'w1_verify') {
      return <VerifyPanel periodId={periodId} weekNum={1} onClose={close} onDone={refreshStates} />
    }
    if (activeNode === 'w2_verify') {
      return <VerifyPanel periodId={periodId} weekNum={2} onClose={close} onDone={refreshStates} />
    }

    if (activeNode === 'w1_invoice') {
      return <InvoicePanel periodId={periodId} weekNum={1} onClose={close} />
    }
    if (activeNode === 'w2_invoice') {
      return <InvoicePanel periodId={periodId} weekNum={2} onClose={close} />
    }

    if (activeNode === 'merge') {
      return <MergePanel periodId={periodId} onClose={close} onDone={refreshStates} />
    }

    if (activeNode === 'modified_timesheets') {
      return <ModifiedTimesheetsPanel periodId={periodId} onClose={close} />
    }

    if (activeNode === 'export_sage50' || activeNode === 'export_summary' || activeNode === 'export_drewedit') {
      return <ExportPanel nodeId={activeNode} periodId={periodId} onClose={close} />
    }

    if (activeNode === 'w1_invoice_export' || activeNode === 'w2_invoice_export') {
      const wk = activeNode.startsWith('w1') ? 1 : 2
      return <InvoicePanel periodId={periodId} weekNum={wk} onClose={close} />
    }

    // Generic placeholder for not-yet-built nodes
    return (
      <>
        <div className="panel-header">
          <h2>{NODE_LABELS[activeNode] || activeNode}</h2>
          <button className="close-btn" onClick={close}>×</button>
        </div>
        <div className="panel-body" style={{ color: '#8b949e', fontSize: 13, paddingTop: 24 }}>
          <div style={{ fontSize: 28, marginBottom: 12 }}>🚧</div>
          <strong style={{ color: '#e2e8f0' }}>Coming next</strong>
          <p style={{ marginTop: 8, lineHeight: 1.7 }}>
            This node is on the roadmap and will be built in the next phase.
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

        <button
          onClick={() => { setShowDebug(d => !d); setActiveNode(null) }}
          style={{
            background: showDebug ? '#92400e' : '#1e293b',
            color:      showDebug ? '#fbbf24' : '#64748b',
            border:     '1px solid #334155',
            borderRadius: 6,
            padding: '4px 10px',
            fontSize: 12,
            cursor: 'pointer',
            marginLeft: 12,
            flexShrink: 0,
          }}
        >
          🛠 Debug
        </button>
      </div>

      <div className="workspace">
        <WorkboardCanvas
          nodeStates={nodeStates}
          selectedNodeId={activeNode}
          onNodeOpen={handleNodeOpen}
        />

        {(activeNode || showDebug) && (
          <div className="side-panel" style={{ width: panelWidth }}>
            <div className="resize-handle" onMouseDown={onResizeStart} />
            {showDebug
              ? (
                <DebugPanel
                  onClose={() => setShowDebug(false)}
                  onReset={() => {
                    setPeriods([])
                    setPeriodId(null)
                    setNodeStates({})
                    setActiveNode(null)
                    getPeriods()
                      .then(ps => { setPeriods(ps); if (ps.length) setPeriodId(ps[0].id) })
                      .catch(() => {})
                  }}
                />
              )
              : renderPanel()
            }
          </div>
        )}
      </div>
    </>
  )
}
