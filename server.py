from abc import ABC, abstractmethod
import http
import http.client
import json
import re as regex
import threading
from types import NoneType, UnionType
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union, get_args, get_origin
from wsgiref.simple_server import make_server
from wsgiref.types import WSGIApplication
from datetime import datetime, timezone
import zoneinfo


Json = Dict[str, str|Dict|list]
RouteHandler = Callable[["Request"], "Response"]

class Request:
    def __init__(self, environ: Dict[str, Any]) -> None:
        self.__environ = environ

    def get_body(self) -> Json:
        content_length = self.__environ.get('CONTENT_LENGTH')
        content_length = int(content_length) if content_length else 0
        request_body = self.__environ['wsgi.input'].read(content_length) if content_length > 0 else b""
        request_body = request_body.decode('utf-8', errors='ignore')
        try:
            request_json = json.loads(request_body)
        except Exception as e:
            print('invalid request json')
            request_json = dict()

        request_json = dict() if request_json == '' else request_json
        return request_json

    def get_method(self) -> str:
        return self.__environ.get('REQUEST_METHOD') # type: ignore

    def get_path(self) -> str:
        return self.__environ.get('PATH_INFO') # type: ignore

    def get_path_param(self, param_key: str) -> str:
        param_value = self.__path_params.get(param_key)
        if param_value is None:
            raise ApplicationError('required path param not provided')
        return param_value

    def set_path_params(self, path_params: Dict[str, str] = dict()) -> None:
        self.__path_params = path_params
        

class Response:
    def __init__(
        self, 
        body: str = '', 
        code: int = 200, 
        content_type: str = 'application/json'
    ) -> None:
        self.__body = body
        self.__status = str(code) + ' ' + http.client.responses.get(code) # type: ignore
        self.__headers = [('Content-Type', content_type)]

    @staticmethod
    def json(body: str|Json, code: int = 200) -> "Response":
        return Response(
            json.dumps({'message': body}), 
            code,
            'application/json'
        )
    
    @staticmethod
    def error(message: str, code=400) -> "Response":
        return Response(
            json.dumps({'reason': message}),
            code,
            'application/json'
        )

    @staticmethod
    def html(body: str, code: int = 200) -> "Response":
        body = f"""
<html>
    <head><title>Time Server</title></head>
    <body>
        <div>{body}</div>
    </body>
</html>
"""
        return Response(
            body, 
            code,
            'text/html'
        )

    def send_response(self, resposne_writer: Callable) -> List[bytes]:
        resposne_writer(self.__status, self.__headers)
        return [self.__body.encode()]

class ApplicationError(Exception):
    def __init__(self, message='application error', code=400):
        super().__init__(message)
        self.__code = code
        self.__message = message
    
    def get_response(self) -> Response:
        return Response.error(self.__message, self.__code)

class Route:
    def __init__(self, method: str, path_regex: str, handler: RouteHandler) -> None:
        self.method = method
        self.path_regex = path_regex
        self.handler = handler

class Router:
    def __init__(self, routes: List[Route] = []) -> None:
        self.__routes = routes

    def handle_request(self, request: Request) -> Response:
        for route in self.__routes:
            if route.method != request.get_method():
                continue

            match = regex.match(route.path_regex, request.get_path())
            if match is None:
                continue

            try:
                request.set_path_params(match.groupdict())
            except AttributeError:
                request.set_path_params() 

            try:
                response = route.handler(request)
            except ApplicationError as e:
                response = e.get_response()
            except Exception as e:
                response = Response('server error', 500) 
                raise e
                
            return response
        return Response('not found', 404) 

class ApplicationModel(ABC):
    @abstractmethod
    def __init__(self):
        pass

T = TypeVar('T', bound='ApplicationModel')

def model_from_json(cls: Type[T], json: Json) -> T:
    model = cls.__new__(cls)
    for key, value in json.items():
        if not key in model.__annotations__:
            raise ApplicationError(f'unexpected param provided: {key}')
        if isinstance(value, str):
            setattr(model, key, value)
            continue
        if isinstance(value, Dict):
            attr_type = model.__annotations__[key]
            value = model_from_json(attr_type, value)
            setattr(model, key, value)
            continue
        if isinstance(value, list):
            raise ApplicationError(f'list in json is not supported: {key}')
        raise ApplicationError(f'unexpected type of json param: {key}')
    for key in cls.__annotations__:
        if hasattr(model, key) and getattr(model, key) is not None:
            continue
        attr_type = model.__annotations__[key]
        origin = get_origin(attr_type)
        args = get_args(attr_type)
        if origin is UnionType and NoneType in args:
            setattr(model, key, None)
            continue
        raise ApplicationError(f'missing required param: {key}')
    return model

class TimezoneModel(ApplicationModel):
    tz: str | None

    def __init__(self, tz: str | None):
        self.tz = tz

    def get_parsed_tz(self) -> zoneinfo.ZoneInfo:
        if self.tz is None:
            return zoneinfo.ZoneInfo('UTC')
        try:
            tz = zoneinfo.ZoneInfo(self.tz)
        except Exception as e:
            raise ApplicationError('invalid timezone')
        return tz

    def get_str_datetime(self) -> str:
        dt = self.get_datetime()
        return dt.strftime(OUTPUT_DATETIME_FORMAT)

    def get_datetime(self) -> datetime:
        try:
            tz = self.get_parsed_tz()
            dt = datetime.now(tz)
        except Exception as e:
            raise ApplicationError('invalid timezone')
        return dt

class DateModel(ApplicationModel):
    date: str
    tz: str | None

    def __init__(self, date: str, tz: str):
        self.date = date
        self.tz = tz
    
    def get_parsed_date(self) -> datetime:
        supported_datime_formats = [
            "%I:%M%p %Y-%m-%d",
            "%m.%d.%Y %H:%M:%S"
        ]
        dt: datetime | None = None
        for supported_format in supported_datime_formats:
            try:
                dt = datetime.strptime(self.date, supported_format)
                break
            except Exception:
                dt = None

        if dt is None:
            raise ApplicationError(f'invalid datetime format: {self.date}')
        
        timezone = TimezoneModel(self.tz).get_parsed_tz()
        return dt.replace(tzinfo=timezone)
    
    def get_date_in_utc(self) -> datetime:
        return self.get_parsed_date().astimezone(timezone.utc)


class DatesDiffModel(ApplicationModel):
    start: DateModel
    end: DateModel
    def __init__(self, start: DateModel, end: DateModel):
        self.start = start
        self.end = end
    
    def get_diff(self) -> datetime:
        return self.start.get_date_in_utc() - self.end.get_date_in_utc() # type: ignore

def render_timezone_time(request: Request) -> Response:
    timezone = request.get_path_param('timezone')
    timezone = TimezoneModel(timezone)
    datetime = timezone.get_str_datetime()
    return Response.html(datetime)

def render_continent_city_time(request: Request) -> Response:
    continent = request.get_path_param('continent')
    city = request.get_path_param('city')
    timezone = TimezoneModel(f'{continent}/{city}')
    datetime = timezone.get_str_datetime()
    return Response.html(datetime)

def render_continent_country_city_time(request: Request) -> Response:
    continent = request.get_path_param('continent')
    country = request.get_path_param('country')
    city = request.get_path_param('city')
    timezone = TimezoneModel(f'{continent}/{country}/{city}')
    datetime = timezone.get_str_datetime()
    return Response.html(datetime)

def render_server_time(_: Request) -> Response:
    dt = datetime.now(timezone.utc).strftime(OUTPUT_DATETIME_FORMAT)
    return Response.html(dt)

def get_timezone_time(request: Request) -> Response:
    timezone = model_from_json(TimezoneModel, request.get_body())
    datetime = timezone.get_str_datetime()
    return Response.json(datetime)

def get_timezone_date(request: Request) -> Response:
    timezone = model_from_json(TimezoneModel, request.get_body())
    date = timezone.get_datetime().date()
    return Response.json(str(date))

def get_dates_diff(request: Request) -> Response:
    dates_diff = model_from_json(DatesDiffModel, request.get_body())
    dates_diff = dates_diff.get_diff()
    return Response.json(str(dates_diff))

def create_application() -> WSGIApplication: 
    router = Router([
        Route('GET', r'^/$', render_server_time),
        Route(
            'GET', 
            r'^/(?P<continent>[a-zA-Z_]+)/(?P<country>[a-zA-Z_]+)/(?P<city>[a-zA-Z_]+)$', 
            render_continent_country_city_time
        ),
        Route(
            'GET',
            r'^/(?P<continent>[a-zA-Z_]+)/(?P<city>[a-zA-Z_]+)$',
            render_continent_city_time
        ),
        Route(
            'GET',
            r'^/(?P<timezone>[a-zA-Z_]{3,})$',
            render_timezone_time
        ),
        Route(
            'POST',
            r'^/api/v1/time$',
            get_timezone_time
        ),
        Route(
            'POST',
            r'^/api/v1/date$',
            get_timezone_date
        ),
        Route(
            'POST',
            r'^/api/v1/datediff$',
            get_dates_diff
        )
    ])

    def handle_request(environ: Dict[str, Any], response_writer: Callable) -> List[bytes]:
        request = Request(environ)
        response = router.handle_request(request)
        return response.send_response(response_writer)
    return handle_request

HOST = '127.0.0.1'
PORT = 8181
OUTPUT_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'

def run_application() -> Callable[[], None]:
    server = make_server(HOST, PORT, create_application())
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()
    print(f"server is running on {HOST}:{PORT}")

    def stop_server():
        server.shutdown()
        server_thread.join()
        print('server shutdown')

    return stop_server

if __name__ == "__main__":
    run_application()