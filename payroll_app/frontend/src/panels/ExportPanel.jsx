/**
 * ExportPanel — period-level data exports.
 *
 * Shared panel for all three export nodes:
 *   export_sage50    — Sage 50 payroll CSV (UTF-16, matches existing pipeline)
 *   export_summary   — Summary CSV (period overview, hours by employee)
 *   export_drewedit  — DrewEdit XLSX bundle (all corrected timesheets)
 *
 * All exports require the period to be reconciled (Merge complete).
 */
import { useState, useEffect, useCallback } from 'react'
import { getPeriod } from '../api'
import axios from 'axios'

const api = axios.create({ baseURL: 'http://localhost:8000' })

const EXPORT_CONFIG = {
  export_sage50: {
    label:       'Sage 50 Payroll CSV',
    icon:        '📥',
    description: 'UTF-16 encoded CSV for Sage 50 payroll entry. Matches the format used by the existing pipeline (payroll_export_*.csv).',
    endpoint:    (id) => `/api/periods/${id}/export/sage50`,
    filename:    (p)  => `payroll_export_${p?.week1_ending?.replace(/-/g, '') || 'period'}.csv`,
  },
  export_summary: {
    label:       'Summary CSV',
    icon:        '📥',
    description: 'Period summary: all employees, weekly REG/OT/DBL/Travel totals, expense summary, verification status.',
    endpoint:    (id) => `/api/periods/${id}/export/summary`,
    filename:    (p)  => `summary_${p?.week1_ending?.replace(/-/g, '') || 'period'}.csv`,
  },
  export_drewedit: {
    label:       'DrewEdit XLSX Bundle',
    icon:        '📥',
    description: 'All corrected employee timesheets for the period as a ZIP bundle of _DrewEdit.xlsx files.',
    endpoint:    (id) => `/api/periods/${id}/export/drewedit`,
    filename:    (p)  => `drewedit_${p?.week1_ending?.replace(/-/g, '') || 'period'}.zip`,
  },
}

export default function ExportPanel({ nodeId, periodId, onClose }) {
  const [period,     setPeriod]     = useState(null)
  const [exporting,  setExporting]  = useState(false)
  const [done,       setDone]       = useState(false)
  const [error,      setError]      = useState(null)

  useEffect(() => {
    if (periodId) {
      getPeriod(periodId).then(setPeriod).catch(() => {})
    }
  }, [periodId])

  const config = EXPORT_CONFIG[nodeId] || EXPORT_CONFIG.export_summary

  const handleExport = async () => {
    setExporting(true)
    setError(null)
    setDone(false)
    try {
      await api.get(config.endpoint(periodId))
      setDone(true)
    } catch (err) {
      setError(err.response?.data?.detail || err.message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <>
      <div className="panel-header">
        <h2>{config.icon} {config.label}</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">
        <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 16, lineHeight: 1.6 }}>
          {config.description}
        </div>

        {period && (
          <div style={{
            padding: '8px 12px', background: '#161b22', borderRadius: 6,
            border: '1px solid #21262d', fontSize: 11, color: '#8b949e',
            marginBottom: 14,
          }}>
            Period: Wk ending <strong>{period.week1_ending}</strong>
            {period.week2_ending && <> + <strong>{period.week2_ending}</strong></>}
            <br />
            Output file: <code style={{ color: '#a78bfa' }}>{config.filename(period)}</code>
          </div>
        )}

        {error && <div className="msg error" style={{ marginBottom: 10, fontSize: 11 }}>✗ {error}</div>}

        {done && (
          <div className="msg success" style={{ marginBottom: 10, fontSize: 11 }}>
            ✓ Export complete — file saved to output directory.
          </div>
        )}

        <button
          className="btn btn-primary"
          style={{ fontSize: 12, padding: '7px 20px', marginBottom: 16 }}
          disabled={exporting}
          onClick={handleExport}
        >
          {exporting ? '… Exporting' : `${config.icon} Export ${config.label}`}
        </button>

        <div style={{
          padding: '8px 12px', background: '#0d1117', borderRadius: 6,
          border: '1px solid #21262d', fontSize: 11, color: '#4b5563', lineHeight: 1.6,
        }}>
          Export endpoints are not yet implemented — requires the Merge (reconciliation)
          node to be complete. Backend export pipeline is the next phase.
        </div>
      </div>
    </>
  )
}
