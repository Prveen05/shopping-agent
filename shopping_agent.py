import base64
import os
import sqlite3
import json
from typing import Optional
from unittest import result
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core import tools
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage


from reviews import get_product_rating

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "shopping_store.db")

llm = ChatGoogleGenerativeAI(model="gemma-4-31b-it", temperature=0)
vision_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

@tool
def search_products(query: str, max_price: Optional[float] = None, is_organic: Optional[bool] = None) -> str:
    """Search for products by query, optionally filtered by price and organic status."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    sql = "SELECT id, name, category, price, description, is_organic FROM products WHERE 1=1"
    params = []

    if query:
        sql += " AND (name LIKE ? OR description LIKE ?)"
        search_term = f"%{query}%"
        params.extend([search_term, search_term])

    if max_price is not None:
        sql += " AND price <= ?"
        params.append(max_price)

    if is_organic is not None:
        sql += " AND is_organic = ?"
        params.append(1 if is_organic else 0)

    sql += " ORDER BY price ASC"

    cursor.execute(sql, params)
    results = cursor.fetchall()
    conn.close()

    products = [
        {
            "id":          row[0],
            "name":        row[1],
            "category":    row[2],
            "price":       row[3],
            "description": row[4],
            "is_organic":  bool(row[5]),
        }
        for row in results
    ]
    return json.dumps(products)

@tool
def get_rating(product_id: int) -> str:
    """
    Retrieve the average rating and review count for a specific product.

    This tool queries the reviews database to calculate the average rating
    from all customer reviews and returns the total number of reviews for
    the specified product.

    Args:
        product_id (int): The unique identifier of the product to retrieve ratings for.

    Returns:
        str: A JSON string containing:
            - product_id (int): The requested product ID
            - average_rating (float): The average rating (0.0 to 5.0). Returns 0.0 if
              the product has no reviews.
            - review_count (int): The total number of reviews for the product

    Example:
        >>> get_rating(1)
        '{"product_id": 1, "average_rating": 4.625, "review_count": 4}'
    """
    result = get_product_rating(product_id)
    return json.dumps(result)    

@tool
def checkout(product_id: int) -> str:
    """
    Place an order for the given product ID. Saves the order to the database and returns
    a confirmation message with the order ID, product name, and price.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT name, price FROM products WHERE id = ?", (product_id,))
        product = cursor.fetchone()

        if not product:
            return json.dumps({
                "error": f"Product with ID {product_id} not found",
                "product_id": product_id
            })

        product_name, price = product

        cursor.execute(
            "INSERT INTO orders (product_id, product_name, price) VALUES (?, ?, ?)",
            (product_id, product_name, price)
        )
        conn.commit()

        order_id = cursor.lastrowid

        return (
            f"Order #{order_id} confirmed! '{product_name}' has been successfully ordered for ${price:.2f}. "
            f"Your order will arrive in 3-5 business days. Thank you for shopping with us!"
        )
    except sqlite3.Error as e:
        return json.dumps({
            "error": f"Database error during checkout: {str(e)}",
            "product_id": product_id
        })
    finally:
        conn.close()

@tool
def describe_product_image(image_path: str) -> str:
    """
    Analyze the product image and return a description of its contents.

    This tool uses a pre-trained image recognition model to identify objects,
    colors, and other relevant features in the product image. The resulting
    description can help customers understand the product's appearance and
    characteristics.

    Args:
        image_path (str): The file path to the product image to be analyzed.

    Returns:
        str: A description of the contents of the product image.
    """
    # Placeholder implementation - replace with actual image analysis logic
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()

    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

    message = HumanMessage(content=[
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{image_data}"},
        },
        {
            "type": "text",
            "text": (
                "Look at this product image and extract its key attributes. "
                "Return ONLY a JSON object with these fields:\n"
                "- product_type: what kind of product it is (e.g. honey, olive oil, almonds)\n"
                "- search_query: a short keyword to search for it (e.g. 'honey', 'olive oil')\n"
                "- is_organic: true if the label says organic, false if not, null if unclear\n"
                "- description: one sentence describing the product"
            ),
        },
    ])

    response = vision_llm.invoke([message])
    print("Image analysis response:", response.content)
    return response.content



agent = create_agent(
    model=llm,
    tools=[search_products, get_rating, checkout, describe_product_image],
    system_prompt=(
        "You are a helpful shopping assistant for an organic food store. Follow these rules strictly.\n\n"
        "GUARD RAILS — ENFORCE THESE FIRST\n"
        "1. If the user's message is NOT related to shopping, products, prices, ratings, orders, or store assistance, "
        "   REJECT it politely WITHOUT using any tools.\n"
        "2. Example off-topic requests: general knowledge questions, jokes, coding help, weather, sports, politics, etc.\n"
        "3. When rejecting, say: 'I'm here to help you find and purchase products from our organic food store. "
        "Can I help you search for something specific?'\n"
        "4. Always redirect back to shopping assistance.\n\n"
        "IMAGE SEARCH — when the user provides an image path:\n"
        "1. Call describe_product_image with the path to identify the product.\n"
        "2. Use the returned search_query and is_organic to call search_products.\n"
        "3. Continue with the BROWSING flow from step 2 onwards.\n\n"
        "BROWSING — when the user describes what they want to buy:\n"
        "1. Call search_products to find matching items (apply any price/organic filters given).\n"
        "2. For each candidate, call get_rating to retrieve its average rating.\n"
        "3. Filter by the user's minimum rating if specified.\n"
        "4. Present qualifying products as a numbered list. For each item use this exact format "
        "   (plain text, no backticks, no code blocks, no bold, no italic):\n\n"
        "   #<number>. <name> (ID:<product_id>) — $<price> ★<rating> — <organic or non-organic>\n\n"
        "   Add a blank line between each product entry for readability. "
        "   Always include (ID:X) so you can reference it later.\n"
        "5. If only one product qualifies, still show it in the list and ask: "
        "   'Would you like to order it? Just say yes or give me the number.'\n"
        "6. Do NOT call checkout at this stage.\n\n"
        "ORDERING — when the user confirms they want to buy (e.g. 'yes', 'sure', 'go ahead', "
        "'order number 2', 'the first one', 'get me #3'):\n"
        "1. Look at your previous message to find the (ID:X) for the chosen product "
        "   (if only one was listed and the user says 'yes', use that product's ID).\n"
        "2. Call checkout with that product_id (the number from (ID:X)).\n"
        "3. Confirm the order to the user in plain text.\n\n"
        "IMPORTANT CONSTRAINTS:\n"
        "- Never place an order unless the user explicitly confirms.\n"
        "- Never guess a product_id — always take it from the (ID:X) in your own previous message.\n"
        "- Never use tools for off-topic questions — reject and redirect instead."
    )
)

if __name__ == "__main__":
    # Example usage
    user_input = "I'm looking for organic honey under $20. Can you help me find some options?"
    response = agent.invoke(
        {
            "messages": [
                {
                    "role": "user", 
                    "content": user_input
                }
            ]
        }
    )
    print(response["messages"][-1].content)
   