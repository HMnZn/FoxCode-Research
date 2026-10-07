import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5273, strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8877' } },
  build: { outDir: 'dist', emptyOutDir: true },
})
