PY := python
SRC := PYTHONPATH=src $(PY)

.PHONY: data verify figures test all energy leaderboard hub hub-data

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

# The energy-province sets, to the end of last month.  Quota-bound: the forecast
# archive allows a few stations an hour, and cached stations are skipped on rerun.
END ?= $(shell date -v1d -v-1d +%Y-%m-%d 2>/dev/null || date -d "$$(date +%Y-%m-01) -1 day" +%Y-%m-%d)
energy:
	$(SRC) -u -m aiwp.build_dataset --ai --energy --variable wind_speed_10m --start 2025-03-01 --end $(END)
	$(SRC) -u -m aiwp.build_dataset --ai --energy --variable shortwave_radiation --start 2026-05-01 --end $(END)

leaderboard:
	$(SRC) -m aiwp.leaderboard

# Hub height: only four models publish 100 m wind, and the only truth available
# there is a reanalysis made by one of them.  The 10 m ERA5 run is the control
# that measures how much that is worth - it is not optional.
hub-data:
	$(SRC) -u -m aiwp.build_dataset --ai --energy --variable wind_speed_100m --start 2025-03-01 --end $(END)
	$(SRC) -u -m aiwp.build_dataset --ai --energy --variable wind_speed_10m_era5 --start 2025-03-01 --end $(END)

hub:
	$(SRC) -m aiwp.hub_height
