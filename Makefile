PLATFORM ?= linux/$(shell docker version --format '{{.Server.Arch}}')
NETWORK  ?= none
RESULTS  ?= results.json

.PHONY: build benchmark

build:
	@jq -r '.[].name' tasks.json | while read -r task; do \
		[ -d "tasks/$$task/env" ] || continue; \
		echo "==> $$task" >&2; \
		docker build --platform $(PLATFORM) -t "local/$$task" "tasks/$$task/env" || exit 1; \
	done

benchmark:
	@mkdir -p logs
	@jq -r '.[] | [.name, .cpus, .memory_mb] | @tsv' tasks.json | \
	while IFS="$$(printf '\t')" read -r task cpus mem; do \
		[ -d "tasks/$$task/env" ] || continue; \
		echo "==> $$task" >&2; \
		start=$$(date +%s); \
		docker run --rm --platform $(PLATFORM) --network $(NETWORK) \
			--cpus "$$cpus" --memory "$$mem"m \
			-v "$(CURDIR)/tasks/$$task:/solution:ro" \
			"local/$$task" bash /solution/solve.sh >"logs/$$task.log" 2>&1; \
		rc=$$?; elapsed=$$(( $$(date +%s) - start )); \
		echo "    exit=$$rc  $${elapsed}s" >&2; \
		jq -n --arg t "$$task" --argjson r "$$rc" --argjson s "$$elapsed" \
			'{task:$$t, exit_code:$$r, seconds:$$s}'; \
	done | jq -s '.' > $(RESULTS)
	@jq -r '.[] | "\(.task)\t\(.exit_code)\t\(.seconds)s"' $(RESULTS)
