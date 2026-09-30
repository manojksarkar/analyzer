import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Tailwind v4 emits nested CSS, range media queries and color-mix(); older browsers
// (the offline server's) drop those rules. Lower them to Chrome/Edge 99, Firefox 97,
// Safari 15.4 — `css` covers the dev server, `build.cssTarget` covers `npm run build`.
export default defineConfig({
  plugins: [tailwindcss(), react()],
  css: {
    transformer: 'lightningcss',
    lightningcss: { targets: { chrome: 99 << 16, edge: 99 << 16, firefox: 97 << 16, safari: (15 << 16) | (4 << 8) } },
  },
  build: { cssTarget: ['chrome99', 'edge99', 'firefox97', 'safari15.4'] },
})
