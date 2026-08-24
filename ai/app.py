import streamlit as st

from text_to_sql import run_text_to_sql
from rag_chat import run_rag


st.set_page_config(
    page_title="Food Data Engineering Platform",
    page_icon="🍽️",
    layout="wide",
)


# ---------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------

with st.sidebar:

    st.title("AI Tools")

    mode = st.radio(
        "Choose an analysis mode",
        [
            "💬 Data Analyst",
            "🧠 Review Analyst",
        ],
    )


# ---------------------------------------------------------
# SELECT APP
# ---------------------------------------------------------

if mode == "💬 Data Analyst":

    run_text_to_sql()

else:

    run_rag()