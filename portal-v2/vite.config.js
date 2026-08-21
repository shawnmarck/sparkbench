import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const sparkHost = process.env.SPARK_HOST || 'sparky'

export default defineConfig({
  base: '/v2/',
  plugins: [react()],
  build: {
    outDir: '../portal/v2',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': {
        target: `http://${sparkHost}`,
        changeOrigin: true,
      },
    },
  },
})
