"""A stand-in for the OpenAI client, shared by the counsellor tests that need
to script the provider: each create() call takes the next canned item and
either returns it as a response or, if it is an exception, raises it. Every
call's messages are kept in .calls so a test can inspect the real prompt.
"""

from types import SimpleNamespace


class FakeClient:
    def __init__(self, items):
        self.calls = []
        queue = list(items)

        def create(model, messages, temperature=0.2):
            self.calls.append(messages)
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=item))])

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
