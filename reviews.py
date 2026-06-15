import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "shopping_store.db")


def get_product_rating(product_id):
    """Get the average rating for a product from the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT AVG(rating), COUNT(*) FROM reviews WHERE product_id = ?", (product_id,))
        result = cursor.fetchone()
        conn.close()

        avg_rating = result[0] if result and result[0] is not None else 0.0
        count = result[1] if result else 0

        return { "product_id": product_id, "average_rating": avg_rating, "review_count": count }
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return { "product_id": product_id, "average_rating": 0.0, "review_count": 0 }
    
def get_ratings_for_products(product_ids: list[int]) -> list[dict]:
    """Get average ratings for a list of product IDs."""
    if not product_ids:
        return []

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        placeholders = ','.join('?' * len(product_ids))
        query = f"""
            SELECT product_id, AVG(rating) as average_rating, COUNT(*) as review_count
            FROM reviews
            WHERE product_id IN ({placeholders})
            GROUP BY product_id
        """

        cursor.execute(query, product_ids)
        results = cursor.fetchall()
        conn.close()

        ratings_dict = {}
        for product_id, avg_rating, count in results:
            ratings_dict[product_id] = {
                "product_id": product_id,
                "average_rating": round(avg_rating, 2) if avg_rating else 0.0,
                "review_count": count
            }

        return [ratings_dict.get(pid, {"product_id": pid, "average_rating": 0.0, "review_count": 0})
                for pid in product_ids]
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return [{"product_id": pid, "average_rating": 0.0, "review_count": 0} for pid in product_ids]  

if __name__ == "__main__":
    # Example usage
    result = get_product_rating(1)
    print('Single Product Rating')
    print(f"Product ID: {result['product_id']}, Average Rating: {result['average_rating']}, Review Count: {result['review_count']}")
   
    results = get_ratings_for_products([1, 2, 3])
    print('\nMultiple Product Ratings')
    for res in results:
        print(f"Product ID: {res['product_id']}, Average Rating: {res['average_rating']}, Review Count: {res['review_count']}")