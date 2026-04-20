/**
 * ReceiptsPanel — per-item receipt attachment for a pay period.
 *
 * Each expense item that requires a receipt gets its own drop zone.
 * Names won't always be obvious (bank statements, partial receipts, etc.) —
 * the owner decides what file belongs to each item and drops it directly.
 *
 * Items with no receipt can be deferred to the next period instead of
 * blocking verification.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { getReceipts, attachReceipt, deferReceipt } from '../api'
import { downloadCsv } from '../utils/csv'

const STATUS = {
  missing:  { bg: '#450a0a', fg: '#fca5a5', label: 'Missing' },
  received: { bg: '#14532d', fg: '#86efac', label: 'Received' },
  deferred: { bg: '#1c1917', fg: '#a8a29e', label: 'Deferred' },
  not_required: { bg: '#1e293b', fg: '#475569', label: 'N/A' },
}

function ReceiptItem({ item, periodId, onRefresh }) {
  const [dragOver,   setDragOver]   = useState(false)
  const [uploading,  setUploading]  = useState(false)
  const [deferring,  setDeferring]  = useState(false)
  const [showDefer,  setShowDefer]  = useState(false)
  const [deferNote,  setDeferNote]  = useState('')
  const [error,      setError]      = useState(null)
  const fileRef = useRef()

  const s = STATUS[item.receipt_status] || STATUS.missing
  const isDone = item.receipt_status === 'received' || item.receipt_status === 'deferred'

  const doUpload = useCallback(async (file) => {
    setUploading(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      await attachReceipt(periodId, item.id, fd)
      onRefresh()
    } catch (err) {
      setError(err.response?.data?.detail || err.message)
    } finally {
      setUploading(false)
    }
  }, [periodId, item.id, onRefresh])

  const doDefer = useCallback(async () => {
    setDeferring(true)
    setError(null)
    try {
      await deferReceipt(periodId, item.id, deferNote)
      onRefresh()
    } catch (err) {
      setError(err.response?.data?.detail || err.message)
    } finally {
      setDeferring(false)
      setShowDefer(false)
    }
  }, [periodId, item.id, deferNote, onRefresh])

  return (
    <div style={{
      border: `1px solid ${isDone ? (item.receipt_status === 'received' ? '#166534' : '#44403c') : '#374151'}`,
      borderRadius: 7,
      padding: '10px 14px',
      marginBottom: 8,
      background: isDone ? (item.receipt_status === 'received' ? 'rgba(34,197,94,0.04)' : 'rgba(168,162,158,0.04)') : '#0d1117',
    }}>
      {/* Item header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: isDone ? 0 : 8 }}>
        <span style={{ fontSize: 10, color: '#4b5563', whiteSpace: 'nowrap' }}>
          {item.work_date || '—'}
        </span>
        <span style={{ fontSize: 12, color: '#e2e8f0', flex: 1 }}>
          {item.category.replace(/_/g, ' ')}
          {item.description && (
            <span style={{ color: '#6b7280', marginLeft: 6 }}>— {item.description}</span>
          )}
        </span>
        <span style={{ fontSize: 12, color: '#8b949e', fontVariantNumeric: 'tabular-nums' }}>
          {item.amount.toFixed(2)} {item.currency}
        </span>
        <span style={{
          fontSize: 10, padding: '2px 6px', borderRadius: 3,
          background: s.bg, color: s.fg, whiteSpace: 'nowrap',
        }}>
          {s.label}
        </span>
      </div>

      {/* Drop zone — only shown when not yet done */}
      {!isDone && (
        <div
          style={{
            border: `1px dashed ${dragOver ? '#58a6ff' : '#374151'}`,
            borderRadius: 5,
            padding: uploading ? '8px 12px' : '6px 12px',
            background: dragOver ? 'rgba(88,166,255,0.06)' : 'transparent',
            cursor: uploading ? 'default' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            transition: 'border-color 0.15s, background 0.15s',
          }}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={e => {
            e.preventDefault()
            setDragOver(false)
            const f = e.dataTransfer.files[0]
            if (f) doUpload(f)
          }}
          onClick={() => !uploading && fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            accept="image/*,.pdf"
            style={{ display: 'none' }}
            onChange={e => {
              const f = e.target.files[0]
              if (f) doUpload(f)
              e.target.value = ''
            }}
          />
          {uploading ? (
            <span style={{ fontSize: 11, color: '#4b5563' }}>Uploading…</span>
          ) : (
            <>
              <span style={{ fontSize: 11, color: '#4b5563' }}>
                {dragOver ? 'Drop to attach' : '📎 Drop or click to attach receipt'}
              </span>
              <span style={{ flex: 1 }} />
              <button
                className="btn"
                style={{
                  fontSize: 10, padding: '2px 8px',
                  background: '#1c1917', color: '#a8a29e',
                  border: '1px solid #44403c', borderRadius: 4,
                }}
                onClick={e => { e.stopPropagation(); setShowDefer(v => !v) }}
              >
                Defer →
              </button>
            </>
          )}
        </div>
      )}

      {/* Defer note input */}
      {showDefer && !isDone && (
        <div style={{ marginTop: 6, display: 'flex', gap: 6, alignItems: 'center' }}>
          <input
            type="text"
            placeholder="Reason (optional)"
            value={deferNote}
            onChange={e => setDeferNote(e.target.value)}
            style={{
              flex: 1, fontSize: 11, padding: '4px 8px',
              background: '#161b22', border: '1px solid #374151',
              borderRadius: 4, color: '#e2e8f0',
            }}
            onKeyDown={e => e.key === 'Enter' && doDefer()}
          />
          <button
            className="btn"
            style={{
              fontSize: 10, padding: '4px 10px',
              background: '#292524', color: '#a8a29e',
              border: '1px solid #44403c', borderRadius: 4,
            }}
            disabled={deferring}
            onClick={doDefer}
          >
            {deferring ? '…' : 'Defer to next period'}
          </button>
          <button
            className="btn"
            style={{ fontSize: 10, padding: '4px 8px', background: 'transparent', color: '#4b5563', border: 'none' }}
            onClick={() => setShowDefer(false)}
          >
            Cancel
          </button>
        </div>
      )}

      {error && (
        <div className="msg error" style={{ marginTop: 6, fontSize: 10 }}>✗ {error}</div>
      )}
    </div>
  )
}

function EmployeeSection({ employee, items, periodId, onRefresh }) {
  const missing  = items.filter(i => i.receipt_status === 'missing').length
  const received = items.filter(i => i.receipt_status === 'received').length
  const deferred = items.filter(i => i.receipt_status === 'deferred').length

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        marginBottom: 8, paddingBottom: 4,
        borderBottom: '1px solid #21262d',
      }}>
        <span style={{ fontWeight: 600, fontSize: 13, color: '#e2e8f0', flex: 1 }}>{employee}</span>
        {missing > 0 && (
          <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: '#450a0a', color: '#fca5a5' }}>
            {missing} missing
          </span>
        )}
        {deferred > 0 && (
          <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: '#1c1917', color: '#a8a29e' }}>
            {deferred} deferred
          </span>
        )}
        {received > 0 && (
          <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: '#14532d', color: '#86efac' }}>
            {received} received
          </span>
        )}
      </div>
      {items.map(item => (
        <ReceiptItem key={item.id} item={item} periodId={periodId} onRefresh={onRefresh} />
      ))}
    </div>
  )
}

export default function ReceiptsPanel({ periodId, weekNum, onClose }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    if (!periodId) return
    setLoading(true)
    getReceipts(periodId, weekNum)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [periodId, weekNum])

  useEffect(load, [periodId, weekNum])

  const byEmployee = {}
  if (data?.items) {
    for (const item of data.items) {
      if (!byEmployee[item.employee]) byEmployee[item.employee] = []
      byEmployee[item.employee].push(item)
    }
  }

  const missingCount  = data?.missing_count  || 0
  const receivedCount = data?.received_count || 0
  const deferredCount = data?.deferred_count || 0
  const allClear = data && missingCount === 0

  return (
    <>
      <div className="panel-header">
        <h2>🧾 {weekNum ? `Week ${weekNum} — ` : ''}Receipts</h2>
        {data?.items?.length > 0 && (
          <button className="btn btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }}
            onClick={() => {
              const out = [['Employee','Date','Category','Description','Amount','Currency','Receipt Status']]
              for (const i of data.items) {
                out.push([i.employee||'',i.work_date||'',i.category||'',i.description||'',i.amount||'',i.currency||'',i.receipt_status||''])
              }
              downloadCsv(out, `debug_receipts_wk${weekNum||'all'}.csv`)
            }}>↓ Debug CSV</button>
        )}
        <button className="close-btn" onClick={onClose}>×</button>
      </div>

      <div className="panel-body">

        <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 14, lineHeight: 1.6 }}>
          Attach a receipt to each item below. Drop any file directly onto the item —
          the filename doesn't need to match. Deferred items are skipped this period
          and will not block verification.
        </div>

        {data && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, padding: '4px 10px', borderRadius: 4, background: '#1e293b', color: '#e2e8f0' }}>
              {data.total_count} required
            </span>
            {missingCount > 0 && (
              <span style={{ fontSize: 12, padding: '4px 10px', borderRadius: 4, background: '#450a0a', color: '#fca5a5' }}>
                {missingCount} missing
              </span>
            )}
            {deferredCount > 0 && (
              <span style={{ fontSize: 12, padding: '4px 10px', borderRadius: 4, background: '#1c1917', color: '#a8a29e' }}>
                {deferredCount} deferred
              </span>
            )}
            {receivedCount > 0 && (
              <span style={{ fontSize: 12, padding: '4px 10px', borderRadius: 4, background: '#14532d', color: '#86efac' }}>
                {receivedCount} received
              </span>
            )}
          </div>
        )}

        {allClear && (
          <div className="msg success" style={{ marginBottom: 14, fontSize: 11 }}>
            ✓ All receipts accounted for — no items are blocking verification.
          </div>
        )}

        {loading && <div style={{ color: '#4b5563', fontSize: 12 }}>Loading…</div>}

        {!loading && data?.total_count === 0 && (
          <div style={{ color: '#4b5563', fontSize: 12 }}>
            No receipts required for this period.
          </div>
        )}

        {Object.entries(byEmployee).map(([employee, items]) => (
          <EmployeeSection
            key={employee}
            employee={employee}
            items={items}
            periodId={periodId}
            onRefresh={load}
          />
        ))}

      </div>
    </>
  )
}
