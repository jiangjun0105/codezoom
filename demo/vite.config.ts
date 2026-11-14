import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

/**
 * In `npm run dev`, serve the same handler that Vercel runs from api/ask.ts, so live
 * mode can be tried locally. The static build never includes it.
 */
function devApi(): Plugin {
  return {
    name: "codezoom-dev-api",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/api/ask", async (req, res) => {
        try {
          const mod = await server.ssrLoadModule("/api/ask.ts");
          const chunks: Buffer[] = [];
          for await (const c of req) chunks.push(c as Buffer);
          const request = new Request("http://local/api/ask", {
            method: req.method,
            headers: { "content-type": "application/json" },
            body: req.method === "POST" ? Buffer.concat(chunks) : undefined,
          });
          const response: Response = req.method === "POST" ? await mod.POST(request) : mod.GET();
          res.statusCode = response.status;
          response.headers.forEach((v, k) => res.setHeader(k, v));
          res.end(await response.text());
        } catch (err) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(err) }));
        }
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  // make .env.local visible to the dev API handler; nothing here reaches the client bundle
  Object.assign(process.env, loadEnv(mode, process.cwd(), ""));
  return {
    // DEMO_BASE=/codezoom/ when the site is served from a subpath
    base: process.env.DEMO_BASE || "/",
    plugins: [react(), devApi()],
    build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
  };
});
