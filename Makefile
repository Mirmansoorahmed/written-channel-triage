# written-channel-triage — common tasks.
#
# The default path is offline and dependency-free: `make test` and `make eval`
# need only the standard library + pytest. The real-model targets (`eval-real`,
# `api`) need the optional extras and a running Ollama server; they are meant to
# be run on your own machine, not in CI.

PY ?= python3
export PYTHONPATH := src

.PHONY: help test eval eval-real data datasheet overlap-check docs api install-models install-api install-eval

help:
	@echo "test          run the unit tests (stdlib + pytest, offline)"
	@echo "data          generate the seeded dataset and run the leakage gate"
	@echo "datasheet     regenerate docs/datasheet.md from data/*.jsonl"
	@echo "overlap-check fail if any test item is >= 0.9 similar to train/examples"
	@echo "eval          run the offline eval subset (System A; B/C -> pending real run)"
	@echo "eval-real     run all three systems with the real models (needs Ollama + extras)"
	@echo "docs          regenerate the README + cost tables from eval/results-v2.json"
	@echo "api           run the FastAPI service locally (needs .[api])"
	@echo "install-*     pip install the matching optional extra"

test:
	$(PY) -m pytest

data:
	$(PY) -m data.generator
	$(PY) -m data.overlap_check

datasheet:
	$(PY) -m data.datasheet

overlap-check:
	$(PY) -m data.overlap_check

eval:
	$(PY) -m eval.harness_v2

eval-real:
	TRIAGE_EVAL_REAL=1 $(PY) -m eval.harness_v2

docs:
	$(PY) -m docs.generate_tables

api:
	$(PY) -m uvicorn triage.api:app --host 0.0.0.0 --port 8000

install-models:
	$(PY) -m pip install -e ".[models]"

install-api:
	$(PY) -m pip install -e ".[api]"

install-eval:
	$(PY) -m pip install -e ".[eval]"
