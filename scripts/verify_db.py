import sqlite3

def check_db():
    conn = sqlite3.connect("tradesense.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"Total tables in database: {len(tables)}")
    for t in tables:
        print(f"  - {t}")
    conn.close()

if __name__ == "__main__":
    check_db()
