import BasicLayout from './layout/BasicLayout'
import { observer } from 'mobx-react'
import { Navigate } from 'react-router-dom'
import { authStore } from './store/auth'
import Loading from './components/loading'
import { useEffect } from 'react'

const App = () => {
  useEffect(() => {
    if (!authStore.initialized) {
      authStore.fetchMe()
    }
  }, [])

  if (!authStore.initialized || authStore.loading) {
    return <Loading />
  }

  if (!authStore.isAuthenticated) {
    return <Navigate replace to="/" />
  }

  return (
    <div
      style={{
        height: '100vh'
      }}
    >
      <BasicLayout />
    </div>
  )
}

export default observer(App)
