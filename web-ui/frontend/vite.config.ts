import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import eslintPlugin from 'vite-plugin-eslint'
import { viteMockServe } from 'vite-plugin-mock'

import path from 'path'
import proxy from './config/proxy'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    eslintPlugin({
      include: ['src/**/*.js', 'src/**/*.ts', 'src/**/*.tsx', 'src/*.js', 'src/*.ts', 'src/*.tsx']
    }),
    viteMockServe({
      // default
      localEnabled: mode === 'mock',
      mockPath: './config/mock'
    })
  ],
  resolve: {
    extensions: ['.mjs', '.js', '.jsx', '.ts', '.tsx', '.json', '.sass', '.scss'], // å¿½ç•¥è¾“å…¥çš„æ‰©å±•å
    alias: [
      { find: '@', replacement: path.resolve(__dirname, 'src') },
      { find: '~', replacement: path.resolve(__dirname, './node_modules') },
      {
        find: '@components',
        replacement: path.resolve(__dirname, 'src/components')
      },
      { find: '@config', replacement: path.resolve(__dirname, 'config') }
      // {
      //   find: '@antd/dist/reset.css',
      //   replacement: path.join(__dirname, 'node_modules/antd/dist/reset.css')
      // }
      // // { find: 'antd', replacement: path.join(__dirname, 'node_modules/antd/dist/antd.js') },
      // // {
      // //   find: '@ant-design/icons',
      // //   replacement: path.join(__dirname, 'node_modules/@ant-design/icons/dist/index.umd.js')
      // // }
    ]
  },
  css: {
    preprocessorOptions: {
      less: {
        // æ”¯æŒå†…è” JavaScript
        javascriptEnabled: true
      }
    }
  },
  server: {
    proxy: proxy[mode]
  },
  build: {
    // æ‰“åŒ…å‡ºmapæ–‡ä»¶
    sourcemap: false
  }
}))
