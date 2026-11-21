import ipaddress
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import OpenerDirector, ProxyHandler, build_opener, Request

class AgentError(RuntimeError):
    pass

class AgentClient:
    def __init__(self, host):
        host = host.strip()
        try:
            address = ipaddress.ip_address(host)
        except ValueError as error:
            raise AgentError("Введите IPv4 или IPv6 адрес Orange Pi.") from error
        endpoint = f"[{address}]" if address.version == 6 else str(address)
        self.base = f"http://{endpoint}:8765"
        self.opener: OpenerDirector = build_opener(ProxyHandler({}))
        self.rtt_ms = None

    def request(self, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        query = Request(self.base+path, data=body, headers={"Content-Type":"application/json"})
        start = time.perf_counter_ns()
        try:
            with self.opener.open(query, timeout=5) as response:
                raw = response.read(20*1024*1024+1)
                if len(raw) > 20*1024*1024:
                    raise AgentError("Превышен размер ответа агента.")
                self.rtt_ms = round((time.perf_counter_ns()-start)/1e6, 2)
                return json.loads(raw)
        except HTTPError as error:
            try:
                message = json.loads(error.read(10000))["error"]
            except (ValueError, KeyError, OSError):
                message = str(error)
            raise AgentError(message) from error
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise AgentError(f"Связь с агентом недоступна: {error}") from error
