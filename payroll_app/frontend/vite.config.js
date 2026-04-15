import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// usePolling is required when the project lives on a Windows-mounted drive (/mnt/f/...)
// because inotify does not fire for cross-filesystem changes in WSL.
export default defineConfig({
  plugins: [react()],
  server: {
    watch: {
      usePolling: true,
      interval: 500,
    },
  },
})
