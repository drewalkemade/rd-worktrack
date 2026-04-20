/**
 * WorkboardNode — shared wrapper for every node on the canvas.
 *
 * Props (passed via React Flow `data`):
 *   label       string   node title
 *   color       string   header colour class: green | blue | orange | teal | red | purple
 *   badge       string?  small badge text (e.g. "Wk 1")
 *   state       string   idle | partial | complete
 *   summary     string   short text shown in node body
 *   onOpen      fn       called when the node or ▶ button is clicked
 *   infoOnly    bool     if true: no Open button, no click handler — visual reference only
 */
import { Handle, Position } from '@xyflow/react'

const STATE_ICON  = { idle: '', partial: '◑', complete: '✓' }
const STATE_COLOR = { idle: '#8b949e', partial: '#f59e0b', complete: '#22c55e' }

export default function WorkboardNode({ data, selected }) {
  const {
    label, color, badge, state = 'idle', summary, onOpen,
    hasInput = true, hasOutput = true, outputs = null,
    infoOnly = false,
  } = data

  const stateIcon  = STATE_ICON[state]  || ''
  const stateColor = STATE_COLOR[state] || '#8b949e'

  return (
    <div
      className={`wb-node ${state} ${selected ? 'selected' : ''} ${infoOnly ? 'info-only' : ''}`}
      onClick={() => !infoOnly && onOpen?.()}
      style={infoOnly ? { cursor: 'default', opacity: 0.8 } : {}}
    >
      {hasInput && (
        <Handle type="target" position={Position.Left}
          style={{ top: '50%', transform: 'translateY(-50%)' }} />
      )}

      <div className={`wb-node-header ${color}`}>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {label}
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5, flexShrink: 0 }}>
          {badge && <span className="wb-node-badge">{badge}</span>}
          {stateIcon && (
            <span style={{ color: stateColor, fontSize: 11, fontWeight: 700 }}>
              {stateIcon}
            </span>
          )}
        </span>
      </div>

      <div className="wb-node-body" style={infoOnly ? { paddingBottom: 6 } : {}}>
        <div style={{ color: '#8b949e' }}>
          {summary || (state === 'idle' ? 'No data yet' : state === 'partial' ? 'In progress' : 'Complete')}
        </div>
        {!infoOnly && (
          <button className="play-btn" onClick={e => { e.stopPropagation(); onOpen?.() }}>
            ▶ Open
          </button>
        )}
      </div>

      {/* Multiple named outputs (e.g. Timesheets → Wk 1 / Wk 2) */}
      {outputs ? (
        outputs.map((o, i) => {
          const topPct = `${(i + 1) * 100 / (outputs.length + 1)}%`
          return (
            <span key={o.id}>
              <span style={{
                position: 'absolute',
                right: 14,
                top: topPct,
                transform: 'translateY(-50%)',
                fontSize: 9,
                color: '#6b7280',
                pointerEvents: 'none',
                userSelect: 'none',
              }}>
                {o.label}
              </span>
              <Handle
                type="source"
                position={Position.Right}
                id={o.id}
                style={{ top: topPct, transform: 'translateY(-50%)' }}
              />
            </span>
          )
        })
      ) : hasOutput && (
        <Handle type="source" position={Position.Right}
          style={{ top: '50%', transform: 'translateY(-50%)' }} />
      )}
    </div>
  )
}
