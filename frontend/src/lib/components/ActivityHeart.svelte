<script lang="ts">
	import { untrack } from 'svelte';

	// The ops/maintainer "heart monitor" (surface_liveness_and_activity_view_
	// design.md §3). Answers "is the network healthy?" at a glance: a fleet
	// throughput pulse (units completed network-wide), connection vitals (workers
	// active / on hold / awaiting your review), a plain-language line, and the
	// few numbers that matter. Same anatomy + identity as the researcher heart,
	// a different heart. The pulse accumulates client-side from the triage poll.
	let {
		pulseTotal,
		activeWorkers,
		holds,
		runningExperiments,
		awaitingReview,
		online = null
	}: {
		pulseTotal: number; // cumulative units completed network-wide (the pulse counter)
		activeWorkers: number;
		holds: number; // quarantined + paused + self-paused
		runningExperiments: number;
		awaitingReview: number;
		online?: boolean | null;
	} = $props();

	type Sample = { t: number; c: number };
	const MAX_SAMPLES = 160;
	let history = $state<Sample[]>([]);

	$effect(() => {
		const c = pulseTotal ?? 0;
		void activeWorkers; // re-sample every poll so the baseline draws between beats
		const t = Date.now();
		untrack(() => {
			history = [...history, { t, c }].slice(-MAX_SAMPLES);
		});
	});

	type Beat = { t: number; delta: number };
	const beats = $derived<Beat[]>(
		history.slice(1).map((s, i) => ({ t: s.t, delta: Math.max(0, s.c - history[i].c) }))
	);
	const maxDelta = $derived(Math.max(1, ...beats.map((b) => b.delta)));
	const beatTimes = $derived(beats.filter((b) => b.delta > 0).map((b) => b.t));
	const lastBeatT = $derived(beatTimes.length ? beatTimes[beatTimes.length - 1] : null);

	let now = $state(Date.now());
	$effect(() => {
		const id = setInterval(() => (now = Date.now()), 1000);
		return () => clearInterval(id);
	});
	const sinceLastBeatMs = $derived(lastBeatT != null ? now - lastBeatT : null);

	function ago(ms: number | null): string {
		if (ms == null) return '—';
		const s = Math.max(0, Math.round(ms / 1000));
		if (s < 60) return `${s}s ago`;
		const m = Math.round(s / 60);
		return m < 60 ? `${m}m ago` : `${Math.round(m / 60)}h ago`;
	}

	// Health, in ops terms. No workers = a real flatline worth alarming on; work
	// flowing = beating; workers up but quiet = idle/ready (the reassurance).
	const flatlined = $derived(activeWorkers === 0);
	const beating = $derived(activeWorkers > 0 && (sinceLastBeatMs == null || sinceLastBeatMs < 12000));
	const idle = $derived(activeWorkers > 0 && !beating);

	// State-led — the worker COUNT lives in the vitals (with its dot), so the
	// line speaks to what the fleet is DOING, not how many are connected.
	const narration = $derived.by(() => {
		if (online === false) return 'coordinator unreachable';
		if (flatlined) return 'no workers connected — the fleet is dark';
		const parts: string[] = [];
		if (runningExperiments > 0)
			parts.push(`${runningExperiments} experiment${runningExperiments === 1 ? '' : 's'} running`);
		if (lastBeatT != null) parts.push(`last completion ${ago(sinceLastBeatMs)}`);
		else parts.push('idle · ready');
		if (awaitingReview > 0) parts.push(`${awaitingReview} awaiting review`);
		return parts.join(' · ');
	});
</script>

<section class="heart" class:flatlined>
	<header>
		<div class="pulse-dot" class:beating={beating && !flatlined} class:idle></div>
		<h3>Network</h3>
		<span class="status">{flatlined ? 'dark' : beating ? 'working' : 'idle'}</span>
	</header>

	<div class="strip" role="img" aria-label="fleet throughput pulse">
		{#if beats.length === 0}
			<p class="empty">listening to the fleet…</p>
		{:else}
			{#each beats as b (b.t)}
				<span
					class="bar"
					class:beat={b.delta > 0}
					style="height: {b.delta > 0 ? 18 + Math.round((b.delta / maxDelta) * 46) : 2}px"
					title="{b.delta} units completed"
				></span>
			{/each}
		{/if}
	</div>

	<p class="narration" class:reassure={idle} class:bad={flatlined || online === false}>{narration}</p>

	<div class="vitals">
		<span class="vital" class:bad={online === false}>
			<i class="dot" class:ok={online === true} class:down={online === false}></i>
			coordinator {online === false ? 'unreachable' : 'up'}
		</span>
		<span class="vital">
			<i class="dot" class:ok={activeWorkers > 0} class:down={flatlined}></i>
			{activeWorkers} worker{activeWorkers === 1 ? '' : 's'}
		</span>
		{#if holds > 0}
			<span class="vital warn">{holds} on hold</span>
		{/if}
	</div>

	<div class="metrics">
		<div class="metric">
			<span class="n">{pulseTotal}</span>
			<span class="l">units completed</span>
		</div>
		<div class="metric">
			<span class="n">{runningExperiments}</span>
			<span class="l">experiments running</span>
		</div>
		<div class="metric" class:attn={awaitingReview > 0}>
			<span class="n">{awaitingReview}</span>
			<span class="l">awaiting review</span>
		</div>
	</div>
</section>

<style>
	.heart {
		border: 1px solid #155e6b;
		border-radius: 12px;
		background: linear-gradient(180deg, #121a2e 0%, #0e1424 100%);
		padding: 1rem 1.1rem;
		display: flex;
		flex-direction: column;
		gap: 0.7rem;
	}
	.heart.flatlined {
		border-color: #5e1f28;
	}
	header {
		display: flex;
		align-items: center;
		gap: 0.55rem;
	}
	h3 {
		margin: 0;
		font-size: 0.95rem;
		font-weight: 600;
		color: #dbe2f0;
	}
	.status {
		margin-left: auto;
		font-size: 0.72rem;
		color: #8b93a7;
		text-transform: lowercase;
	}
	.pulse-dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: #5e1f28;
	}
	.pulse-dot.beating {
		background: #67e8f9;
		animation: beat 1.1s ease-out infinite;
	}
	.pulse-dot.idle {
		background: #155e6b;
	}
	@keyframes beat {
		0% {
			box-shadow: 0 0 0 0 rgba(103, 232, 249, 0.55);
		}
		70% {
			box-shadow: 0 0 0 8px rgba(103, 232, 249, 0);
		}
		100% {
			box-shadow: 0 0 0 0 rgba(103, 232, 249, 0);
		}
	}
	.strip {
		display: flex;
		align-items: flex-end;
		gap: 2px;
		height: 70px;
		padding: 4px 2px;
		background: #0a1120;
		border-radius: 8px;
		border: 1px solid #1a2236;
		overflow: hidden;
	}
	.bar {
		flex: 0 0 3px;
		min-width: 3px;
		background: #233049;
		border-radius: 2px;
		align-self: flex-end;
	}
	.bar.beat {
		background: #67e8f9;
	}
	.empty {
		margin: auto;
		color: #5b6478;
		font-size: 0.8rem;
	}
	.narration {
		margin: 0;
		font-size: 0.86rem;
		color: #b8bfd0;
	}
	.narration.reassure {
		color: #67e8f9;
	}
	.narration.bad {
		color: #fca5a5;
	}
	.vitals {
		display: flex;
		flex-wrap: wrap;
		gap: 0.9rem;
		font-size: 0.76rem;
		color: #9aa3b8;
	}
	.vital {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}
	.vital.bad {
		color: #fca5a5;
	}
	.vital.warn {
		color: #fbbf24;
	}
	.dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: #2a3450;
	}
	.dot.ok {
		background: #6ee7b7;
	}
	.dot.down {
		background: #fca5a5;
	}
	.metrics {
		display: flex;
		align-items: center;
		gap: 1.3rem;
	}
	.metric {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}
	.metric .n {
		font-size: 1.05rem;
		font-weight: 600;
		color: #e6ebf5;
		font-variant-numeric: tabular-nums;
	}
	.metric.attn .n {
		color: #fbbf24;
	}
	.metric .l {
		font-size: 0.68rem;
		color: #7c849a;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
</style>
