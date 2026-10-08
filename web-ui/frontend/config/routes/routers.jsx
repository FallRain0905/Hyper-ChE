import NotFoundPage from '@/404'
import App from '@/App'
import ErrorPage from '@/ErrorPage'
import Home from '@/pages/Home'
import Landing from '@/pages/Landing'
import WhyHypergraph from '@/pages/Landing/WhyHypergraph'
import TryDemo from '@/pages/Landing/TryDemo'
import Files from '@/pages/Files'
import Graph from '@/pages/Hyper/Graph'
import FullGraph from '@/pages/Hyper/FullGraph'
import HyperDB from '@/pages/Hyper/DB'
import Setting from '@/pages/Setting'
import Admin from '@/pages/Admin'
import DocumentConvert from '@/pages/DocumentConvert'
import PromptStudio from '@/pages/Prompts'
import Providers from '@/pages/Providers'
import { PUBLIC_DEMO } from '@/config/publicDemo'
import {
  DatabaseOutlined,
  DeploymentUnitOutlined,
  FileAddOutlined,
  ProjectOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  SafetyCertificateOutlined,
  SmileFilled,
  ApiOutlined,
  FileTextOutlined,
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
    path: PUBLIC_DEMO.route,
    element: <TryDemo />,
  },
  {
    path: PUBLIC_DEMO.legacyRoute,
    element: <Navigate replace to={PUBLIC_DEMO.route} />,
  },
  {
    path: '/demo/pfas',
    element: <Navigate replace to={PUBLIC_DEMO.route} />,
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
        path: '/app/convert',
        name: '文档转换',
        icon: <FileAddOutlined />,
        element: <DocumentConvert />,
      },
      {
        path: '/app/prompts',
        name: '领域提示词',
        icon: <FileTextOutlined />,
        element: <PromptStudio />,
      },
      {
        path: '/app/providers',
        name: 'API 渠道',
        icon: <ApiOutlined />,
        element: <Providers />,
      },
      {
        path: '/app/Setting',
        name: '系统设置',
        icon: <SettingOutlined />,
        element: <Setting />,
      },
      {
        path: '/app/admin',
        name: '管理员后台',
        icon: <SafetyCertificateOutlined />,
        element: <Admin />,
      },
    ],
  },
  { path: '/Hyper/chat', element: <Navigate replace to="/app/Hyper/chat" /> },
  { path: '/Hyper/show', element: <Navigate replace to="/app/Hyper/show" /> },
  { path: '/Hyper/DB', element: <Navigate replace to="/app/Hyper/DB" /> },
  { path: '/Hyper/FullGraph', element: <Navigate replace to="/app/Hyper/FullGraph" /> },
  { path: '/Hyper/files', element: <Navigate replace to="/app/Hyper/files" /> },
  { path: '/API', element: <Navigate replace to="/app/Hyper/chat" /> },
  { path: '/convert', element: <Navigate replace to="/app/convert" /> },
  { path: '/prompts', element: <Navigate replace to="/app/prompts" /> },
  { path: '/providers', element: <Navigate replace to="/app/providers" /> },
  { path: '/Setting', element: <Navigate replace to="/app/Setting" /> },
  { path: '/admin', element: <Navigate replace to="/app/admin" /> },
  { path: '*', element: <NotFoundPage /> },
]
