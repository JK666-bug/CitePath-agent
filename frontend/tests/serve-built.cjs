// Optional serverless browser testing: fulfill built SPA files directly from disk.
// The API mock registered afterwards takes precedence over this asset route.
const fs = require('node:fs')
const path = require('node:path')

async function serveBuilt(page, directory, origin) {
  if (!directory) return
  const root = path.resolve(directory)
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' }
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (url.origin !== new URL(origin).origin) return route.abort('blockedbyclient')
    let target = path.resolve(root, '.' + decodeURIComponent(url.pathname))
    const relative = path.relative(root, target)
    if (relative.startsWith('..') || path.isAbsolute(relative)) return route.fulfill({ status: 404, body: '' })
    if (!fs.existsSync(target) || !fs.statSync(target).isFile()) target = path.join(root, 'index.html')
    await route.fulfill({ contentType: types[path.extname(target)] || 'application/octet-stream', body: fs.readFileSync(target) })
  })
}

module.exports = { serveBuilt }
