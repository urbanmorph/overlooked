// Serves /data/* from the private R2 bucket (binding DATA), with Range, HEAD and ETag support.
// The cache/ folder in the bucket is internal and never served.

const SHORT = 'public, max-age=300';

export async function onRequest({ request, env, params }) {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method not allowed', { status: 405, headers: { Allow: 'GET, HEAD' } });
  }
  const key = (params.path || []).join('/');
  if (!key || key.startsWith('cache/') || key.includes('..')) {
    return new Response('Not found', { status: 404 });
  }

  const obj = request.method === 'HEAD'
    ? await env.DATA.head(key)
    : await env.DATA.get(key, { range: request.headers, onlyIf: request.headers });
  if (!obj) return new Response('Not found', { status: 404 });

  const headers = new Headers();
  obj.writeHttpMetadata(headers);
  headers.set('ETag', obj.httpEtag);
  headers.set('Accept-Ranges', 'bytes');
  if (!headers.has('Cache-Control')) headers.set('Cache-Control', SHORT);
  if (key === 'latest.json') headers.set('Cache-Control', SHORT);

  // onlyIf did not match: the browser's copy is current.
  if (request.method === 'GET' && !('body' in obj)) {
    return new Response(null, { status: 304, headers });
  }
  if (request.method === 'HEAD') {
    headers.set('Content-Length', String(obj.size));
    return new Response(null, { status: 200, headers });
  }
  if (obj.range && request.headers.has('Range')) {
    const { offset = 0, length = obj.size - offset } = obj.range;
    headers.set('Content-Range', `bytes ${offset}-${offset + length - 1}/${obj.size}`);
    headers.set('Content-Length', String(length));
    return new Response(obj.body, { status: 206, headers });
  }
  headers.set('Content-Length', String(obj.size));
  return new Response(obj.body, { status: 200, headers });
}
