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
export const getVerification  = (id, wk)   => api.get(`/api/periods/${id}/weeks/${wk}/verification`).then(r => r.data)
export const runVerification  = (id, wk)   => api.post(`/api/periods/${id}/weeks/${wk}/verify`).then(r => r.data)
export const setVerified      = (id, wk, empId, note) =>
  api.post(`/api/periods/${id}/weeks/${wk}/set-verified/${empId}`, { note }).then(r => r.data)

export const importPayrollPdf = (formData) => api.post('/api/import/payroll-pdf', formData, {
  headers: { 'Content-Type': 'multipart/form-data' }
}).then(r => r.data)

export const importTravelPdf  = (formData) => api.post('/api/import/travel-pdf', formData, {
  headers: { 'Content-Type': 'multipart/form-data' }
}).then(r => r.data)

export const importTimesheets = (formData)  => api.post('/api/import/timesheets', formData, {
  headers: { 'Content-Type': 'multipart/form-data' }
}).then(r => r.data)
