PLATFORM ?= linux/amd64
NETWORK  ?= none
RESULTS  ?= results.json
JOBS     ?= 4

.PHONY: download benchmark

download:
	@jq -r '.[].image' tasks.json | sort -u | xargs -P $(JOBS) -I{} \
		sh -c 'docker pull --quiet --platform $(PLATFORM) "{}" >/dev/null \
			&& echo "ok   {}" || echo "FAIL {}"'

benchmark:
	@mkdir -p logs
	@jq -r '.[] | [.name, .image, .cpus, .memory_mb] | @tsv' tasks.json | \
	while IFS="$$(printf '\t')" read -r task img cpus mem; do \
		echo "==> $$task" >&2; \
		start=$$(date +%s); \
		docker run --rm --platform $(PLATFORM) --network $(NETWORK) \
			--cpus "$$cpus" --memory "$$mem"m \
			-v "$(CURDIR)/tasks/$$task:/solution:ro" \
			"$$img" bash /solution/solve.sh >"logs/$$task.log" 2>&1; \
		rc=$$?; elapsed=$$(( $$(date +%s) - start )); \
		echo "    exit=$$rc  $${elapsed}s" >&2; \
		jq -n --arg t "$$task" --argjson r "$$rc" --argjson s "$$elapsed" \
			'{task:$$t, exit_code:$$r, seconds:$$s}'; \
	done | jq -s '.' > $(RESULTS)
	@jq -r '.[] | "\(.task)\t\(.exit_code)\t\(.seconds)s"' $(RESULTS)
