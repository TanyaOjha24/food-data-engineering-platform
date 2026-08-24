import os

import numpy as np
import pandas as pd
import streamlit as st
import snowflake.connector
import cohere
from dotenv import load_dotenv


load_dotenv()

EMBEDDING_MODEL = os.getenv(
    "COHERE_EMBEDDING_MODEL",
    "embed-english-v3.0"
)

CHAT_MODEL = os.getenv(
    "COHERE_CHAT_MODEL",
    "command-a-03-2025"
)

NEW_REVIEWS = int(os.getenv("NEW_REVIEWS", "500"))
TOP_K = int(os.getenv("TOP_K", "5"))

'''CACHE_FILE = "review_embeddings.parquet"'''
from pathlib import Path

CACHE_FILE = Path(__file__).resolve().parent / "review_embeddings.parquet"



client = cohere.ClientV2(
    api_key=os.getenv("COHERE_API_KEY")
)


# Snowflake
def read_reviews_from_snowflake():
    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )

    query = f"""
        SELECT
            REVIEW_ID,
            CITY,
            RATING,
            COMMENT
        FROM ZOMATO.STAGING.STG_REVIEWS
        SAMPLE ({NEW_REVIEWS} ROWS)
    """

    cursor = conn.cursor()

    try:
        df = cursor.execute(query).fetch_pandas_all()
    finally:
        cursor.close()
        conn.close()

    df.columns = [col.lower() for col in df.columns]

    return df


# Embeddings

def embed(texts, input_type="search_document"):
    all_embeddings = []

    batch_size = 96

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]

        response = client.embed(
            model="embed-v4.0",
            input_type=input_type,
            texts=batch,
            embedding_types=["float"],
        )

        all_embeddings.extend(response.embeddings.float)

    return all_embeddings


# Load Reviews + Create Embeddings

@st.cache_data
def load_reviews():

    if os.path.exists(CACHE_FILE):
        return pd.read_parquet(CACHE_FILE)

    print("Loading reviews from Snowflake...")

    df = read_reviews_from_snowflake()

    print(f"Loaded {len(df)} reviews.")

    print("Creating embeddings...")

    df["embedding"] = embed(
        df["comment"].tolist(),
        input_type="search_document"
    )

    df.to_parquet(CACHE_FILE)

    print("Embeddings cached.")

    return df


# Cosine Similarity

def cosine_similarity(vec_a, vec_b):

    return np.dot(vec_a, vec_b) / (
        np.linalg.norm(vec_a) *
        np.linalg.norm(vec_b)
    )


# Find Similar Reviews

def find_similar_reviews(question, df):

    question_vector = embed(
        [question],
        input_type="search_query"
    )[0]

    scores = []

    for review_vector in df["embedding"]:
        scores.append(
            cosine_similarity(
                question_vector,
                review_vector
            )
        )

    results = df.copy()

    results["score"] = scores

    return results.nlargest(TOP_K, "score")


# Ask LLM

def ask_llm(question, top_reviews):

    context = ""

    for _, row in top_reviews.iterrows():

        context += (
            f"City: {row['city']}\n"
            f"Rating: {row['rating']} stars\n"
            f"Review: {row['comment']}\n\n"
        )

    system_prompt = """
You answer questions about customer reviews for a food delivery application.

Use ONLY the customer reviews provided in the context.

Do not invent information.

If the provided reviews do not contain enough information
to answer the question, say that the available reviews
do not provide enough information.

Be concise and directly answer the question.
"""

    user_prompt = f"""
Question:
{question}

Customer Reviews:
{context}
"""

    response = client.chat(
        model=CHAT_MODEL,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    )

    return response.message.content[0].text


# ---------------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------------

def run_rag():

    st.title("Chat with your Zomato Reviews")

    st.caption(
        f"Searching {NEW_REVIEWS} reviews "
        f"using {EMBEDDING_MODEL} embeddings "
        f"and answering with {CHAT_MODEL}"
    )

    # ---------------------------------------------------------
    # LOAD DATA
    # ---------------------------------------------------------

    review_df = load_reviews()

    # ---------------------------------------------------------
    # QUESTION
    # ---------------------------------------------------------

    question = st.text_input(
        "Ask a question about your reviews:",
        placeholder=(
            "e.g. What are the most common complaints "
            "about delivery?"
        ),
    )

    # ---------------------------------------------------------
    # RAG PIPELINE
    # ---------------------------------------------------------

    if question:

        top_reviews = find_similar_reviews(
            question,
            review_df,
        )

        answer = ask_llm(
            question,
            top_reviews,
        )

        st.markdown("**Answer:**")

        st.write(answer)

        with st.expander(
            "Reviews used to build this answer"
        ):

            st.dataframe(
                top_reviews[
                    [
                        "city",
                        "rating",
                        "comment",
                        "score",
                    ]
                ],
                hide_index=True,
                use_container_width=True,
            )