"""The Streamlit page: one agent run per question, with earlier turns kept on screen."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import study_chat
from study_chat import reply
from study_chat.reply import Reply

APP = Path(study_chat.__file__).parent / "app.py"


class ScriptedResponder:
    """Stands in for ``reply.respond``: records each question and answers from a script."""

    def __init__(self, replies: list[Reply]) -> None:
        """Answer the questions asked, in order, with ``replies``."""
        self.replies = list(replies)
        self.questions: list[str] = []

    def __call__(self, question: str) -> Reply:
        """Record ``question`` and return the next scripted reply."""
        self.questions.append(question)
        return self.replies.pop(0)


def start_app(
    monkeypatch: pytest.MonkeyPatch, replies: list[Reply]
) -> tuple[AppTest, ScriptedResponder]:
    """Run the page once with ``respond`` replaced by a scripted responder."""
    responder = ScriptedResponder(replies)
    monkeypatch.setattr(reply, "respond", responder)
    app = AppTest.from_file(str(APP))
    app.run()
    return app, responder


def ask(app: AppTest, question: str) -> None:
    """Type ``question`` into the chat box and send it."""
    app.chat_input[0].set_value(question).run()


def test_the_page_opens_with_no_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Before any question the page shows its title and an empty conversation."""
    app, responder = start_app(monkeypatch, [])

    assert not app.exception
    assert app.title[0].value == "Study assistant"
    assert len(app.chat_message) == 0
    assert responder.questions == []


def test_a_question_shows_the_question_and_the_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sending a question shows it as the user's message and the reply as the assistant's."""
    app, responder = start_app(monkeypatch, [Reply(text="Hash maps hash keys [1].", failed=False)])

    ask(app, "what is a hash map")

    assert not app.exception
    assert responder.questions == ["what is a hash map"]
    assert [message.name for message in app.chat_message] == ["user", "assistant"]
    assert app.chat_message[0].markdown[0].value == "what is a hash map"
    assert app.chat_message[1].markdown[0].value == "Hash maps hash keys [1]."


def test_earlier_turns_stay_without_being_asked_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second question adds a turn, and the first question is not sent to the agent again."""
    app, responder = start_app(
        monkeypatch,
        [Reply(text="First answer.", failed=False), Reply(text="Second answer.", failed=False)],
    )

    ask(app, "first question")
    ask(app, "second question")

    assert responder.questions == ["first question", "second question"]
    shown = [message.markdown[0].value for message in app.chat_message]
    assert shown == ["first question", "First answer.", "second question", "Second answer."]


def test_a_failed_reply_is_shown_as_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed run shows its message as an error in the assistant's turn, not as an answer."""
    app, _ = start_app(monkeypatch, [Reply(text="the model endpoint refused", failed=True)])

    ask(app, "anything")

    assistant = app.chat_message[1]
    assert assistant.name == "assistant"
    assert assistant.error[0].value == "the model endpoint refused"
    assert len(assistant.markdown) == 0
