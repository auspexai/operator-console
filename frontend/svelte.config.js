import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
	},
	kit: {
		// Static export: SvelteKit pre-renders every page to HTML at build
		// time. The FastAPI backend serves the built bundle. No SSR; no
		// server-side data fetching per request. Per operator_console_design.md §16
		// (Q-O1 resolution: static export sufficient; SSR overkill for private
		// auth-gated UI).
		adapter: adapter({
			fallback: 'index.html', // SPA fallback for client-side routing
			pages: 'build',
			assets: 'build',
			precompress: false,
			strict: true
		}),
		// O-M1 has no nav / routes yet, so prerender is the default behavior.
		prerender: {
			handleHttpError: 'warn'
		}
	}
};

export default config;
