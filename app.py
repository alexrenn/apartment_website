from flask import Flask, request, redirect, url_for, render_template
import sqlite3
import os
from datetime import date, timedelta

app = Flask(__name__)
DATABASE = os.path.join(os.path.dirname(__file__), 'bills.db')


ROOMMATES = ['Michelle', 'Bea','Kimmy', 'Violeta', 'Zulma', "Alex"]
CHORES =  ['Sweep + mop living area', 
           'Take out trash',
           'Take out recycling',
           'Clean windows + vacuum couch',
           'Sweep + mop kitchen',
           'Clean guest bathroom']

def get_db():
    """Get a database connection with row factory enabled."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paid_by TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            receipt_image TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bill_splits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER NOT NULL,
            owes_name TEXT NOT NULL,
            amount REAL NOT NULL,
            settled INTEGER DEFAULT 0,
            FOREIGN KEY (bill_id) REFERENCES bills(id)
        );
                       
        CREATE TABLE IF NOT EXISTS messages (
            msg TEXT NOT NULL,
            time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
    ''')
    conn.commit()
    conn.close()

init_db()

# --- Routes ---

@app.route('/')
def index():
    return redirect(url_for('bills'))


@app.route('/bills')
def bills():
    me = request.args.get('me', '')
    if me and me not in ROOMMATES:
        me = ''

    page = request.args.get('page', 1, type=int)
    if page < 1:
        page = 1
    per_page = 10
    offset = (page - 1) * per_page

    conn = get_db()
    total_bills = conn.execute('SELECT COUNT(*) as cnt FROM bills').fetchone()['cnt']
    all_bills = conn.execute('''
        SELECT b.*, GROUP_CONCAT(bs.owes_name) as split_among
        FROM bills b
        LEFT JOIN bill_splits bs ON b.id = bs.bill_id
        GROUP BY b.id
        ORDER BY b.created_at DESC
        LIMIT ? OFFSET ?
    ''', (per_page, offset)).fetchall()
    total_pages = (total_bills + per_page - 1) // per_page

    my_splits = []
    if me:
        my_splits = conn.execute('''
            SELECT bs.id, bs.amount, b.paid_by, b.description, b.created_at
            FROM bill_splits bs
            JOIN bills b ON bs.bill_id = b.id
            WHERE bs.owes_name = ? AND bs.settled = 0 AND b.paid_by != ?
            ORDER BY b.created_at DESC
        ''', (me, me)).fetchall()

    conn.close()
    balances = calculate_balances()
    return render_template('bills.html', bills=all_bills, roommates=ROOMMATES,
                           balances=balances, me=me, my_splits=my_splits,
                           page=page, total_pages=total_pages)


@app.route('/bills/add', methods=['POST'])
def add_bill():
    paid_by = request.form['paid_by']
    amount = float(request.form['amount'])
    description = request.form.get('description', '')
    split_among = request.form.getlist('split_among')

    # Validate inputs
    if paid_by not in ROOMMATES or not split_among or amount <= 0:
        return redirect(url_for('bills'))
    split_among = [name for name in split_among if name in ROOMMATES]
    if not split_among:
        return redirect(url_for('bills'))

    per_person = round(amount / len(split_among), 2) # 2 is number of digits after decimal point

    conn = get_db()
    cursor = conn.execute(
        'INSERT INTO bills (paid_by, amount, description) VALUES (?, ?, ?)',
        (paid_by, amount, description)
    )
    bill_id = cursor.lastrowid
    for person in split_among:
        conn.execute(
            'INSERT INTO bill_splits (bill_id, owes_name, amount) VALUES (?, ?, ?)',
            (bill_id, person, per_person)
        )
    conn.commit()
    conn.close()
    return redirect(url_for('bills'))

def calculate_balances():
    """Return a matrix: balances[debtor][creditor] = amount owed."""
    conn = get_db()
    rows = conn.execute('''
        SELECT b.paid_by, bs.owes_name, SUM(bs.amount) as total
        FROM bill_splits bs
        JOIN bills b ON bs.bill_id = b.id
        WHERE bs.settled = 0 AND bs.owes_name != b.paid_by
        GROUP BY b.paid_by, bs.owes_name
    ''').fetchall()
    conn.close()

    # balances[debtor][creditor] = how much debtor owes creditor
    balances = {name: {other: 0.0 for other in ROOMMATES} for name in ROOMMATES}
    for row in rows:
        balances[row['owes_name']][row['paid_by']] += row['total']
    return balances


@app.route('/bills/settle-one', methods=['POST'])
def settle_one():
    split_id = request.form['split_id']
    me = request.form.get('me', '')

    conn = get_db()
    conn.execute('''
        UPDATE bill_splits
        SET settled = 1
        WHERE id = ? AND owes_name = ?
        AND settled = 0
    ''', (split_id, me))
    conn.commit()
    conn.close()
    return redirect(url_for('bills', me=me))

@app.route('/chores')
def chores():
    today = date.today()
    week_number = today.isocalendar()[1]  # current ISO week number
    # Shift the chores list each week so assignments rotate
    shift = week_number % len(ROOMMATES)
    shifted_chores = CHORES[shift:] + CHORES[:shift]
    assignments = list(zip(ROOMMATES, shifted_chores))
    return render_template('chores.html', assignments=assignments)

@app.route('/chitchat', methods=['GET'])
def chitchat():
    conn = get_db()
    messages = conn.execute('SELECT msg, time FROM messages ORDER BY time DESC').fetchall()
    conn.close()
    return render_template('chitchat.html', messages=messages)
@app.route('/chitchat', methods=['POST'])
def post_msg():
    message = request.form['message']
    conn = get_db()
    conn.execute('INSERT INTO messages (msg) VALUES (?)', (message,))
    conn.commit()
    conn.close()
    return redirect(url_for('chitchat'))


if __name__ == '__main__':
    app.run(debug=True)


#todo
# delete recent bill