import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolveBuildSha } from './scripts/resolve-build-sha.mjs';

// GitHub Actions supplies VITE_BUILD_SHA; Cloudflare Pages supplies CF_PAGES_COMMIT_SHA.
// Vite reads process.env after loading this config, so normalize the value here.
const buildSha = resolveBuildSha(process.env);
if (buildSha) process.env.VITE_BUILD_SHA = buildSha;

export default defineConfig({ base: '/', plugins: [svelte()], build: { rollupOptions: { input: { main: 'index.html', analytics: 'analytics.html', accessLogs: 'access-logs.html', embed: 'embed.html', embedBuilder: 'embed-builder.html', webhooks: 'webhooks.html' } } }, server: { proxy: { '^/api(?:/|$)': 'http://127.0.0.1:8000' } } });
