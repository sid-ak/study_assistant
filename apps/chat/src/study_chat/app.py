"""The chat page Streamlit runs: one agent run per question, with earlier turns kept on screen.

Streamlit runs this whole file again on every interaction. Earlier turns live in session state,
which survives those reruns, so they are redrawn from there and never sent to the agent again.
"""

import streamlit as st

from study_chat import reply
from study_chat.reply import Reply

# The session-state key holding every (question, reply) turn so far, oldest first.
TURNS = "turns"


def show_question(question: str) -> None:
    """Draw ``question`` as the user's message."""
    with st.chat_message("user"):
        st.markdown(question)


def show_reply(answer: Reply) -> None:
    """Draw ``answer`` as Markdown, or as an error when the run failed."""
    if answer.failed:
        st.error(answer.text)
    else:
        st.markdown(answer.text)


st.set_page_config(page_title="Study assistant")
st.title("Study assistant")

if TURNS not in st.session_state:
    st.session_state[TURNS] = []
turns: list[tuple[str, Reply]] = st.session_state[TURNS]

for earlier_question, earlier_reply in turns:
    show_question(earlier_question)
    with st.chat_message("assistant"):
        show_reply(earlier_reply)

question = st.chat_input("Ask about your course materials")
if question:
    show_question(question)
    with st.chat_message("assistant"):
        with st.spinner("Searching and answering..."):
            # Looked up on the module at call time, so tests can replace it.
            answer = reply.respond(question)
        show_reply(answer)
    turns.append((question, answer))
