import { mount } from 'svelte';
import App from './App.svelte';
import './style.css';
import './timetable.css';
import './layout.css';
import './responsive.css';

mount(App, { target: document.getElementById('app')! });

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js').catch(() => {});
}
