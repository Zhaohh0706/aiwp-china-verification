"""The stations this study verifies against, and why these ones.

Verification needs a truth source, and for surface temperature the only truth
that is both free and genuinely observed is METAR: hourly reports from airport
weather stations, archived since the 1970s by Iowa State's Mesonet, no account
required. Reanalysis would be easier and would not be an observation.

So the station list is airports. That is a real limitation and it is stated
rather than hidden: airports sit on flat open ground outside cities, which is
where they were put on purpose. A model that is good at an airport is not
necessarily good over the urban core twenty kilometres away, and a temperature
verified at ZBAA is not the temperature in Beijing's third ring road.

The Chinese stations are the subject. The overseas ones are the control: if a
model looks bad over China, the first question is whether it looks bad
everywhere, and without a comparison group that question cannot be answered.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    slug: str
    name_zh: str
    icao: str
    latitude: float
    longitude: float
    timezone: str
    group: str  # "china" or "control"

    @property
    def is_china(self) -> bool:
        return self.group == "china"


# Coordinates are the airport's, taken from the same metadata the ICAO code is.
CHINA = [
    Station("beijing", "北京首都", "ZBAA", 40.0801, 116.5846, "Asia/Shanghai", "china"),
    Station("shanghai", "上海浦东", "ZSPD", 31.1434, 121.8052, "Asia/Shanghai", "china"),
    Station("guangzhou", "广州白云", "ZGGG", 23.3924, 113.2988, "Asia/Shanghai", "china"),
    Station("shenzhen", "深圳宝安", "ZGSZ", 22.6393, 113.8107, "Asia/Shanghai", "china"),
    Station("chengdu", "成都双流", "ZUUU", 30.5785, 103.9471, "Asia/Shanghai", "china"),
    Station("chongqing", "重庆江北", "ZUCK", 29.7196, 106.6416, "Asia/Shanghai", "china"),
    Station("qingdao", "青岛胶东", "ZSQD", 36.3620, 120.0882, "Asia/Shanghai", "china"),
    Station("hong-kong", "香港", "VHHH", 22.3089, 113.9145, "Asia/Hong_Kong", "china"),
    Station("taipei", "台北松山", "RCSS", 25.0377, 121.5149, "Asia/Taipei", "china"),
]

CONTROL = [
    Station("london", "伦敦希思罗", "EGLL", 51.4706, -0.4619, "Europe/London", "control"),
    Station("frankfurt", "法兰克福", "EDDF", 50.0264, 8.5431, "Europe/Berlin", "control"),
    Station("nyc", "纽约肯尼迪", "KJFK", 40.6398, -73.7789, "America/New_York", "control"),
    Station("tokyo", "东京羽田", "RJTT", 35.5523, 139.7798, "Asia/Tokyo", "control"),
]

# The eight PV stations from the power-forecasting study, at the coordinates
# recovered there from their own irradiance records (solar noon for longitude,
# day length for latitude, the station barometer for elevation).  They carry no
# ICAO code because they are not airports and have no METAR; irradiance at these
# points is verified against satellite retrieval instead.
#
# Verifying the weather at the same points the power model runs on is what joins
# the two studies: an irradiance error here is the input to a yield error there.
PV_SITES = [
    Station("pv01", "光伏 1 号站 50 MW", "", 40.55, 96.34, "Asia/Shanghai", "pv"),
    Station("pv02", "光伏 2 号站 130 MW", "", 37.45, 78.66, "Asia/Shanghai", "pv"),
    Station("pv03", "光伏 3 号站 30 MW", "", 30.10, 120.49, "Asia/Shanghai", "pv"),
    Station("pv04", "光伏 4 号站 130 MW", "", 31.00, 112.38, "Asia/Shanghai", "pv"),
    Station("pv05", "光伏 5 号站 110 MW", "", 30.25, 114.51, "Asia/Shanghai", "pv"),
    Station("pv06", "光伏 6 号站 35 MW", "", 20.10, 98.67, "Asia/Shanghai", "pv"),
    Station("pv07", "光伏 7 号站 30 MW", "", 24.25, 99.94, "Asia/Shanghai", "pv"),
    Station("pv08", "光伏 8 号站 30 MW", "", 25.00, 116.81, "Asia/Shanghai", "pv"),
]

ALL = CHINA + CONTROL
BY_SLUG = {s.slug: s for s in ALL + PV_SITES}
