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

export const importTimesheets = (formData)  => api.post('/api/import/timesheets', formData, {
  headers: { 'Content-Type': 'multipart/form-data' }
}).then(r => r.data)
