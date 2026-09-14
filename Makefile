PY := python
SRC := PYTHONPATH=src $(PY)

.PHONY: data verify figures test all

all: data verify figures

data:
	$(SRC) -u -m aiwp.build_dataset

verify:
	$(SRC) -u -m aiwp.run_verification

figures:
	$(SRC) -m aiwp.make_figures

test:
	$(SRC) -m pytest tests -q
