import NotFoundPage from '@/404'
import App from '@/App'
import ErrorPage from '@/ErrorPage'
import Home from '@/pages/Home'
import Landing from '@/pages/Landing'
import WhyHypergraph from '@/pages/Landing/WhyHypergraph'
import TryDemo from '@/pages/Landing/TryDemo'
import FlowBatteryDemo from '@/pages/Landing/FlowBatteryDemo'
import PFASDemo from '@/pages/Landing/PFASDemo'
import Files from '@/pages/Files'
import Graph from '@/pages/Hyper/Graph'
import FullGraph from '@/pages/Hyper/FullGraph'
import HyperDB from '@/pages/Hyper/DB'
import Setting from '@/pages/Setting'
import {
  DatabaseOutlined,
  DeploymentUnitOutlined,
  FileAddOutlined,
  ProjectOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  SmileFilled,
} from '@ant-design/icons'
import { Navigate } from 'react-router-dom'

export const routers = [
  {
    path: '/',
    element: <Landing />,
  },
  {
    path: '/why-hypergraph',
    element: <WhyHypergraph />,
  },
  {
    path: '/try',
    element: <TryDemo />,
  },
  {
    path: '/demo/flow-battery',
    element: <FlowBatteryDemo />,
  },
  {
    path: '/demo/pfas',
    element: <PFASDemo />,
  },
  {
    path: '/app',
    element: <App />,
    errorElement: <ErrorPage />,
    icon: <SmileFilled />,
    children: [
      {
        path: '/app',
        element: <Navigate replace to="/app/Hyper/chat" />,
      },
      {
        path: '/app/Hyper/chat',
        name: '检索问答',
        icon: <QuestionCircleOutlined />,
        element: <Home />,
      },
      {
        path: '/app/Hyper/show',
        name: '超图展示',
        icon: <DeploymentUnitOutlined />,
        element: <Graph />,
      },
      {
        path: '/app/Hyper/DB',
        name: 'HypergraphDB',
        icon: <DatabaseOutlined />,
        element: <HyperDB />,
      },
      {
        path: '/app/Hyper/FullGraph',
        name: 'FullGraph',
        icon: <ProjectOutlined />,
        element: <FullGraph />,
      },
      {
        path: '/app/Hyper/files',
        name: '知识库',
        icon: <FileAddOutlined />,
        element: <Files />,
      },
      {
        path: '/app/API',
        name: 'API 文档',
        hideInMenu: true,
        element: <Navigate replace to="/app/Hyper/chat" />,
      },
      {
        path: '/app/Setting',
        name: '系统设置',
        icon: <SettingOutlined />,
        element: <Setting />,
      },
    ],
  },
  { path: '/Hyper/chat', element: <Navigate replace to="/app/Hyper/chat" /> },
  { path: '/Hyper/show', element: <Navigate replace to="/app/Hyper/show" /> },
  { path: '/Hyper/DB', element: <Navigate replace to="/app/Hyper/DB" /> },
  { path: '/Hyper/FullGraph', element: <Navigate replace to="/app/Hyper/FullGraph" /> },
  { path: '/Hyper/files', element: <Navigate replace to="/app/Hyper/files" /> },
  { path: '/API', element: <Navigate replace to="/app/Hyper/chat" /> },
  { path: '/Setting', element: <Navigate replace to="/app/Setting" /> },
  { path: '*', element: <NotFoundPage /> },
]
