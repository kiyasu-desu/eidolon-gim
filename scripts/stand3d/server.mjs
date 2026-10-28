// Loopback-only harness for the product engine, owned and stopped by each run.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const ts = require('typescript');
export const {chromium} = require('playwright');
const modules = path.join(root, 'frontend/src/components/conversations/stand');

export async function serve(run, {generation = false} = {}) {
  const html = `<!doctype html><meta charset="utf-8"><script type="importmap">{"imports":{"three":"/three/three.module.js"}}</script><style>body{margin:0;background:#e3e8ef}canvas{width:100vw;height:100vh;display:block}</style><canvas></canvas><script type="module">
    import {Stand3DEngine} from '/engine/Stand3DEngine.js';
    const engine=new Stand3DEngine(document.querySelector('canvas'),'full',1,'linear');
    engine.setStill(true);engine.setPaused(true);await engine.load({id:'pipeline',url:new URLSearchParams(location.search).has('baseline')?'/baseline':'/assets'});
    engine.setPaused(true);window.engine=engine;window.ready=true;
  </script>`;
  const scriptCache = new Map();
  const server = http.createServer((request, response) => {
    try {
      const url = new URL(request.url, 'http://localhost');
      if (url.pathname === '/') {response.setHeader('content-type', 'text/html; charset=utf-8');return response.end(html);}
      if (url.pathname === '/favicon.ico') {response.statusCode=204;return response.end();}
      const name = path.basename(url.pathname);
      if (/^\/(engine|lib)\/[^/]+\.js$/.test(url.pathname)) {
        if (!scriptCache.has(url.pathname)) {
          const source = fs.readFileSync(url.pathname.startsWith('/engine/') ? path.join(modules, name.replace(/\.js$/, '.ts')) : path.join(root, 'frontend/src/lib', name.replace(/\.js$/, '.ts')), 'utf8');
          const js = ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
            .replace(/"@\/lib\/([^"\n]+)"/g, '"/lib/$1.js"').replace(/"\.\/([^"\n]+)"/g, '"./$1.js"');
          scriptCache.set(url.pathname, js);
        }
        response.setHeader('content-type', 'text/javascript');return response.end(scriptCache.get(url.pathname));
      }
      let file;
      if (url.pathname.startsWith('/three/')) file = path.join(root, 'frontend/node_modules/three/build', name);
      else if (url.pathname === '/hand_surface_probe.mjs' || url.pathname === '/cloth_penetration_probe.mjs') file = path.join(root, 'scripts/stand3d', name);
      else if (/^\/(assets|baseline)\//.test(url.pathname)) {
        const baseline = url.pathname.startsWith('/baseline/');
        const relative = decodeURIComponent(url.pathname.slice(baseline ? 10 : 8));
        const folder = path.join(run, generation || baseline ? 'inputs/assets' : 'candidate');
        file = path.resolve(folder, relative);
        if (!file.startsWith(folder + path.sep)) {response.statusCode=403;return response.end();}
        if (generation && !baseline && relative === 'animations.json') file = path.join(run, 'source-animations.json');
      }
      if (!file || !fs.existsSync(file)) {response.statusCode=404;return response.end();}
      response.setHeader('content-type', /\.(m?js)$/.test(file) ? 'text/javascript' : file.endsWith('.png') ? 'image/png' : file.endsWith('.json') ? 'application/json' : 'application/octet-stream');
      fs.createReadStream(file).on('error',()=>response.destroy()).pipe(response);
    } catch (error) {response.statusCode=500;response.end(String(error));}
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  return {url:`http://127.0.0.1:${server.address().port}`,close:()=>new Promise((resolve,reject)=>{server.close(error=>error?reject(error):resolve());server.closeAllConnections();})};
}
