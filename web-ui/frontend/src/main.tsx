import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { router } from '../config/routes'

import Loading from './components/loading'
import './styles/tailwind.css'
import './i18n'
import { SERVER_URL } from './utils'

const nativeFetch = window.fetch.bind(window)
window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
  const shouldIncludeCredentials = url.startsWith(SERVER_URL) || url.startsWith('/api')
  return nativeFetch(input, {
    ...init,
    credentials: init?.credentials || (shouldIncludeCredentials ? 'include' : undefined)
  })
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <RouterProvider router={router} fallbackElement={<Loading />} />
)
