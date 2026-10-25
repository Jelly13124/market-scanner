# Market Scanner 前端

React 18、TypeScript、Vite；代码位于 src/。

```bash
npm install
npm run dev
npm run build
npm run lint
```

VITE_API_URL 在构建时决定后端地址；本地开发通常指向 http://127.0.0.1:8001，生产部署由构建配置决定。不要在 VITE_* 中放置模型或数据库机密。

行情不再展示付费 tier 徽标；扫描按钮不依赖模型 key。Analyze 的可用模型状态由后端的 BYOK/Ollama 配置决定。FD 设置仅用于显式旧兼容入口。
