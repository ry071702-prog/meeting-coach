// コンテナ内でリポジトリ (読み取り専用マウント) を配る静的サーバー
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8", ".md": "text/markdown; charset=utf-8",
  ".py": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".vtt": "text/vtt; charset=utf-8",
};

export function start(ROOT = "/repo", PORT = 8010) {
  const srv = http.createServer((req, res) => {
    let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
    let file = path.join(ROOT, path.normalize(p));
    if (!file.startsWith(ROOT)) { res.writeHead(403).end(); return; }
    try {
      if (fs.statSync(file).isDirectory()) file = path.join(file, "index.html");
      const data = fs.readFileSync(file);
      res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
      res.end(data);
    } catch { res.writeHead(404).end("not found"); }
  });
  return new Promise((r) => srv.listen(PORT, "127.0.0.1", () => r(srv)));
}
