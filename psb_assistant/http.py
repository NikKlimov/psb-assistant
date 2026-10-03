from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests

from psb_assistant.cache import Cache
from psb_assistant.models import bank_url

logger = logging.getLogger(__name__)
USER_AGENT = "PSBInterviewAssistant/0.1"
ROBOTS = "https://www.psbank.ru/robots.txt"


class CrawlError(RuntimeError):
    pass


class PoliteHTTP:
    """One request at a time, allowlisted redirects, robots fail closed."""

    def __init__(self, cache: Cache, delay: float = 2.0) -> None:
        self.cache = cache
        self.delay = max(1.0, delay)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept"] = "text/html,text/plain;q=0.9"
        self.lock = threading.Lock()
        self.last_request = 0.0
        self.robots: RobotFileParser | None = None

    def _request(self, url: str) -> requests.Response:
        bank_url(url)
        for attempt in range(3):
            with self.lock:
                time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
                try:
                    response = self.session.get(url, timeout=(8, 25), allow_redirects=False, stream=True)
                except requests.RequestException:
                    if attempt == 2:
                        raise
                    logger.warning("http_retry url=%s attempt=%s reason=transport", url, attempt + 1)
                    response = None
                finally:
                    self.last_request = time.monotonic()
            if response is not None:
                if response.status_code not in (429, 500, 502, 503, 504):
                    return response
                logger.warning(
                    "http_retry url=%s attempt=%s status=%s", url, attempt + 1, response.status_code
                )
                if attempt == 2:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After", "0")
                response.close()
                # Do not hammer a server asking for a long pause.
                if retry_after.isdigit() and int(retry_after) > 30:
                    raise CrawlError("Server requested a long Retry-After; refresh postponed")
                time.sleep(max(2**attempt, int(retry_after) if retry_after.isdigit() else 0))
            else:
                time.sleep(2**attempt)
        raise CrawlError("HTTP retries exhausted")

    @staticmethod
    def _body(response: requests.Response) -> str:
        with response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 5_000_000:
                    raise CrawlError("Page exceeds 5 MB")
                chunks.append(chunk)
            body = b"".join(chunks)
            # The public site is UTF-8; requests defaults text/* without charset to Latin-1.
            return body.decode(
                response.encoding if response.encoding and response.encoding != "ISO-8859-1" else "utf-8",
                errors="replace",
            )

    def load_robots(self, force: bool = False) -> None:
        cached = None if force else self.cache.get(ROBOTS)
        if cached:
            body = cached[0]
        else:
            response = self._request(ROBOTS)
            # 404 explicitly permits crawling; inaccessible or forbidden robots does not.
            if response.status_code == 404:
                body = "User-agent: *\nAllow: /"
                response.close()
            else:
                body = self._body(response)
                if "<html" in body.lower() or "user-agent:" not in body.lower():
                    raise CrawlError("robots.txt is not a valid robots document")
            self.cache.put(ROBOTS, body)
        parser = RobotFileParser(ROBOTS)
        parser.parse(body.splitlines())
        self.robots = parser
        self.delay = max(self.delay, float(parser.crawl_delay(USER_AGENT) or 0))
        rate = parser.request_rate(USER_AGENT)
        if rate and rate.requests:
            self.delay = max(self.delay, rate.seconds / rate.requests)
        logger.info("robots_loaded delay=%s", self.delay)

    def fetch(self, url: str) -> str:
        bank_url(url)
        if self.robots is None:
            self.load_robots()
        for _ in range(5):
            if self.robots is None or not self.robots.can_fetch(USER_AGENT, url):
                raise CrawlError(f"robots.txt disallows {url}")
            response = self._request(url)
            if response.status_code in (301, 302, 303, 307, 308):
                target = urljoin(url, response.headers.get("Location", ""))
                response.close()
                bank_url(target)
                if target == url:
                    raise CrawlError("Redirect without a destination")
                url = target
                continue
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                response.close()
                raise CrawlError("Only public HTML pages can be ingested")
            return self._body(response)
        raise CrawlError("Too many redirects")
