PLATFORM ?= linux/$(shell docker version --format '{{.Server.Arch}}')
NETWORK  ?= none
RESULTS  ?= results/benchmark.json

# soak (concurrency) params
NCPUS        ?= 4
DURATION     ?= 20
SOAK_RESULTS ?= results/soak.json
ONLY         ?=

.PHONY: build benchmark soak

build:
	@jq -r '.[].name' tasks.json | while read -r task; do \
		[ -d "tasks/$$task/env" ] || continue; \
		echo "==> $$task" >&2; \
		docker build --platform $(PLATFORM) -t "local/$$task" "tasks/$$task/env" || exit 1; \
	done

benchmark:
	@mkdir -p logs $(dir $(RESULTS))
	@jq -r '.[] | [.name, .cpus, .memory_mb] | @tsv' tasks.json | \
	while IFS="$$(printf '\t')" read -r task cpus mem; do \
		[ -d "tasks/$$task/env" ] || continue; \
		echo "==> $$task" >&2; \
		start=$$(date +%s%3N); \
		docker run --rm --platform $(PLATFORM) --network $(NETWORK) \
			--cpus "$$cpus" --memory "$$mem"m \
			-v "$(CURDIR)/tasks/$$task:/solution:ro" \
			"local/$$task" bash /solution/solve.sh >"logs/$$task.log" 2>&1; \
		rc=$$?; elapsed=$$(( $$(date +%s%3N) - start )); \
		echo "    exit=$$rc  $${elapsed}ms" >&2; \
		jq -n --arg t "$$task" --argjson r "$$rc" --argjson s "$$elapsed" \
			'{task:$$t, exit_code:$$r, ms:$$s}'; \
	done | jq -s '.' > $(RESULTS)
	@jq -r '.[] | "\(.task)\t\(.exit_code)\t\(.ms)ms"' $(RESULTS)

# Concurrency soak: one lane per task, each lane runs its own oracle back-to-back
# (full container standup/teardown per run) until DURATION elapses. All lanes run
# at once (heterogeneous, ~n_tasks live), pinned to a fixed NCPUS-core budget via
# --cpuset-cpus so the throughput number is comparable machine-to-machine.
soak:
	@mkdir -p soak_logs $(dir $(SOAK_RESULTS))
	@rm -f soak_logs/*.tsv soak_logs/all.tsv
	@avail=$$(nproc); \
	if [ "$(NCPUS)" -gt "$$avail" ]; then \
		echo "NCPUS=$(NCPUS) exceeds available CPUs ($$avail); pick NCPUS<=$$avail" >&2; exit 1; \
	fi; \
	cpuset="0-$$(( $(NCPUS) - 1 ))"; \
	start=$$(date +%s); deadline=$$(( start + $(DURATION) )); \
	echo "soak: NCPUS=$(NCPUS) (cpuset $$cpuset)  DURATION=$(DURATION)s  platform $(PLATFORM)" >&2; \
	list=$$(jq -r '.[] | "\(.name):\(.memory_mb)"' tasks.json | while IFS=: read -r t m; do \
		[ -d "tasks/$$t/env" ] || continue; \
		if [ -n "$(ONLY)" ]; then case " $(ONLY) " in *" $$t "*) : ;; *) continue ;; esac; fi; \
		docker image inspect "local/$$t" >/dev/null 2>&1 || { echo "skip $$t (no local image)" >&2; continue; }; \
		echo "$$t:$$m"; \
	done); \
	n=0; \
	for item in $$list; do \
		task=$${item%%:*}; mem=$${item##*:}; \
		( ok=0; fail=0; \
		  while now=$$(date +%s); [ "$$now" -lt "$$deadline" ]; do \
			if timeout -k 10 $$(( deadline - now )) \
				docker run --rm --init --platform $(PLATFORM) --network $(NETWORK) \
				--cpuset-cpus "$$cpuset" --memory "$${mem}m" \
				--label "soak_session=$$start" \
				-v "$(CURDIR)/tasks/$$task:/solution:ro" \
				"local/$$task" bash /solution/solve.sh >/dev/null 2>&1; \
			then ok=$$(( ok + 1 )); \
			elif [ "$$(date +%s)" -ge "$$deadline" ]; then :; \
			else fail=$$(( fail + 1 )); fi; \
		  done; \
		  printf '%s\t%s\t%s\n' "$$task" "$$ok" "$$fail" > "soak_logs/$$task.tsv" ) & \
		n=$$(( n + 1 )); \
	done; \
	echo "launched $$n lanes on cpuset $$cpuset; running $(DURATION)s (in-flight runs killed at the deadline)..." >&2; \
	wait; \
	docker ps -q --filter "label=soak_session=$$start" | xargs -r docker kill >/dev/null 2>&1 || true; \
	elapsed=$$(( $$(date +%s) - start )); \
	cat soak_logs/*.tsv 2>/dev/null > soak_logs/all.tsv || true; \
	jq -Rs --argjson ncpus $(NCPUS) --argjson secs "$$elapsed" '[ split("\n")[] | select(length>0) | split("\t") | {task:.[0], completed:(.[1]|tonumber), failed:(.[2]|tonumber)} ] | {ncpus:$$ncpus, seconds:$$secs, total_completed:(map(.completed)|add // 0), total_failed:(map(.failed)|add // 0), tasks:sort_by(-.completed)}' soak_logs/all.tsv > $(SOAK_RESULTS); \
	echo "== soak done in $$elapsed s ==" >&2
	@jq -r '"NCPUS=\(.ncpus)  elapsed=\(.seconds)s  total_completed=\(.total_completed)  total_failed=\(.total_failed)"' $(SOAK_RESULTS)
	@echo "completed  failed  task"
	@jq -r '.tasks[] | "\(.completed)\t\(.failed)\t\(.task)"' $(SOAK_RESULTS)
