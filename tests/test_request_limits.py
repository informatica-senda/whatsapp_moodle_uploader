"""Focused tests for the ASGI body-size guard, with synthetic requests only."""
import asyncio
import unittest

from api_service import RequestBodyLimitMiddleware


class RequestBodyLimitTests(unittest.TestCase):
    def run_asgi(self, headers=(), chunks=(), maximum=4):
        received = []
        messages = iter([{"type": "http.request", "body": part, "more_body": i < len(chunks) - 1}
                         for i, part in enumerate(chunks)])

        async def receive():
            return next(messages)

        async def app(scope, receive, send):
            body = await receive()
            received.append(body["body"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        sent = []

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "method": "POST", "path": "/test", "headers": list(headers)}
        asyncio.run(RequestBodyLimitMiddleware(app, maximum)(scope, receive, send))
        status = next(message["status"] for message in sent if message["type"] == "http.response.start")
        return status, received

    def test_accepts_body_at_limit(self):
        status, received = self.run_asgi(chunks=[b"ab", b"cd"])
        self.assertEqual(status, 200)
        self.assertEqual(received, [b"abcd"])

    def test_rejects_chunked_body_over_limit(self):
        status, received = self.run_asgi(chunks=[b"abc", b"de"])
        self.assertEqual(status, 413)
        self.assertEqual(received, [])

    def test_rejects_oversize_content_length_without_reading_body(self):
        status, received = self.run_asgi(headers=[(b"content-length", b"5")])
        self.assertEqual(status, 413)
        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
