from datetime import datetime
import http.client
import json
from zoneinfo import ZoneInfo
from server import Json, HOST, PORT, OUTPUT_DATETIME_FORMAT, run_application
import re
import pytest

@pytest.fixture(scope="module", autouse=True)
def before_tests():
    stop_server = run_application()
    yield
    stop_server()

def test_render_server_time():
    tz_name = 'UTC'
    code, html = render_request('/')
    assert code == 200
    expected = datetime.now(ZoneInfo('UTC'))
    actual = get_datetime_from_html(html, tz_name)
    assert_datetimes(expected, actual)

def test_render_timezone_time():
    """positive"""
    tz_name = 'UTC'
    code, html = render_request(f'/{tz_name}')
    print('code', code)
    assert code == 200
    expected = datetime.now(ZoneInfo(tz_name))
    actual = get_datetime_from_html(html, tz_name)
    assert_datetimes(expected, actual)

    """negative"""
    code, _ = render_request('/asd')
    assert code == 400

def test_render_continent_city_time():
    """positive"""
    tz_name = 'Asia/Novosibirsk'
    code, html = render_request(f'/{tz_name}')
    assert code == 200
    expected = datetime.now(ZoneInfo(tz_name))
    actual = get_datetime_from_html(html, tz_name)
    assert_datetimes(expected, actual)

    """negative"""
    code, _ = render_request('/Europe/Europe')
    assert code == 400

def test_render_continent_country_city_time():
    """positive"""
    tz_name = 'America/Argentina/Buenos_Aires'
    code, html = render_request(f'/{tz_name}')
    assert code == 200
    expected = datetime.now(ZoneInfo(tz_name))
    actual = get_datetime_from_html(html, tz_name)
    assert_datetimes(expected, actual)

    """negative"""
    code, _ = render_request('/Europe/Europe/America')
    assert code == 400

def test_get_timezone_time():
    """positive"""
    tz_name = 'America/Argentina/Buenos_Aires'
    code, json = post_request('/api/v1/time', {'tz': tz_name})
    assert code == 200
    expected = datetime.now(ZoneInfo(tz_name))
    actual = get_datetime_from_json(json, tz_name)
    assert_datetimes(expected, actual)

    tz_name = 'UTC'
    code, json = post_request('/api/v1/time')
    assert code == 200
    expected = datetime.now(ZoneInfo(tz_name))
    actual = get_datetime_from_json(json, tz_name)
    assert_datetimes(expected, actual)

    """negative"""
    tz_name = 'merica/Argentina/Buenos_Aires'
    code, json = post_request('/api/v1/time', {'tz': tz_name})
    assert code == 400

def test_get_timezone_date():
    """positive"""
    tz_name = 'America/Argentina/Buenos_Aires'
    code, json = post_request('/api/v1/date', {'tz': tz_name})
    assert code == 200
    expected = str(datetime.now(ZoneInfo(tz_name)).date())
    actual = json.get('message')
    assert expected == actual

    tz_name = 'UTC'
    code, json = post_request('/api/v1/date')
    assert code == 200
    expected = str(datetime.now(ZoneInfo(tz_name)).date())
    actual = json.get('message')
    assert expected == actual
    
    """negative"""
    tz_name = 'America/rgentina/Buenos_Aires'
    code, json = post_request('/api/v1/time', {'tz': tz_name})
    assert code == 400

def test_get_dates_diff():
    """positive"""
    code, json = post_request('/api/v1/datediff', {
        'start': {
            'date': '12.20.2024 00:19:00',
            'tz': 'Europe/Moscow'
        },
        'end': {
            'date': '12:19am 2024-12-20',
            'tz': 'Asia/Novosibirsk'
        },
    })
    assert code == 200
    expected = '4:00:00'
    actual = json.get('message')
    assert expected == actual

    code, json = post_request('/api/v1/datediff', {
        'start': {
            'date': '12.20.2024 00:19:00',
        },
        'end': {
            'date': '12:19am 2024-12-20',
            'tz': 'Asia/Novosibirsk'
        },
    })
    assert code == 200
    expected = '7:00:00'
    actual = json.get('message')
    assert expected == actual

    """negative"""
    code, json = post_request('/api/v1/datediff', {
        'start': {
            'date': '12.20.2024 00:19:00',
        },
        'end': {
            'date': '12:19a 2024-12-20',
            'tz': 'Asia/Novosibirsk'
        },
    })
    assert code == 400

# Utility functions

MAX_DELAY = 2

def assert_datetimes(expected: datetime, actual: datetime):
    diff = abs(expected - actual)
    assert diff.total_seconds() <= MAX_DELAY

def get_datetime_from_json(json: Json, tz_name: str) -> datetime:
    dt = json.get('message')
    if not isinstance(dt, str):
        raise Exception(f'unexpected response: {str(dt)}')
    dt = datetime.strptime(dt, OUTPUT_DATETIME_FORMAT)
    return dt.replace(tzinfo=ZoneInfo(tz_name))

def get_datetime_from_html(html: str, tz_name: str) -> datetime:
    match = re.search(r'<div>(.*?)</div>', html, re.DOTALL)
    if match:
        dt = match.group(1).strip()
        dt = datetime.strptime(dt, OUTPUT_DATETIME_FORMAT)
        return dt.replace(tzinfo=ZoneInfo(tz_name))
    else:
        raise ValueError("No <div> element found in the HTML")

def render_request(path: str) -> tuple[int, str]:
    response = send_request(path, 'GET')
    return response.getcode(), response.read().decode('utf-8')

def get_request(path: str) -> tuple[int, Json]:
    response = send_request(path, 'GET')
    return response.getcode(), json.loads(response.read())

def post_request(path: str, body: Json | None = None) -> tuple[int, Json]:
    request_body: Json | str = '' if body is None else body
    response = send_request(path, 'POST', json.dumps(request_body))
    return response.getcode(), json.loads(response.read())

def send_request(path: str, method: str, body: str | None = None) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection(HOST, PORT)
    conn.request(method, path, body)
    return conn.getresponse()