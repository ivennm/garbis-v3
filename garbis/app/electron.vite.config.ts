import { resolve } from 'node:path'
import { defineConfig } from 'electron-vite'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'

/** `npm run dev` only: React fast refresh injects an inline script, which the strict CSP would block. */
const devCsp: Plugin = {
  name: 'garbis-dev-csp',
  apply: 'serve',
  transformIndexHtml: (html) => html.replace("script-src 'self' blob:", "script-src 'self' 'unsafe-inline' blob:")
}

export default defineConfig({
  main: {},
  preload: {},
  renderer: {
    resolve: {
      alias: { '@renderer': resolve('src/renderer/src') }
    },
    plugins: [react(), devCsp]
  }
})
