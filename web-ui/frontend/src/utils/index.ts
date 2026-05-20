export const storage = function (key, value) {
    localStorage.setItem(key, JSON.stringify(value))
    return value
}

export const SERVER_URL = import.meta.env.VITE_SERVER_URL || 'http://localhost:8000';

export const getWebSocketUrl = (path = '/ws') => {
    if (SERVER_URL.startsWith('/')) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        return `${protocol}//${window.location.host}${SERVER_URL}${path}`
    }
    return `${SERVER_URL.replace(/^http/, 'ws')}${path}`
}
