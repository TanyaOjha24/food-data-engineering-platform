import os
import re

import pandas as pd
import snowflake.connector
import streamlit as st
import cohere
from dotenv import load_dotenv


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

load_dotenv()

CHAT_MODEL = os.getenv("CHAT_MODEL", "command-a-03-2025")

client = cohere.ClientV2(
    api_key=os.getenv("COHERE_API_KEY")
)


# ---------------------------------------------------------
# DATABASE SCHEMA
# ---------------------------------------------------------

SCHEMA = """
You are querying the ZOMATO.MARTS schema in Snowflake.

Use ONLY the following tables and columns.

DIM_CUSTOMER:
- CUSTOMER_ID NUMBER
- CUSTOMER_NAME TEXT
- EMAIL TEXT
- AGE NUMBER
- AGE_SEGMENT TEXT
- GENDER TEXT
- MARITAL_STATUS TEXT
- OCCUPATION TEXT
- INCOME_BAND TEXT
- EDUCATION TEXT
- FAMILY_SIZE NUMBER

DIM_DATE:
- DATE_DAY DATE
- YEAR NUMBER
- MONTH NUMBER
- MONTH_NAME TEXT
- DAY_NAME TEXT
- IS_WEEKEND BOOLEAN

DIM_FOOD:
- F_ID TEXT
- FOOD_NAME TEXT
- VEG_OR_NON_VEG TEXT

DIM_RESTAURANTS:
- RESTAURANT_ID NUMBER
- RESTAURANT_NAME TEXT
- CITY TEXT
- CUISINE TEXT
- RATING NUMBER
- RATING_COUNT NUMBER
- COST_FOR_TWO NUMBER

FACT_ORDER_ITEMS:
- ORDER_ITEM_ID NUMBER
- ORDER_ID NUMBER
- RESTAURANT_ID NUMBER
- F_ID TEXT
- ORDER_TS TIMESTAMP_NTZ
- ORDER_DATE DATE
- CITY TEXT
- PRICE NUMBER
- QUANTITY NUMBER
- LINE_AMOUNT NUMBER

FCT_ORDERS:
- ORDER_ID NUMBER
- ORDER_TIMESTAMP TIMESTAMP_NTZ
- ORDER_DATE DATE
- CUSTOMER_ID NUMBER
- RESTAURANT_ID NUMBER
- CITY TEXT
- CUISINE TEXT
- PAYMENT_METHOD TEXT
- ORDER_STATUS TEXT
- IS_DELIVERED BOOLEAN
- ITEMS_COUNT NUMBER
- SALES_QTY NUMBER
- SUBTOTAL NUMBER
- DISCOUNT NUMBER
- DELIVERY_FEE NUMBER
- GST NUMBER
- SALES_AMOUNT NUMBER
- CUSTOMER_RATING NUMBER
- DELIVERY_TIME_MIN NUMBER

MART_DAILY_CITY_REVENUNE:
- ORDER_DATE DATE
- CITY TEXT
- ORDERS NUMBER
- DELIVERED_ORDERS NUMBER
- CANCEL_RATE NUMBER
- GMV NUMBER
- AOV NUMBER

MART_DELIVERY_SLA:
- CITY TEXT
- ORDER_HOUR NUMBER
- DELIVERED_ORDERS NUMBER
- P50 NUMBER
- P90 NUMBER

MART_RESTAURANT_PERFORMANCE:
- RESTAURANT_ID NUMBER
- RESTAURANT_NAME TEXT
- CITY TEXT
- CUISINE TEXT
- ORDERS NUMBER
- REVENUE NUMBER
- AVG_CUSTOMER_RATING NUMBER
- AVG_DELIVERY_MIN NUMBER


IMPORTANT BUSINESS DEFINITIONS:

- GMV means delivered revenue.
- CANCEL_RATE is the cancellation rate.
- AOV means average order value.
- P50 is the 50th percentile delivery time.
- P90 is the 90th percentile delivery time.
- Prefer MART tables when they directly answer the question.
- Use FCT_ORDERS when detailed order-level analysis is required.
- Use FACT_ORDER_ITEMS for food/item-level analysis.
- Use DIM_RESTAURANTS for restaurant attributes.
- Use DIM_CUSTOMER for customer demographics.
- Use DIM_DATE for date-related analysis.

IMPORTANT TABLE NAME:
The table is actually named MART_DAILY_CITY_REVENUNE.
The spelling "REVENUNE" is intentional. Use that exact table name.
"""


# ---------------------------------------------------------
# PROMPT
# ---------------------------------------------------------

SYSTEM_PROMPT = f"""
You are a Snowflake SQL expert.

Your job is to translate a user's natural-language analytics
question into ONE safe Snowflake SQL query.

DATABASE SCHEMA
---------------
{SCHEMA}

RULES
-----

1. Generate ONE query only.

2. SELECT statements and WITH ... SELECT statements only.

3. Never generate:
   - INSERT
   - UPDATE
   - DELETE
   - DROP
   - ALTER
   - CREATE
   - TRUNCATE
   - MERGE
   - GRANT
   - REVOKE
   - COPY
   - CALL

4. Use ONLY the tables and columns listed in the schema.

5. Use bare table names.

   Correct:
   FCT_ORDERS

   Incorrect:
   ZOMATO.MARTS.FCT_ORDERS

6. Prefer MART tables when they already contain the required metric.

7. Use appropriate aggregation:
   - SUM for totals
   - AVG for averages
   - COUNT for counts
   - GROUP BY for category comparisons

8. If the question asks for "top", "highest", "lowest",
   "best", or "worst", sort appropriately.

9. Add LIMIT 100 for result sets that could return many rows.

10. If the question asks for a single aggregate such as:
    "What is total GMV?"
    do not add LIMIT.

11. Do not invent tables, columns, metrics, or business definitions.

12. Return ONLY valid JSON in this format:

{{
    "sql": "SELECT ..."
}}

Do not include markdown.
Do not include explanations.

13. For rates and percentages, always ensure decimal division.
    Do not divide two integer expressions directly.

    Use:
    COUNT_IF(condition) / NULLIF(COUNT(*), 0)

    or multiply the numerator by 1.0 before division.

14. For ORDER_STATUS comparisons, treat status values case-insensitively.
    Use UPPER(ORDER_STATUS) when comparing statuses such as
    'DELIVERED', 'CANCELLED', and 'REFUNDED'.
    - Cancellation rate = cancelled orders / total orders.
"""


# ---------------------------------------------------------
# EXAMPLE QUESTIONS
# ---------------------------------------------------------

EXAMPLE_QUESTIONS = [
    "What are the top 10 cities by GMV?",
    "Which cuisine has the most orders?",
    "What is the average delivery time by city?",
    "Which payment method has the highest cancellation rate?",
    "What are the top 10 restaurants by revenue?",
    "What is the average order value by city?",
    "Which food items are ordered the most?",
    "What is the total GMV?",
]


# ---------------------------------------------------------
# SNOWFLAKE CONNECTION
# ---------------------------------------------------------

@st.cache_resource
def get_connection():

    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema="MARTS",
        role=os.getenv("SNOWFLAKE_ROLE", "DBT_ROLE"),
    )


# ---------------------------------------------------------
# SQL GENERATION
# ---------------------------------------------------------

def generate_sql(question):

    response = client.chat(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": question,
            },
        ],
        temperature=0,
        response_format={
            "type": "json_object"
        },
    )

    answer = response.message.content[0].text

    import json

    result = json.loads(answer)

    sql = result["sql"]

    # Remove accidental fully qualified names
    sql = sql.replace("ZOMATO.MARTS.", "")
    sql = sql.replace("ZOMATO.", "")

    return sql.strip().rstrip(";")


# ---------------------------------------------------------
# SQL SAFETY
# ---------------------------------------------------------

FORBIDDEN_SQL = [
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "REPLACE",
    "MERGE",
    "GRANT",
    "REVOKE",
    "COPY",
    "CALL",
]


ALLOWED_TABLES = {
    "DIM_CUSTOMER",
    "DIM_DATE",
    "DIM_FOOD",
    "DIM_RESTAURANTS",
    "FACT_ORDER_ITEMS",
    "FCT_ORDERS",
    "MART_DAILY_CITY_REVENUNE",
    "MART_DELIVERY_SLA",
    "MART_RESTAURANT_PERFORMANCE",
}


def remove_sql_comments(sql):

    # Remove -- comments
    sql = re.sub(
        r"--.*?$",
        "",
        sql,
        flags=re.MULTILINE,
    )

    # Remove /* ... */ comments
    sql = re.sub(
        r"/\*.*?\*/",
        "",
        sql,
        flags=re.DOTALL,
    )

    return sql.strip()


def is_safe(sql):

    sql = remove_sql_comments(sql)

    normalized = sql.strip().upper()

    # Must start with SELECT or WITH
    if not (
        normalized.startswith("SELECT")
        or normalized.startswith("WITH")
    ):
        return False, "Only SELECT queries are allowed."


    # Reject forbidden SQL keywords
    for word in FORBIDDEN_SQL:

        pattern = rf"\b{word}\b"

        if re.search(pattern, normalized):
            return False, f"Forbidden SQL operation detected: {word}"


    # Reject multiple statements
    if ";" in sql:
        return False, "Multiple SQL statements are not allowed."


    # Extract table names after FROM and JOIN
    table_matches = re.findall(
        r"\b(?:FROM|JOIN)\s+([A-Z0-9_]+)",
        normalized,
    )

    for table in table_matches:

        if table not in ALLOWED_TABLES:
            return False, f"Table is not allowed: {table}"


    return True, None


# ---------------------------------------------------------
# RUN QUERY
# ---------------------------------------------------------

def run_query(sql):

    conn = get_connection()

    cursor = conn.cursor()

    try:

        df = cursor.execute(sql).fetch_pandas_all()

        return df

    finally:

        cursor.close()


# ---------------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------------

def run_text_to_sql():

    st.title("Chat with your Zomato Data")

    st.caption(
        f"Ask in English → {CHAT_MODEL} generates SQL → Snowflake executes it"
    )

    # ---------------------------------------------------------
    # SIDEBAR
    # ---------------------------------------------------------

    with st.sidebar:

        st.header("Example Questions")

        for question in EXAMPLE_QUESTIONS:

            st.markdown(
                f"- {question}"
            )

    # ---------------------------------------------------------
    # QUESTION
    # ---------------------------------------------------------

    question = st.text_input(
        "Ask a question about your Zomato data:",
        placeholder="e.g. What are the top 10 restaurants by revenue?",
    )

    # ---------------------------------------------------------
    # PROCESS QUESTION
    # ---------------------------------------------------------

    if question:

        try:

            # Generate SQL
            sql = generate_sql(question)

            st.subheader("Generated SQL")

            st.code(
                sql,
                language="sql",
            )

            # Validate SQL
            safe, error_message = is_safe(sql)

            if not safe:

                st.error(
                    f"Query blocked: {error_message}"
                )

            else:

                # Execute
                df = run_query(sql)

                st.success(
                    f"{len(df)} rows returned"
                )

                # Results
                st.subheader("Results")

                st.dataframe(
                    df,
                    hide_index=True,
                    use_container_width=True,
                )

                # Simple chart
                if (
                    len(df.columns) == 2
                    and len(df) > 0
                    and pd.api.types.is_numeric_dtype(
                        df.iloc[:, 1]
                    )
                ):

                    st.subheader("Visualization")

                    st.bar_chart(
                        df,
                        x=df.columns[0],
                        y=df.columns[1],
                    )

        except Exception as e:

            st.error(
                f"Error: {e}"
            )