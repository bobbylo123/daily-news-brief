import requests
from datetime import datetime
import pytz

class WeatherFetcher:
    def __init__(self):
        self.brisbane_coords = {'lat': -27.4698, 'lon': 153.0251}

    def get_brisbane_weather(self) -> dict:
        """Fetch Brisbane weather data"""
        try:
            response = requests.get(
                f'https://api.open-meteo.com/v1/forecast?latitude={self.brisbane_coords["lat"]}&longitude={self.brisbane_coords["lon"]}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,uv_index&timezone=Australia%2FBrisbane',
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                current = data.get('current', {})
                return {
                    'temperature': round(current.get('temperature_2m', 0)),
                    'humidity': current.get('relative_humidity_2m', 0),
                    'wind_speed': round(current.get('wind_speed_10m', 0)),
                    'uv_index': round(current.get('uv_index', 0), 1),
                    'condition': self._get_weather_description(current.get('weather_code', 0)),
                    'rain_probability': 0
                }
        except Exception as e:
            print(f"Error fetching weather: {e}")

        return self._get_fallback_weather()

    def _get_weather_description(self, code: int) -> str:
        descriptions = {
            0: 'Clear sky',
            1: 'Mainly clear',
            2: 'Partly cloudy',
            3: 'Overcast',
            45: 'Foggy',
            48: 'Foggy',
            51: 'Light drizzle',
            53: 'Moderate drizzle',
            55: 'Dense drizzle',
            61: 'Slight rain',
            63: 'Moderate rain',
            65: 'Heavy rain',
            71: 'Slight snow',
            73: 'Moderate snow',
            75: 'Heavy snow',
            77: 'Snow grains',
            80: 'Slight rain showers',
            81: 'Moderate rain showers',
            82: 'Violent rain showers',
            85: 'Slight snow showers',
            86: 'Heavy snow showers',
            95: 'Thunderstorm',
            96: 'Thunderstorm with hail',
            99: 'Thunderstorm with hail'
        }
        return descriptions.get(code, 'Unknown')

    def _get_fallback_weather(self) -> dict:
        return {
            'temperature': 28,
            'humidity': 65,
            'wind_speed': 12,
            'uv_index': 7.5,
            'condition': 'Partly cloudy',
            'rain_probability': 20
        }
