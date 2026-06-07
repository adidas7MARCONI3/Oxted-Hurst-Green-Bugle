import httpx
from dataclasses import dataclass


@dataclass
class WeatherSummary:
    description: str          # human-readable, e.g. "Cloudy with showers, 14°C"
    temperature_c: float
    precipitation_mm: float
    wind_kmh: float
    wmo_code: int             # WMO weather interpretation code


# WMO code → plain English
_WMO_DESCRIPTIONS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail",
}


class WeatherGatherer:
    API_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, latitude: float, longitude: float, timezone: str = "Europe/London"):
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = timezone

    def fetch_today(self) -> WeatherSummary:
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "current": "temperature_2m,precipitation,wind_speed_10m,weather_code",
            "timezone": self.timezone,
        }
        resp = httpx.get(self.API_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()["current"]

        code = data["weather_code"]
        temp = data["temperature_2m"]
        precip = data["precipitation"]
        wind = data["wind_speed_10m"]
        desc_base = _WMO_DESCRIPTIONS.get(code, "Variable conditions")

        return WeatherSummary(
            description=f"{desc_base}, {temp:.0f}°C",
            temperature_c=temp,
            precipitation_mm=precip,
            wind_kmh=wind,
            wmo_code=code,
        )
