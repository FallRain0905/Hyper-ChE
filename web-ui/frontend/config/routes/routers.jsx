import { lazy } from 'react'
import NotFoundPage from '@/404'
import App from '@/App'
import ErrorPage from '@/ErrorPage'
const Home = lazy(() => import('@/pages/Home'))
const Landing = lazy(() => import('@/pages/Landing'))
const WhyHypergraph = lazy(() => import('@/pages/Landing/WhyHypergraph'))
const TryDemo = lazy(() => import('@/pages/Landing/TryDemo'))
const Files = lazy(() => import('@/pages/Files'))
const Graph = lazy(() => import('@/pages/Hyper/Graph'))
const FullGraph = lazy(() => import('@/pages/Hyper/FullGraph'))
const HyperDB = lazy(() => import('@/pages/Hyper/DB'))
const Setting = lazy(() => import('@/pages/Setting'))
const Admin = lazy(() => import('@/pages/Admin'))
const DocumentConvert = lazy(() => import('@/pages/DocumentConvert'))
const PromptStudio = lazy(() => import('@/pages/Prompts'))
const Providers = lazy(() => import('@/pages/Providers'))
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
    errorElement: <ErrorPage />,
  },
  {
    path: '/why-hypergraph',
    element: <WhyHypergraph />,
    errorElement: <ErrorPage />,
  },
  {
    path: PUBLIC_DEMO.route,
    element: <TryDemo />,
    errorElement: <ErrorPage />,
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
