import sqlite3

def get_schema():
    conn = sqlite3.connect('instance/db.sqlite3')
    cursor = conn.cursor()
    cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    for row in cursor.fetchall():
        if row[1] and '25' in row[1]:
            print(f"Table: {row[0]}")
            print(row[1])

if __name__ == '__main__':
    get_schema()
