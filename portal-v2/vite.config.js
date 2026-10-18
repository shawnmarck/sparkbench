import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const sparkHost = process.env.SPARK_HOST || 'sparky'

export default defineConfig({
  base: '/',
  plugins: [react()],
  build: {
    outDir: '../portal',
    emptyOutDir: false,
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
