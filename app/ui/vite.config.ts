import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 브라우저는 같은 origin 의 /api 만 부른다. dev 에서는 Vite 가 BFF 로 넘긴다.
// KEM_BFF_URL 은 dev 서버(Node) 쪽 값이라 브라우저 번들에 들어가지 않는다 (VITE_ 접두사 없음).
const bff = process.env.KEM_BFF_URL ?? 'http://127.0.0.1:8610'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5610,
    proxy: { '/api': bff },
  },
})
