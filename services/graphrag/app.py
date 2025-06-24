import streamlit as st
import pandas as pd
from sqlalchemy import text, exc as sqlalchemy_exc
from langchain_community.utilities import SQLDatabase
from langchain_google_vertexai import ChatVertexAI
import re
import traceback
import json

# --- Hardcoded Spanner Connection Details ---
SPANNER_PROJECT_ID = "pj-joshua-foundations-test"
SPANNER_INSTANCE_ID = "graphfree"
SPANNER_DATABASE_ID = "look"

# --- SQL Keywords for Validation ---
SQL_KEYWORDS = [
    "SELECT",
    "FROM",
    "WHERE",
    "JOIN",
    "GROUP BY",
    "ORDER BY",
    "LIMIT",
    "INSERT INTO",
    "UPDATE",
    "DELETE FROM",
    "WITH",
    "CREATE TABLE",
    "ALTER TABLE",
    "DROP TABLE",
    "VALUES",
]


# --- Utility to strip markdown code blocks ---
def strip_markdown_code_blocks(text_content: str) -> str:
    if not isinstance(text_content, str):
        return text_content
    pattern = r"```(?:[a-zA-Z]+\n)?(.*?)```"
    stripped_text = re.sub(pattern, r"\1", text_content, flags=re.DOTALL)
    return stripped_text.strip()


# --- Helper Function to Get Specific Recommendations (Data Fetching) ---
def get_spanner_recommendations_data(
    user_id: int,
    db: SQLDatabase,
    num_recommendations: int = 9,
    filters: dict = None,
    budget: float = None,
) -> pd.DataFrame | str:
    if not db or not db._engine:
        return "Error: Database connection not established or engine not available for recommendations."

    if not isinstance(num_recommendations, int) or num_recommendations <= 0:
        num_recommendations = 9

    sql_limit = num_recommendations

    base_query = f"""
    WITH TargetUserPurchasedProducts AS (
        SELECT DISTINCT oi.product_id
        FROM order_items oi
        WHERE oi.user_id = {user_id}
    ),
    UsersWhoAlsoPurchasedTheseProducts AS (
        SELECT DISTINCT oi.user_id AS similar_user_id
        FROM order_items oi
        WHERE
            oi.user_id != {user_id}
            AND oi.product_id IN (SELECT product_id FROM TargetUserPurchasedProducts)
    ),
    PotentialRecommendations AS (
        SELECT
            uwp.similar_user_id,
            oi.product_id AS recommended_product_id
        FROM UsersWhoAlsoPurchasedTheseProducts uwp
        JOIN order_items oi ON uwp.similar_user_id = oi.user_id
        WHERE
            oi.product_id NOT IN (SELECT product_id FROM TargetUserPurchasedProducts)
    )
    SELECT
        pr.recommended_product_id,
        p.name AS recommended_product_name,
        p.category AS recommended_product_category,
        p.brand AS recommended_product_brand,
        p.retail_price AS recommended_product_price,
        COUNT(DISTINCT pr.similar_user_id) AS recommendation_strength
    FROM PotentialRecommendations pr
    JOIN products p ON pr.recommended_product_id = p.product_id
    """
    where_clauses = []
    if filters:
        excluded_categories = filters.get("excluded_categories")
        if (
            excluded_categories
            and isinstance(excluded_categories, list)
            and len(excluded_categories) > 0
        ):
            cleaned_formatted_categories = []
            for cat in excluded_categories:
                if isinstance(cat, str):
                    cleaned_cat = cat.strip().lower().replace("'", "''")
                    cleaned_formatted_categories.append(f"'{cleaned_cat}'")
            if cleaned_formatted_categories:
                where_clauses.append(
                    f"LOWER(p.category) NOT IN ({', '.join(cleaned_formatted_categories)})"
                )

    if budget is not None and isinstance(budget, (int, float)) and budget > 0:
        where_clauses.append(f"p.retail_price <= {budget}")

    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)

    base_query += f"""
    GROUP BY
        pr.recommended_product_id,
        p.name,
        p.category,
        p.brand,
        p.retail_price
    ORDER BY
        recommendation_strength DESC,
        p.name ASC
    LIMIT {sql_limit}; 
    """
    final_query = base_query
    try:
        with db._engine.connect() as connection:
            result_proxy = connection.execute(text(final_query))
            rows = result_proxy.fetchall()
            if not rows:
                filter_message = (
                    " with the current filters"
                    if filters and any(filters.values())
                    else ""
                )
                budget_message = (
                    f" within your budget of ${budget:.2f}"
                    if budget is not None
                    else ""
                )
                return f"No recommendations found for User ID {user_id}{filter_message}{budget_message} or the user has not purchased any products."
            df = pd.DataFrame(rows, columns=result_proxy.keys())
            return df
    except Exception as e:
        return f"Error executing recommendation query: {e}\nQuery attempted:\n{final_query}"


# --- Function to Format Recommendations as Conversational Text ---
def format_recommendations_as_text(
    recommendations_df: pd.DataFrame,
    user_id: int,
    num_asked_for: int,
    budget: float | None,
    filters: dict | None,
    llm: ChatVertexAI,
    current_user_prompt: str,
) -> str:
    if recommendations_df.empty:
        filter_message = (
            " with the current filters" if filters and any(filters.values()) else ""
        )
        budget_message = (
            f" within your budget of ${budget:.2f}" if budget is not None else ""
        )
        return f"I couldn't find any recommendations for User ID {user_id}{filter_message}{budget_message} right now."

    num_to_mention = min(len(recommendations_df), 1)
    if num_to_mention == 0:
        return "I found some recommendations, but couldn't pick one to highlight for a conversation."

    top_rec_to_mention = recommendations_df.head(num_to_mention).iloc[0]

    rec_details_str = f"'{top_rec_to_mention['recommended_product_name']}' (Category: {top_rec_to_mention['recommended_product_category']}, Price: ${top_rec_to_mention['recommended_product_price']:.2f})"

    prompt_for_llm = (
        f"You are a helpful and adaptive shopping assistant. "
        f"The user (User ID {user_id}) just made the following request/statement: '{current_user_prompt}'.\n"
        "Based on their likely shopping patterns, "
    )

    if budget is not None:
        prompt_for_llm += f"and keeping in mind their budget of around ${budget:.2f}, "
    if filters and filters.get("excluded_categories"):
        prompt_for_llm += f"while avoiding categories like {', '.join(filters['excluded_categories'])}, "

    prompt_for_llm += f"a good suggestion could be {rec_details_str}. "
    prompt_for_llm += (
        "Craft a brief, friendly, and conversational explanation (1-2 sentences) for this suggestion. "
        "Crucially, your explanation should acknowledge and adapt to the user's *latest statement* ('{current_user_prompt}'). "
        "For example, if they mentioned weather, try to tie your reason to that if it makes sense, or acknowledge the mismatch if it doesn't. "
        "If they asked a direct question that led to this recommendation, make sure your response feels like an answer. "
        "Avoid generic phrases if the user's prompt gives you more specific context to work with. "
        "Do not list more items than the one provided in the details."
    )

    try:
        response = llm.invoke(prompt_for_llm)
        conversational_text = strip_markdown_code_blocks(response.content)
        if len(recommendations_df) > num_to_mention:
            conversational_text += f" (I also found {len(recommendations_df) - num_to_mention} other suggestions. You can ask to see them as a table if you'd like!)"
        elif len(recommendations_df) == 1:
            conversational_text += (
                " (That's the top one I found based on your criteria!)"
            )

        return conversational_text
    except Exception as e:
        print(f"Error generating conversational recommendation text: {e}")
        return f"Based on your request, one item to consider is: {rec_details_str}."


# --- New Function to Get User Purchase History Summary ---
def get_user_purchase_history_summary(
    user_id: int, db: SQLDatabase, num_items: int = 3
) -> list[str] | str:
    if not db or not db._engine:
        return "Error: Database connection not available for history."
    query = f"""
    SELECT p.name as product_name, p.category as product_category
    FROM order_items oi
    JOIN products p ON oi.product_id = p.product_id
    WHERE oi.user_id = {user_id}
    ORDER BY oi.created_at DESC 
    LIMIT {num_items};
    """
    try:
        with db._engine.connect() as connection:
            result_proxy = connection.execute(text(query))
            rows = result_proxy.fetchall()
            if not rows:
                return []
            history_summary = [f"'{row[0]}' (Category: {row[1]})" for row in rows]
            return history_summary
    except Exception as e:
        print(f"Error fetching purchase history for user {user_id}: {e}")
        return f"Error fetching history: {str(e)}"


# --- Helper function to validate if text looks like SQL ---
def is_likely_sql(query_text: str) -> bool:
    if not query_text or not isinstance(query_text, str):
        return False
    cleaned_query_text = strip_markdown_code_blocks(query_text)
    query_upper = cleaned_query_text.upper()
    if not any(keyword in query_upper for keyword in SQL_KEYWORDS):
        return False
    if len(cleaned_query_text.split()) < 2 and "SELECT" not in query_upper:
        if not any(
            kw in query_upper for kw in ["SELECT", "WITH", "INSERT", "UPDATE", "DELETE"]
        ):
            return False
    conversational_starters = [
        "HOW ARE YOU",
        "WHAT IS",
        "CAN YOU",
        "TELL ME",
        "I AM",
        "SELECT A DATE",
        "WHAT'S THE PRICE OF",
        "PRICE OF",
    ]
    if (
        any(query_upper.startswith(starter) for starter in conversational_starters)
        and query_upper.count("SELECT") <= 1
        and query_upper.count("FROM") == 0
    ):
        if not (
            "PRICE" in query_upper
            or "BRAND" in query_upper
            or "CATEGORY" in query_upper
            or "DETAILS" in query_upper
            or "ABOUT" in query_upper
        ):
            return False
    return True


# --- LLM Intent Router ---
def route_user_intent(
    user_prompt: str,
    llm: ChatVertexAI,
    previous_context: dict = None,
    displayed_data_context: pd.DataFrame = None,
) -> dict:
    context_str = ""
    if previous_context and previous_context.get("user_id") is not None:
        context_str += f"""
        PREVIOUS RECOMMENDATION CONTEXT (for user_id {previous_context.get("user_id")}):
        - Number of recommendations previously requested/shown: {previous_context.get("num_recommendations")}
        - Active filters from last turn: {json.dumps(previous_context.get("filters"))}
        - Budget from last turn: {previous_context.get("budget")}
        """

    if displayed_data_context is not None and not displayed_data_context.empty:
        context_str += "\n\nCURRENTLY DISPLAYED RECOMMENDATIONS (summary of top item if available):\n"
        top_item = displayed_data_context.iloc[0]
        context_str += f"- Name: {top_item.get('recommended_product_name', 'N/A')}, Category: {top_item.get('recommended_product_category', 'N/A')}, Price: {top_item.get('recommended_product_price', 'N/A')}\n"

    prompt_template = f"""
    Analyze the user's LATEST PROMPT, considering the optional PREVIOUS RECOMMENDATION CONTEXT and CURRENTLY DISPLAYED RECOMMENDATIONS, to determine the primary intent.

    Possible intents:
    1.  "product_recommendation": User asks for new recommendations. Default output is conversational.
        - Extract: user_id (int).
        - Extract: num_recommendations (int, null if not specified by user).
        - Extract: budget_amount (float, null if not specified).
        - Extract: filters (dict like {{"excluded_categories": ["jeans"]}} for *this current request*, null if none mentioned *now*).
    2.  "product_recommendation_table": User explicitly asks for recommendations in a TABLE format (e.g., "show table", "list them").
        - Extract: user_id (int).
        - Extract: num_recommendations (int, null if not specified).
        - Extract: budget_amount (float, null if not specified).
        - Extract: filters (dict for *this current request*, null if none mentioned *now*).
    3.  "refine_recommendation": User wants to MODIFY the last set of recommendations (e.g., "no jeans now", "make it cheaper", "what if budget is 30?").
        - The user_id, and base num_recommendations/budget usually come from PREVIOUS RECOMMENDATION CONTEXT.
        - Extract: *only the new changes* for filters (dict, e.g., {{"excluded_categories": ["t-shirts"]}}) or a *new* budget_amount if explicitly stated in the LATEST PROMPT. If user says "show as table" during refinement, this intent is still "refine_recommendation" but the main app will handle the table display.
    4.  "explain_recommendation_context": User asks WHY a recommendation was made, or about the basis for it (e.g., "Why that item?", "What did user X buy before?", "Is it because I bought X?").
        - Extract: user_id (int, if specified in LATEST PROMPT, otherwise it will be inferred from PREVIOUS RECOMMENDATION CONTEXT by the application).
    5.  "query_displayed_recommendations": User asks a question about items in the CURRENTLY DISPLAYED RECOMMENDATIONS (e.g., "what's the price of the dress?", "tell me about the first one").
        - Extract: product_identifier_text (string, how user refers to the item from current display).
        - Extract: requested_attribute (string, e.g., "price", "brand", "details").
    6.  "general_sql_query": User asks a general question requiring a new Spanner SQL query against the database (not about current recommendations).
    7.  "conversational": General chat, greeting, or unrelated question.
    8.  "unknown": If intent is unclear.

    {context_str}

    Respond ONLY with a JSON object with the following keys: "intent", "user_id", "num_recommendations", "budget_amount", "filters", "product_identifier_text", "requested_attribute", "explanation".
    Set keys to null if not applicable for the detected intent. For "refine_recommendation", user_id/num_recommendations/budget_amount will be null if not *explicitly changed* in the current prompt, as they are inherited.

    User's LATEST PROMPT: "{user_prompt}"

    JSON Response:
    """
    try:
        response = llm.invoke(prompt_template)
        raw_response_content = response.content
        cleaned_response_content = strip_markdown_code_blocks(raw_response_content)
        st.session_state.router_llm_raw_output = cleaned_response_content
        intent_data = json.loads(cleaned_response_content)

        expected_keys = [
            "intent",
            "user_id",
            "num_recommendations",
            "budget_amount",
            "filters",
            "product_identifier_text",
            "requested_attribute",
            "explanation",
        ]
        for k in expected_keys:
            if k not in intent_data:
                intent_data[k] = None

        if intent_data.get("user_id") is not None:
            try:
                intent_data["user_id"] = int(intent_data["user_id"])
            except (ValueError, TypeError):
                intent_data["user_id"] = None
        if intent_data.get("num_recommendations") is not None:
            try:
                intent_data["num_recommendations"] = int(
                    intent_data["num_recommendations"]
                )
            except (ValueError, TypeError):
                intent_data["num_recommendations"] = None
        if intent_data.get("budget_amount") is not None:
            try:
                intent_data["budget_amount"] = float(intent_data["budget_amount"])
            except (ValueError, TypeError):
                intent_data["budget_amount"] = None

        if intent_data.get("filters") is not None:
            if not isinstance(intent_data.get("filters"), dict):
                intent_data["filters"] = None
            elif "excluded_categories" in intent_data["filters"]:
                if isinstance(intent_data["filters"]["excluded_categories"], list):
                    cleaned_cats = [
                        str(cat).strip().lower()
                        for cat in intent_data["filters"]["excluded_categories"]
                        if isinstance(cat, (str, int, float))
                    ]
                    intent_data["filters"]["excluded_categories"] = cleaned_cats
                else:
                    intent_data["filters"]["excluded_categories"] = []
        return intent_data
    except Exception as e:
        return {
            "intent": "unknown",
            "user_id": None,
            "num_recommendations": None,
            "budget_amount": None,
            "filters": None,
            "product_identifier_text": None,
            "requested_attribute": None,
            "explanation": f"Error in intent routing: {e}. LLM Output: {cleaned_response_content if 'cleaned_response_content' in locals() else 'N/A'}",
            "raw_llm_output": cleaned_response_content
            if "cleaned_response_content" in locals()
            else "No raw output",
        }


# --- Function to Answer Questions from Displayed DataFrame ---
def answer_from_displayed_data(
    df: pd.DataFrame, identifier_text: str, attribute_text: str, llm: ChatVertexAI
) -> str:
    if df is None or df.empty:
        return "There are no recommendations currently displayed to ask about."
    if not identifier_text or not attribute_text:
        return "I need to know which product and what information you're asking about."
    identifier_text_lower = identifier_text.lower()
    attribute_text_lower = attribute_text.lower()
    target_row = None
    ordinal_match = re.match(
        r"(?:the )?(first|second|third|fourth|fifth|last|(\d+)(?:st|nd|rd|th)?) (?:one|item|product|recommendation)",
        identifier_text_lower,
    )
    if ordinal_match:
        try:
            if ordinal_match.group(1) == "first":
                idx = 0
            elif ordinal_match.group(1) == "second":
                idx = 1
            elif ordinal_match.group(1) == "third":
                idx = 2
            elif ordinal_match.group(1) == "fourth":
                idx = 3
            elif ordinal_match.group(1) == "fifth":
                idx = 4
            elif ordinal_match.group(1) == "last":
                idx = len(df) - 1
            elif ordinal_match.group(2):
                idx = int(ordinal_match.group(2)) - 1
            if 0 <= idx < len(df):
                target_row = df.iloc[idx]
        except (ValueError, IndexError):
            pass
    if target_row is None:
        best_match_score = 0
        # Ensure 'recommended_product_name' column exists
        if "recommended_product_name" in df.columns:
            for i, row_name in enumerate(df["recommended_product_name"]):
                if identifier_text_lower in str(row_name).lower():
                    current_score = len(identifier_text_lower) / len(str(row_name))
                    if current_score > best_match_score:
                        best_match_score = current_score
                        target_row = df.iloc[i]
        if target_row is None and "recommended_product_name" in df.columns:
            name_matches = df[
                df["recommended_product_name"].str.contains(
                    identifier_text_lower, case=False, na=False
                )
            ]
            if len(name_matches) == 1:
                target_row = name_matches.iloc[0]
            elif len(name_matches) > 1:
                return f"I found multiple products matching '{identifier_text}'. Can you be more specific? Options: {', '.join(name_matches['recommended_product_name'].tolist())}"

    if target_row is None and "recommended_product_id" in df.columns:
        try:
            potential_id = int(identifier_text_lower)
            id_matches = df[df["recommended_product_id"] == potential_id]
            if len(id_matches) == 1:
                target_row = id_matches.iloc[0]
        except ValueError:
            pass

    if target_row is None:
        return f"Sorry, I couldn't identify which product you're referring to as '{identifier_text}' from the current list."

    product_name = target_row.get("recommended_product_name", "Unknown Product")
    if "price" in attribute_text_lower:
        price = target_row.get("recommended_product_price")
        return (
            f"The price of {product_name} is ${price:.2f}."
            if price is not None
            else f"Sorry, I don't have price information for {product_name}."
        )
    elif "brand" in attribute_text_lower:
        brand = target_row.get("recommended_product_brand")
        return (
            f"{product_name} is from the brand {brand}."
            if brand
            else f"Sorry, I don't have brand information for {product_name}."
        )
    elif "category" in attribute_text_lower:
        category = target_row.get("recommended_product_category")
        return (
            f"{product_name} belongs to the category: {category}."
            if category
            else f"Sorry, I don't have category information for {product_name}."
        )
    elif (
        "details" in attribute_text_lower
        or "more" in attribute_text_lower
        or "about" in attribute_text_lower
    ):
        details = [f"Details for {product_name}:"]
        if "recommended_product_category" in target_row and pd.notna(
            target_row["recommended_product_category"]
        ):
            details.append(f"- Category: {target_row['recommended_product_category']}")
        if "recommended_product_brand" in target_row and pd.notna(
            target_row["recommended_product_brand"]
        ):
            details.append(f"- Brand: {target_row['recommended_product_brand']}")
        if "recommended_product_price" in target_row and pd.notna(
            target_row["recommended_product_price"]
        ):
            details.append(f"- Price: ${target_row['recommended_product_price']:.2f}")
        if "recommendation_strength" in target_row and pd.notna(
            target_row["recommendation_strength"]
        ):
            details.append(
                f"- Recommendation Strength: {target_row['recommendation_strength']}"
            )
        return (
            "\n".join(details)
            if len(details) > 1
            else f"I don't have many specific details for {product_name} beyond its name."
        )
    else:
        for col in df.columns:
            if attribute_text_lower in col.lower().replace("_", " "):
                value = target_row.get(col)
                return (
                    f"For {product_name}, the {col.replace('recommended_', '').replace('_', ' ')} is: {value}."
                    if value is not None
                    else f"I don't have information on '{attribute_text}' for {product_name}."
                )
        return f"Sorry, I'm not sure what information you're asking for regarding '{attribute_text}' for {product_name}."


# --- Function for General SQL Query Generation and Execution ---
def query_spanner_with_llm(
    natural_language_query: str, db: SQLDatabase, llm: ChatVertexAI
) -> pd.DataFrame | str:
    if not db or not db._engine:
        return "Error: Database connection not established for LLM query or engine not available."
    if not llm:
        return "Error: Vertex AI LLM not initialized."
    try:
        # Provide schema information to the LLM for generating SQL queries
        table_info = ""
        try:
            table_info = db.get_table_info()
        except Exception as e:
            print(
                f"Warning: Could not retrieve table schema via db.get_table_info(): {e}"
            )
            # Fallback or use a predefined schema string if db.get_table_info() fails or is not comprehensive enough
            table_info = """
            CREATE TABLE users (user_id INT64 NOT NULL, first_name STRING(128), last_name STRING(128), email STRING(256), age INT64, gender STRING(16), state STRING(64), street_address STRING(256), postal_code STRING(64), city STRING(128), country STRING(128), latitude FLOAT64, longitude FLOAT64, traffic_source STRING(64), created_at STRING(64), user_geom STRING(64)) PRIMARY KEY(user_id);
            CREATE TABLE distribution_centers (distribution_center_id INT64 NOT NULL, name STRING(128), latitude FLOAT64, longitude FLOAT64, distribution_center_geom STRING(64)) PRIMARY KEY(distribution_center_id);
            CREATE TABLE events (event_id INT64 NOT NULL, user_id INT64 NOT NULL, sequence_number INT64, session_id STRING(128), created_at STRING(64), ip_address STRING(64), city STRING(128), state STRING(64), postal_code STRING(64), browser STRING(64), traffic_source STRING(64), uri STRING(1024), event_type STRING(64), FOREIGN KEY (user_id) REFERENCES users(user_id)) PRIMARY KEY(event_id);
            CREATE TABLE orders (order_id INT64 NOT NULL, user_id INT64 NOT NULL, status STRING(32), gender STRING(16), created_at STRING(64), returned_at STRING(64), shipped_at STRING(64), delivered_at STRING(64), num_of_item INT64, FOREIGN KEY (user_id) REFERENCES users(user_id)) PRIMARY KEY(order_id);
            CREATE TABLE products (product_id INT64 NOT NULL, cost FLOAT64, category STRING(128), name STRING(256), brand STRING(128), retail_price FLOAT64, department STRING(128), sku STRING(128), distribution_center_id INT64, FOREIGN KEY (distribution_center_id) REFERENCES distribution_centers(distribution_center_id)) PRIMARY KEY(product_id);
            CREATE TABLE order_items (order_item_id INT64 NOT NULL, order_id INT64 NOT NULL, user_id INT64 NOT NULL, product_id INT64 NOT NULL, inventory_item_id INT64, status STRING(32), created_at STRING(64), shipped_at STRING(64), delivered_at STRING(64), returned_at STRING(64), sale_price FLOAT64, FOREIGN KEY (order_id) REFERENCES orders(order_id), FOREIGN KEY (user_id) REFERENCES users(user_id), FOREIGN KEY (product_id) REFERENCES products(product_id)) PRIMARY KEY(order_item_id);
            """

        graph_ddl = """
CREATE OR REPLACE PROPERTY GRAPH LookerCommerceGraph
NODE TABLES (users, distribution_centers, products, orders, order_items, events)
EDGE TABLES (
  events AS Performed SOURCE KEY (user_id) REFERENCES users DESTINATION KEY (event_id) REFERENCES events,
  orders AS Placed SOURCE KEY (user_id) REFERENCES users DESTINATION KEY (order_id) REFERENCES orders,
  order_items AS OrderedItem SOURCE KEY (order_id) REFERENCES orders DESTINATION KEY (order_item_id) REFERENCES order_items,
  order_items AS Purchased SOURCE KEY (user_id) REFERENCES users DESTINATION KEY (order_item_id) REFERENCES order_items,
  order_items AS ItemProduct SOURCE KEY (order_item_id) REFERENCES order_items DESTINATION KEY (product_id) REFERENCES products,
  products AS Stocked SOURCE KEY (distribution_center_id)  REFERENCES distribution_centers DESTINATION KEY (product_id) REFERENCES products
);
        """
        schema_for_prompt = (
            f"Database Schema:\n{table_info}\n\nProperty Graph Schema:\n{graph_ddl}\n\n"
        )

        directive = (
            f"You are a Spanner SQL expert. Given the following database schema:\n"
            f"{schema_for_prompt}"
            "Your task is to generate a syntactically correct Spanner SQL query to answer the user's question. "
            "If the question involves graph relationships, use the LookerCommerceGraph. "
            "Only output the SQL query. Do not include any other text, explanation, or conversational phrases. "
            "If the question cannot be answered with SQL or is not a request for data, respond with 'NO_SQL_POSSIBLE'.\n"
            "User Question: "
        )
        full_prompt_for_llm_with_schema = directive + natural_language_query

        sql_generation_response = llm.invoke(full_prompt_for_llm_with_schema)
        generated_sql_text_raw = sql_generation_response.content
        generated_sql_text = strip_markdown_code_blocks(generated_sql_text_raw)
        st.session_state.generated_sql_for_display = generated_sql_text

        if "NO_SQL_POSSIBLE" in generated_sql_text.upper() or not is_likely_sql(
            generated_sql_text
        ):
            return (
                f"The LLM determined no SQL query is possible or did not generate a recognizable SQL query for your request. "
                f'LLM output: "{generated_sql_text}"'
            )
        with db._engine.connect() as connection:
            sql_text_obj = text(generated_sql_text)
            result_proxy = connection.execute(sql_text_obj)
            if result_proxy.returns_rows:
                rows = result_proxy.fetchall()
                if not rows:
                    return "The LLM-generated query executed successfully but returned no results."
                return pd.DataFrame(rows, columns=result_proxy.keys())
            else:
                return f"The LLM-generated query executed successfully. (No rows returned, rowcount: {result_proxy.rowcount})"
    except Exception as e:
        error_message = f"Error processing LLM query: {e}\n"
        if "generated_sql_text" in locals() and generated_sql_text:
            error_message += (
                f"LLM Generated Output (might be problematic):\n{generated_sql_text}"
            )
        return error_message


# --- Function for Conversational Response ---
def generate_conversational_response(user_prompt: str, llm: ChatVertexAI) -> str:
    if not llm:
        return "Error: Vertex AI LLM not initialized for conversation."
    try:
        prompt = f"User: {user_prompt}\nAssistant:"
        response = llm.invoke(prompt)
        return strip_markdown_code_blocks(response.content)
    except Exception as e:
        return f"Error in generating conversational response: {e}"


# --- Streamlit App ---
def main():
    st.set_page_config(page_title="Spanner Vertex AI Chat", layout="wide")
    st.title("Welcome to Persy!")
    st.caption("Ask questions or get recommendations. Powered by Vertex AI.")

    if "db_connection" not in st.session_state:
        st.session_state.db_connection = None
    if "db_connection_status" not in st.session_state:
        st.session_state.db_connection_status = "Initializing..."
    if "llm_instance" not in st.session_state:
        st.session_state.llm_instance = None
    if "llm_status" not in st.session_state:
        st.session_state.llm_status = "Initializing..."
    if "router_llm_raw_output" not in st.session_state:
        st.session_state.router_llm_raw_output = ""
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Hi! How can I help you with your Spanner data today?",
            }
        ]
    if "generated_sql_for_display" not in st.session_state:
        st.session_state.generated_sql_for_display = None
    if "last_recommendation_params" not in st.session_state:
        st.session_state.last_recommendation_params = {
            "user_id": None,
            "num_recommendations": 9,
            "filters": {},
            "budget": None,
            "output_format": "conversational",
        }
    if "last_displayed_recommendations_df" not in st.session_state:
        st.session_state.last_displayed_recommendations_df = None

    if st.session_state.db_connection is None:
        spanner_uri = f"spanner+spanner:///projects/{SPANNER_PROJECT_ID}/instances/{SPANNER_INSTANCE_ID}/databases/{SPANNER_DATABASE_ID}"
        try:
            # Pass include_tables to ensure all tables are discoverable if not by default
            # This might not be strictly necessary if the Spanner driver + SQLAlchemy dialect handle it,
            # but can be a good practice for complex schemas or if default discovery is limited.
            # For now, we will rely on the default schema discovery of SQLDatabase.
            st.session_state.db_connection = SQLDatabase.from_uri(spanner_uri)
            st.session_state.db_connection_status = "Connected"
        except Exception as e:
            tb_str = traceback.format_exc()
            st.sidebar.error(
                f"Spanner Connection Failed: {e}\n\nFull Traceback:\n{tb_str}"
            )
            st.session_state.db_connection_status = f"Failed: {e}"
            st.session_state.db_connection = None

    if st.session_state.llm_instance is None:
        try:
            st.session_state.llm_instance = ChatVertexAI(
                model_name="gemini-2.0-flash-001",
                temperature=0.3,
                project=SPANNER_PROJECT_ID,
                location="us-central1",
            )
            st.session_state.llm_status = "Vertex AI Initialized"
        except Exception as e:
            tb_str = traceback.format_exc()
            st.sidebar.error(f"Vertex AI Init Failed: {e}\n\nFull Traceback:\n{tb_str}")
            st.session_state.llm_status = f"Vertex AI Failed: {e}"
            st.session_state.llm_instance = None

    st.sidebar.header("⚙️ Configuration Status")
    st.sidebar.markdown(f"**Spanner Project:** `{SPANNER_PROJECT_ID}`")
    st.sidebar.markdown(f"**Spanner Instance:** `{SPANNER_INSTANCE_ID}`")
    st.sidebar.markdown(f"**Spanner Database:** `{SPANNER_DATABASE_ID}`")
    st.sidebar.markdown(f"**LLM Provider:** `Vertex AI (Google)`")
    st.sidebar.caption(
        f"Spanner: {st.session_state.get('db_connection_status', 'Unknown')}"
    )
    st.sidebar.caption(f"LLM: {st.session_state.get('llm_status', 'Unknown')}")
    if st.session_state.router_llm_raw_output:
        with st.sidebar.expander("Router LLM Raw Output (Debug)"):
            st.code(st.session_state.router_llm_raw_output, language=None)

    db_connection = st.session_state.db_connection
    llm_instance = st.session_state.llm_instance

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if isinstance(msg["content"], pd.DataFrame):
                st.dataframe(msg["content"], hide_index=True)
            else:
                st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about your data or for recommendations..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            st.session_state.generated_sql_for_display = None
            final_response_content_for_turn = (
                "Sorry, I encountered an issue. Please try again."
            )

            if st.session_state.get("llm_status") != "Vertex AI Initialized":
                final_response_content_for_turn = "Assistant: Vertex AI LLM is not initialized. Please check configuration."

            if llm_instance:
                message_placeholder.markdown("Understanding your request...")
                prev_rec_context = (
                    st.session_state.last_recommendation_params
                    if st.session_state.last_recommendation_params.get("user_id")
                    is not None
                    else None
                )
                current_displayed_df = st.session_state.get(
                    "last_displayed_recommendations_df"
                )
                intent_result = route_user_intent(
                    prompt,
                    llm_instance,
                    previous_context=prev_rec_context,
                    displayed_data_context=current_displayed_df,
                )

                original_intent = intent_result.get("intent")
                intent_to_process = original_intent

                extracted_user_id_from_router = intent_result.get("user_id")
                extracted_num_recs_from_router = intent_result.get(
                    "num_recommendations"
                )
                extracted_budget_from_router = intent_result.get("budget_amount")
                new_filters_from_router = intent_result.get("filters")
                product_identifier = intent_result.get("product_identifier_text")
                requested_attribute = intent_result.get("requested_attribute")
                router_explanation = intent_result.get(
                    "explanation", "No explanation from router."
                )

                current_user_id_for_rec = (
                    prev_rec_context.get("user_id") if prev_rec_context else None
                )
                current_num_recs_for_rec = (
                    prev_rec_context.get("num_recommendations", 9)
                    if prev_rec_context
                    else 9
                )
                current_budget_for_rec = (
                    prev_rec_context.get("budget") if prev_rec_context else None
                )
                compounded_filters = (
                    prev_rec_context.get("filters", {}).copy()
                    if prev_rec_context
                    else {}
                )
                current_output_format = (
                    prev_rec_context.get("output_format", "conversational")
                    if prev_rec_context
                    else "conversational"
                )

                if original_intent == "refine_recommendation":
                    if prev_rec_context and prev_rec_context.get("user_id") is not None:
                        current_user_id_for_rec = prev_rec_context["user_id"]
                        current_num_recs_for_rec = (
                            extracted_num_recs_from_router
                            if extracted_num_recs_from_router is not None
                            else current_num_recs_for_rec
                        )
                        current_budget_for_rec = (
                            extracted_budget_from_router
                            if extracted_budget_from_router is not None
                            else current_budget_for_rec
                        )

                        if new_filters_from_router and isinstance(
                            new_filters_from_router, dict
                        ):
                            if "excluded_categories" in new_filters_from_router:
                                new_excluded = new_filters_from_router[
                                    "excluded_categories"
                                ]
                                if isinstance(new_excluded, list):
                                    existing_excluded = compounded_filters.get(
                                        "excluded_categories", []
                                    )
                                    if not isinstance(existing_excluded, list):
                                        existing_excluded = []
                                    compounded_filters["excluded_categories"] = list(
                                        set(existing_excluded + new_excluded)
                                    )

                        if "table" in prompt.lower() or "list" in prompt.lower():
                            intent_to_process = "product_recommendation_table"
                            current_output_format = "table"
                        else:
                            intent_to_process = "product_recommendation"
                            current_output_format = prev_rec_context.get(
                                "output_format", "conversational"
                            )  # Keep previous format unless table explicitly asked

                    else:
                        final_response_content_for_turn = "Assistant: Please ask for initial recommendations for a user before trying to refine them."
                        intent_to_process = "conversational"

                elif (
                    original_intent == "product_recommendation"
                    or original_intent == "product_recommendation_table"
                ):
                    current_user_id_for_rec = extracted_user_id_from_router
                    current_num_recs_for_rec = (
                        extracted_num_recs_from_router
                        if extracted_num_recs_from_router is not None
                        else 9
                    )
                    current_budget_for_rec = extracted_budget_from_router
                    compounded_filters = (
                        new_filters_from_router if new_filters_from_router else {}
                    )
                    intent_to_process = original_intent
                    current_output_format = (
                        "table"
                        if original_intent == "product_recommendation_table"
                        else "conversational"
                    )

                router_decision_message = (
                    f"🤖 Router: Intent='{original_intent}'"
                    f", UserID='{extracted_user_id_from_router if extracted_user_id_from_router is not None else (current_user_id_for_rec if current_user_id_for_rec is not None else 'N/A')}'"
                    f", NumRecs='{current_num_recs_for_rec}'"
                    f", Budget='{current_budget_for_rec if current_budget_for_rec is not None else 'N/A'}'"
                    f", NewFilters='{json.dumps(new_filters_from_router) if new_filters_from_router else 'None'}'"
                    f", FinalFilters='{json.dumps(compounded_filters)}'"
                    f", OutputFormat='{current_output_format}'"
                    f". Reason: '{router_explanation}'"
                )
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": router_decision_message,
                })

                if (
                    intent_to_process == "product_recommendation"
                    or intent_to_process == "product_recommendation_table"
                ):
                    if current_user_id_for_rec is not None:
                        if db_connection:
                            budget_msg_part = (
                                f" with a budget of ${current_budget_for_rec:.2f}"
                                if current_budget_for_rec is not None
                                else ""
                            )
                            message_placeholder.markdown(
                                f"Fetching recommendations for User ID: {current_user_id_for_rec}{budget_msg_part} with filters: {json.dumps(compounded_filters) if compounded_filters else 'None'}..."
                            )

                            recommendation_data = get_spanner_recommendations_data(
                                current_user_id_for_rec,
                                db_connection,
                                current_num_recs_for_rec,
                                compounded_filters,
                                current_budget_for_rec,
                            )

                            if isinstance(recommendation_data, pd.DataFrame):
                                st.session_state.last_recommendation_params = {
                                    "user_id": current_user_id_for_rec,
                                    "num_recommendations": current_num_recs_for_rec,
                                    "filters": compounded_filters.copy(),
                                    "budget": current_budget_for_rec,
                                    "output_format": current_output_format,
                                }
                                st.session_state.last_displayed_recommendations_df = (
                                    recommendation_data.copy()
                                )

                                if current_output_format == "table":
                                    final_response_content_for_turn = (
                                        recommendation_data
                                    )
                                else:
                                    final_response_content_for_turn = (
                                        format_recommendations_as_text(
                                            recommendation_data,
                                            current_user_id_for_rec,
                                            current_num_recs_for_rec,
                                            current_budget_for_rec,
                                            compounded_filters,
                                            llm_instance,
                                            prompt,
                                        )
                                    )
                            else:
                                final_response_content_for_turn = recommendation_data
                        else:
                            final_response_content_for_turn = "Assistant: Cannot fetch recommendations, database is not connected."
                    else:
                        final_response_content_for_turn = "Assistant: I understand you want recommendations, but I couldn't identify a User ID. Please specify the user."

                elif intent_to_process == "explain_recommendation_context":
                    user_id_to_explain = extracted_user_id_from_router
                    if not user_id_to_explain and prev_rec_context:
                        user_id_to_explain = prev_rec_context.get("user_id")

                    if user_id_to_explain and db_connection:
                        message_placeholder.markdown(
                            f"Looking up purchase history for User ID {user_id_to_explain} to explain recommendations..."
                        )
                        history_summary = get_user_purchase_history_summary(
                            user_id_to_explain, db_connection
                        )

                        last_rec_item_name = "a recent suggestion"
                        last_rec_item_details = ""
                        df_for_context = (
                            st.session_state.last_displayed_recommendations_df
                        )
                        if df_for_context is not None and not df_for_context.empty:
                            top_rec = df_for_context.iloc[0]
                            last_rec_item_name = (
                                f"'{top_rec['recommended_product_name']}'"
                            )
                            last_rec_item_details = f"(Category: {top_rec['recommended_product_category']}, Price: ${top_rec['recommended_product_price']:.2f})"

                        explanation_prompt = (
                            f"The user's current question/statement is: '{prompt}'.\n"
                            f"For User ID {user_id_to_explain}, their recent purchase history includes items like: {', '.join(history_summary) if history_summary and isinstance(history_summary, list) else 'nothing specific found from recent purchases'}.\n"
                            f"A recent recommendation made to them was {last_rec_item_name} {last_rec_item_details}.\n"
                            "Based on this, provide a short, conversational explanation that addresses the user's question. "
                            "If the user's question implies a misunderstanding or challenges the recommendation's premise (e.g., 'it's getting warmer'), "
                            "acknowledge their point and try to reconcile it with the purchase history or suggest the recommendation might have been based on general patterns if the history isn't strongly indicative. "
                            "Be natural, helpful, and directly answer their question."
                        )
                        final_response_content_for_turn = strip_markdown_code_blocks(
                            llm_instance.invoke(explanation_prompt).content
                        )
                    elif not user_id_to_explain:
                        final_response_content_for_turn = "Assistant: I'm not sure which user's recommendations you're asking about. Could you please specify?"
                    else:
                        final_response_content_for_turn = "Assistant: I can't look up purchase history right now as the database is not connected."

                elif intent_to_process == "query_displayed_recommendations":
                    if (
                        st.session_state.last_displayed_recommendations_df is not None
                        and not st.session_state.last_displayed_recommendations_df.empty
                    ):
                        message_placeholder.markdown(
                            f"Looking for '{product_identifier}' details..."
                        )
                        final_response_content_for_turn = answer_from_displayed_data(
                            st.session_state.last_displayed_recommendations_df,
                            product_identifier,
                            requested_attribute,
                            llm_instance,
                        )
                    else:
                        final_response_content_for_turn = "Assistant: There are no recommendations currently displayed to ask about. Please get some recommendations first."

                elif intent_to_process == "general_sql_query":
                    if db_connection:
                        message_placeholder.markdown(
                            "Generating and executing SQL query..."
                        )
                        final_response_content_for_turn = query_spanner_with_llm(
                            prompt, db_connection, llm_instance
                        )
                    else:
                        final_response_content_for_turn = "Assistant: Cannot execute SQL query, database is not connected."

                elif intent_to_process == "conversational":
                    message_placeholder.markdown("Thinking...")
                    final_response_content_for_turn = generate_conversational_response(
                        prompt, llm_instance
                    )

            current_turn_display_message = ""
            generated_output_to_show = st.session_state.generated_sql_for_display

            if generated_output_to_show and original_intent == "general_sql_query":
                sql_display_part = f"🔍 **LLM Generated SQL Output:**\n```sql\n{generated_output_to_show}\n```"
                if isinstance(final_response_content_for_turn, str) and not isinstance(
                    final_response_content_for_turn, pd.DataFrame
                ):
                    current_turn_display_message = f"{sql_display_part}\n\nAssistant: {final_response_content_for_turn}"
                elif isinstance(final_response_content_for_turn, pd.DataFrame):
                    message_placeholder.markdown(sql_display_part)
                    st.dataframe(final_response_content_for_turn, hide_index=True)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": sql_display_part,
                    })
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": final_response_content_for_turn,
                    })
                    current_turn_display_message = None
            elif isinstance(final_response_content_for_turn, pd.DataFrame):
                message_placeholder.empty()
                st.dataframe(final_response_content_for_turn, hide_index=True)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": final_response_content_for_turn,
                })
                current_turn_display_message = None
            else:
                current_turn_display_message = (
                    f"Assistant: {final_response_content_for_turn}"
                    if not str(final_response_content_for_turn).startswith("Assistant:")
                    else str(final_response_content_for_turn)
                )

            if current_turn_display_message:
                message_placeholder.markdown(current_turn_display_message)
                if not isinstance(final_response_content_for_turn, pd.DataFrame):
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": current_turn_display_message,
                    })

            st.session_state.generated_sql_for_display = None
            st.session_state.router_llm_raw_output = ""


if __name__ == "__main__":
    main()
