<script lang="ts">
	// UI fix D: concurrent-experiment activity lanes. One aggregate rail on top,
	// one lane per experiment below — identity via LABELS (never hue-cycling);
	// color stays reserved for state per the color discipline. Fed by the
	// server's replay ring (survives navigation) + live refresh.
	type Ev = { experiment_id: string | null; at: string; type: string };
	let {
		events = [],
		labels = {},
		windowMinutes = 90
	}: {
		events: Ev[];
		labels?: Record<string, string>;
		windowMinutes?: number;
	} = $props();

	const now = $derived(Date.now());
	const t0 = $derived(now - windowMinutes * 60e3);
	const beats = $derived(
		events
			.filter((e) => e.type === 'unit.progress' && e.at && Date.parse(e.at) >= t0)
			.map((e) => ({ x: (Date.parse(e.at) - t0) / (windowMinutes * 60e3), exp: e.experiment_id }))
	);
	const lanes = $derived(
		[...new Set(beats.map((b) => b.exp).filter((x): x is string => !!x))].sort()
	);
	const short = (id: string) => labels[id] ?? id.replace(/^exp-/, '').slice(0, 10);
</script>

{#if beats.length}
	<div class="lanestrip">
		<div class="lane">
			<span class="lbl">all activity</span>
			<div class="rail">
				{#each beats as b, i (i)}<span class="tick agg" style="left:{(b.x * 100).toFixed(2)}%"
					></span>{/each}
			</div>
		</div>
		{#each lanes as exp (exp)}
			<div class="lane">
				<span class="lbl" title={exp}>{short(exp)}</span>
				<div class="rail">
					{#each beats.filter((b) => b.exp === exp) as b, i (i)}<span
							class="tick"
							style="left:{(b.x * 100).toFixed(2)}%"
						></span>{/each}
				</div>
			</div>
		{/each}
		<div class="axis"><span>−{windowMinutes}m</span><span>now</span></div>
	</div>
{/if}

<style>
	.lanestrip {
		margin: 0.6rem 0 0.9rem;
		border: 1px solid var(--border, #e2e2e2);
		border-radius: 8px;
		padding: 0.5rem 0.75rem;
	}
	.lane {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.18rem 0;
	}
	.lbl {
		flex: 0 0 9rem;
		font-size: 0.72rem;
		color: var(--muted, #777);
		font-family: ui-monospace, monospace;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		text-align: right;
	}
	.rail {
		position: relative;
		flex: 1;
		height: 10px;
		background: var(--rail, #f2f2f0);
		border-radius: 5px;
		overflow: hidden;
	}
	.tick {
		position: absolute;
		top: 1px;
		bottom: 1px;
		width: 2px;
		border-radius: 1px;
		background: var(--ink, #555);
		opacity: 0.85;
	}
	.tick.agg {
		background: var(--muted, #999);
	}
	.axis {
		display: flex;
		justify-content: space-between;
		font-size: 0.68rem;
		color: var(--muted, #999);
		margin-top: 0.15rem;
		padding-left: 9.6rem;
	}
</style>
