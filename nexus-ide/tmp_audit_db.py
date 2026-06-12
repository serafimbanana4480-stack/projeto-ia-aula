import sqlite3
conn = sqlite3.connect('C:/Users/rodri/Desktop/PROJETO IA AULA GIT CLONE/projeto-ia-aula/nexus-ide/data/nexus.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print('TABLES:', tables)
for t in tables:
    cursor.execute(f'SELECT COUNT(*) FROM {t}')
    print(f'{t}: {cursor.fetchone()[0]} rows')
conn.close()
