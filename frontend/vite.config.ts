import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({ base: '/', plugins: [svelte()], build: { rollupOptions: { input: { main: 'index.html', analytics: 'analytics.html', accessLogs: 'access-logs.html', embed: 'embed.html', embedBuilder: 'embed-builder.html' } } }, server: { proxy: { '/api': 'http://127.0.0.1:8000' } } });
