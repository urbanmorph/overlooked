// /mcp: the agent server (Model Context Protocol). See lib/mcp.js.
import { handle } from './lib/mcp.js';

export const onRequest = ({ request, env, waitUntil }) => handle(request, env, waitUntil);
