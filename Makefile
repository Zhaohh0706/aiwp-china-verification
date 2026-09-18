PY := python
SRC := PYTHONPATH=src $(PY)

.PHONY: data verify figures test all

all: data verify figures

data:
	$(SRC) -u -m aiwp.build_dataset
	$(SRC) -u -m aiwp.build_dataset --variable wind_speed_10m
	$(SRC) -u -m aiwp.build_dataset --ai
	$(SRC) -u -m aiwp.build_dataset --ai --variable wind_speed_10m
	$(SRC) -u -m aiwp.build_dataset --ai --variable shortwave_radiation

verify:
	$(SRC) -u -m aiwp.run_verification

figures:
	$(SRC) -m aiwp.make_figures

test:
	$(SRC) -m pytest tests -q
