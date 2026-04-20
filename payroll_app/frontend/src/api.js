import axios from 'axios'

const api = axios.create({ baseURL: 'http://localhost:8000' })

export const getEmployees    = ()           => api.get('/api/employees').then(r => r.data)
export const updateEmployee  = (id, body)   => api.put(`/api/employees/${id}`, body).then(r => r.data)
export const addAlias        = (id, body)   => api.post(`/api/employees/${id}/aliases`, body).then(r => r.data)
export const deleteAlias     = (id, body)   => api.delete(`/api/employees/${id}/aliases`, { data: body }).then(r => r.data)

export const getPeriods      = ()           => api.get('/api/periods').then(r => r.data)
export const getPeriod       = (id)         => api.get(`/api/periods/${id}`).then(r => r.data)
export const getNodeStates   = (id)         => api.get(`/api/periods/${id}/node-states`).then(r => r.data)
export const getWeek1Hours   = (id)         => api.get(`/api/periods/${id}/week1-hours`).then(r => r.data)
export const getWeek2Hours   = (id)         => api.get(`/api/periods/${id}/week2-hours`).then(r => r.data)
export const getPeriodExpenses = (id)       => api.get(`/api/periods/${id}/expenses`).then(r => r.data)

export const getWeek          = (id, wk)   => api.get(`/api/periods/${id}/weeks/${wk}`).then(r => r.data)
export const getApprovedHours  = (id, wk)  => api.get(`/api/periods/${id}/weeks/${wk}/approved-hours`).then(r => r.data)
export const getTravelHours    = (id, wk)  => api.get(`/api/periods/${id}/weeks/${wk}/travel-hours`).then(r => r.data)
export const getDayComparison  = (id, wk)  => api.get(`/api/periods/${id}/weeks/${wk}/day-comparison`).then(r => r.data)
export const getCorrections    = (id, wk)  => api.get(`/api/periods/${id}/weeks/${wk}/corrections`).then(r => r.data)
export const identifyCorrection = (id, wk, body) => api.post(`/api/periods/${id}/weeks/${wk}/corrections/identify`, body).then(r => r.data)
export const applySundayOverride = (id, wk, body) => api.post(`/api/periods/${id}/weeks/${wk}/corrections/sunday-override`, body).then(r => r.data)
export const resolveCorrection   = (id, wk, body) => api.post(`/api/periods/${id}/weeks/${wk}/corrections/resolve`, body).then(r => r.data)
export const getVerification  = (id, wk)   => api.get(`/api/periods/${id}/weeks/${wk}/verification`).then(r => r.data)
export const runVerification  = (id, wk)   => api.post(`/api/periods/${id}/weeks/${wk}/verify`).then(r => r.data)
export const setVerified      = (id, wk, empId, note) =>
  api.post(`/api/periods/${id}/weeks/${wk}/set-verified/${empId}`, { note }).then(r => r.data)

export const getInvoicePreview = (id, wk)   => api.get(`/api/periods/${id}/weeks/${wk}/invoice-preview`).then(r => r.data)

export const getReceipts      = (id, wk)    => api.get(`/api/periods/${id}/receipts${wk ? `?week_num=${wk}` : ''}`).then(r => r.data)
export const attachReceipt    = (id, expId, formData) =>
  api.post(`/api/periods/${id}/expenses/${expId}/attach-receipt`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }).then(r => r.data)
export const deferReceipt     = (id, expId, note) =>
  api.post(`/api/periods/${id}/expenses/${expId}/defer`, { note }).then(r => r.data)

export const importPayrollPdf = (formData) => api.post('/api/import/payroll-pdf', formData, {
  headers: { 'Content-Type': 'multipart/form-data' }
}).then(r => r.data)

export const importTravelPdf  = (formData) => api.post('/api/import/travel-pdf', formData, {
  headers: { 'Content-Type': 'multipart/form-data' }
}).then(r => r.data)

export const importTimesheets = (formData)  => api.post('/api/import/timesheets', formData, {
  headers: { 'Content-Type': 'multipart/form-data' }
}).then(r => r.data)

// Debug / dev tools
export const debugStats             = ()  => api.get('/api/debug/stats').then(r => r.data)
export const debugClearImportedData = ()  => api.post('/api/debug/clear-imported-data').then(r => r.data)
export const debugClearAndReseed    = ()  => api.post('/api/debug/clear-and-reseed').then(r => r.data)
