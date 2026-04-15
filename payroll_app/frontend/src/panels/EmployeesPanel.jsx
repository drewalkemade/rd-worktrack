/**
 * EmployeesPanel — global employee roster editor.
 *
 * Shows every active employee in an editable grid.
 * Inline-edit any field and press Enter or click away to save.
 * Aliases are shown as tags; adding/removing via the alias sub-row.
 */
import { useState, useEffect, useRef } from 'react'
import { getEmployees, updateEmployee, addAlias, deleteAlias } from '../api'

const ASSIGNMENT_LABELS = {
  billable: { label: 'Billable', color: '#166534' },
  internal: { label: 'Internal', color: '#4c1d95' },
}

function EditableCell({ value, onSave, placeholder = '' }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal]         = useState(value ?? '')
  const ref                   = useRef()

  useEffect(() => { setVal(value ?? '') }, [value])
  useEffect(() => { if (editing) ref.current?.focus() }, [editing])

  const commit = () => {
    setEditing(false)
    if (val !== (value ?? '')) onSave(val)
  }

  if (!editing) {
    return (
      <span
        style={{ cursor: 'text', color: value ? '#e2e8f0' : '#4b5563', display: 'block', padding: '3px 6px' }}
        onClick={() => setEditing(true)}
        title="Click to edit"
      >
        {value || <em style={{ color: '#4b5563' }}>{placeholder}</em>}
      </span>
    )
  }

  return (
    <input
      ref={ref}
      value={val}
      onChange={e => setVal(e.target.value)}
      onBlur={commit}
      onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setVal(value ?? ''); setEditing(false) } }}
    />
  )
}

function AliasRow({ emp, onRefresh }) {
  const [newType,  setNewType]  = useState('display_name')
  const [newValue, setNewValue] = useState('')
  const [saving,   setSaving]   = useState(false)

  const alias_types = ['display_name', 'pdf_name', 'travel_name', 'sage50_name', 'receipt_name', 'expense_code']

  const handleAdd = async () => {
    if (!newValue.trim()) return
    setSaving(true)
    try {
      await addAlias(emp.id, { alias_type: newType, alias_value: newValue.trim() })
      setNewValue('')
      onRefresh()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (type, value) => {
    await deleteAlias(emp.id, { alias_type: type, alias_value: value })
    onRefresh()
  }

  return (
    <tr style={{ background: '#131a24' }}>
      <td colSpan={6} style={{ padding: '8px 14px 10px 28px' }}>
        <div style={{ marginBottom: 6, fontSize: 10, color: '#8b949e', fontWeight: 600, letterSpacing: '0.6px', textTransform: 'uppercase' }}>
          Aliases
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
          {emp.aliases.map(a => (
            <span key={a.alias_type + a.alias_value} className="tag"
              style={{ cursor: 'pointer' }}
              title={`${a.alias_type}: click × to remove`}>
              <span style={{ color: '#8b949e', marginRight: 3 }}>{a.alias_type}:</span>
              {a.alias_value}
              <span
                style={{ marginLeft: 5, color: '#ef4444', cursor: 'pointer' }}
                onClick={() => handleDelete(a.alias_type, a.alias_value)}
              >×</span>
            </span>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select value={newType} onChange={e => setNewType(e.target.value)}
            style={{ background: '#21262d', border: '1px solid #30363d', color: '#e2e8f0', padding: '4px 8px', borderRadius: 4, fontSize: 11 }}>
            {alias_types.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <input value={newValue} onChange={e => setNewValue(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleAdd()}
            placeholder="alias value"
            style={{ background: '#21262d', border: '1px solid #30363d', color: '#e2e8f0',
                     padding: '4px 8px', borderRadius: 4, fontSize: 11, flex: 1 }} />
          <button className="btn btn-ghost" onClick={handleAdd} disabled={saving} style={{ padding: '4px 10px', fontSize: 11 }}>
            + Add
          </button>
        </div>
      </td>
    </tr>
  )
}

export default function EmployeesPanel({ onClose }) {
  const [employees, setEmployees] = useState([])
  const [expanded,  setExpanded]  = useState(null)  // employee id
  const [loading,   setLoading]   = useState(true)

  const load = async () => {
    setLoading(true)
    try { setEmployees(await getEmployees()) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const save = async (id, field, value) => {
    await updateEmployee(id, { [field]: value })
    setEmployees(prev => prev.map(e => e.id === id ? { ...e, [field]: value } : e))
  }

  if (loading) return <div style={{ padding: 20, color: '#8b949e', fontSize: 13 }}>Loading employees…</div>

  return (
    <>
      <div className="panel-header">
        <h2>👥 Employee Roster</h2>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body" style={{ padding: 0 }}>
        <div style={{ padding: '10px 16px 8px', fontSize: 11, color: '#8b949e', borderBottom: '1px solid #21262d' }}>
          Click any cell to edit. Click a row's <strong style={{ color: '#e2e8f0' }}>Name</strong> to expand aliases.
          Changes save immediately.
        </div>

        <table className="emp-grid">
          <thead>
            <tr>
              <th>Name</th>
              <th>PDF Name</th>
              <th>PDF ID</th>
              <th>Centerline ID</th>
              <th>Type</th>
              <th>Active</th>
            </tr>
          </thead>
          <tbody>
            {employees.map(emp => (
              <>
                <tr key={emp.id} style={{ cursor: 'pointer' }}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span
                        style={{ color: '#58a6ff', cursor: 'pointer', fontSize: 10 }}
                        onClick={() => setExpanded(expanded === emp.id ? null : emp.id)}
                        title="Show aliases"
                      >
                        {expanded === emp.id ? '▾' : '▸'}
                      </span>
                      <EditableCell value={emp.display_name}
                        onSave={v => save(emp.id, 'display_name', v)} />
                    </div>
                  </td>
                  <td>
                    <EditableCell value={emp.pdf_name} placeholder="—"
                      onSave={v => save(emp.id, 'pdf_name', v)} />
                  </td>
                  <td>
                    <EditableCell value={emp.pdf_id} placeholder="—"
                      onSave={v => save(emp.id, 'pdf_id', v)} />
                  </td>
                  <td>
                    <EditableCell value={emp.centerline_id} placeholder="—"
                      onSave={v => save(emp.id, 'centerline_id', v)} />
                  </td>
                  <td>
                    <span style={{
                      background: ASSIGNMENT_LABELS[emp.assignment_type]?.color || '#21262d',
                      padding: '2px 7px', borderRadius: 3, fontSize: 10, color: '#fff'
                    }}>
                      {ASSIGNMENT_LABELS[emp.assignment_type]?.label || emp.assignment_type || '—'}
                    </span>
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <span style={{ color: emp.active ? '#22c55e' : '#4b5563', fontSize: 13 }}>
                      {emp.active ? '●' : '○'}
                    </span>
                  </td>
                </tr>
                {expanded === emp.id && (
                  <AliasRow key={`${emp.id}-aliases`} emp={emp} onRefresh={load} />
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
