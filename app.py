from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from fingerprint_logic import (
    initialize_sensor,
    get_fingerprint,
    enroll_fingerprint,
    delete_fingerprint
)
from firebase_utils import (
    add_user_to_firebase,
    list_enrolled_fingerprints,
    create_user_in_firestore,
    authenticate_user,
    get_pending_users,
    approve_user,
    db
)
import atexit, secrets, smtplib
from email.mime.text import MIMEText
from firebase_admin import firestore
from datetime import datetime
import pytz


app = Flask(__name__)
app.secret_key = "supersecretkey"

uart, finger = initialize_sensor()

# SMTP settings
SMTP_SERVER, SMTP_PORT = "smtp.gmail.com", 587
EMAIL_USERNAME = "eamssecuresafe@gmail.com"
EMAIL_PASSWORD = "hfsi iygk kkld ngnw"

temp_pins = {}

def generate_pin():
    return str(secrets.randbelow(900000) + 100000)

def send_email(to_email, pin):
    msg = MIMEText(f"Your login PIN is: {pin}. Expires in 15 min.")
    msg["Subject"], msg["From"], msg["To"] = "Secure Login PIN", EMAIL_USERNAME, to_email
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
            s.starttls()
            s.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            s.sendmail(EMAIL_USERNAME, to_email, msg.as_string())
    except Exception as e:
        print(f"Email error: {e}")

@app.route('/')
def home():
    return redirect(url_for('dashboard')) if 'email' in session else redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email, pwd = request.form['email'], request.form['password']
        user, err = authenticate_user(email, pwd)
        if err:
            return render_template('login.html', error=err)
        if not user.get('verified'):
            return render_template('login.html', error="Pending approval by root.")

        session['email'], session['role'] = user['email'], user['role']
        session.pop('pin_verified', None)

        # ? Add login log entry
        db.collection("login_logs").add({
            "email": email,
            "timestamp": firestore.SERVER_TIMESTAMP
        })

        return redirect(url_for('dashboard'))
    return render_template('login.html', message=request.args.get("message"))

@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method=='POST':
        email, pwd = request.form['email'], request.form['password']
        ok, msg = create_user_in_firestore(email, pwd)
        if not ok: return render_template('signup.html', error=msg)
        return redirect(url_for('login', message="Account created. Please log in.")) #return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login', message="You have been logged out.")) #return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'email' not in session: return redirect(url_for('login'))
    if not session.get('pin_verified'):
        pin = generate_pin(); temp_pins[session['email']]=pin
        send_email(session['email'], pin)
        return redirect(url_for('verify_pin'))
    users = get_pending_users() if session['role']=='root' else None
    return render_template('dashboard.html', pending_users=users, message=request.args.get("message")) #return render_template('dashboard.html', pending_users=users)

@app.route('/verify_pin', methods=['GET','POST'])
def verify_pin():
    if 'email' not in session: return redirect(url_for('login'))
    if request.method=='POST':
        pin = request.form.get('pin')
        if temp_pins.get(session['email'])==pin:
            session['pin_verified']=True
            temp_pins.pop(session['email'], None)
            return redirect(url_for('dashboard'))
        return render_template('verify_pin.html', error="Incorrect PIN.")
    return render_template('verify_pin.html')

@app.route('/index')
def fingerprint_ui():
    if 'email' not in session: return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/validate', methods=['POST'])
def validate():
    if get_fingerprint(finger):
        from fingerprint_logic import open_door_if_closed
        success, msg = open_door_if_closed()
        return jsonify({'success': success, 'message': msg})
    return jsonify({'success': False, 'message': 'Access denied'})
'''@app.route('/validate', methods=['POST'])
def validate():
    if get_fingerprint(finger):
        return jsonify({'success':True,'message':'Access granted'})
    return jsonify({'success':False,'message':'Access denied'})'''

@app.route('/do_enroll', methods=['POST'])
def do_enroll():
    if 'email' not in session: return redirect(url_for('login'))
    password = request.form.get('password')
    name = request.form.get('name')
    success = enroll_fingerprint(finger, password, name)
    return render_template('message.html', message="Enrollment successful!" if success else "Enrollment failed.")

@app.route('/do_delete', methods=['POST'])
def do_delete():
    if 'email' not in session:
        return redirect(url_for('login'))
    name = request.form.get('name')
    success = delete_fingerprint(finger, name)
    return render_template('message.html', message="Deleted successfully!" if success else "Deletion failed.")

@app.route('/delete_form')
def delete_form():
    if 'email' not in session:
        return redirect(url_for('login'))
    return render_template('delete_form.html')

'''@app.route('/enroll', methods=['POST'])
def enroll():
    return jsonify({'success': enroll_fingerprint(finger, entered_password, name)})'''

'''@app.route('/delete', methods=['POST'])
def delete():
    return jsonify({'success': delete_fingerprint(finger)})'''
    
@app.route('/closedoor', methods=['POST'])
def closedoor():
    from fingerprint_logic import close_door_if_open
    success, msg = close_door_if_open()
    return jsonify({'success': success, 'message': msg})


@app.route('/add_user', methods=['POST'])
def add_user():
    data=request.get_json(); user=data.get('username','').strip()
    if add_user_to_firebase(user): return jsonify({'success':True})
    return jsonify({'success':False,'message':'User exists'})

@app.route('/list')
def list_fps():
    return jsonify(list_enrolled_fingerprints())
    
@app.route('/approve_user/<doc_id>')
def approve_user_route(doc_id):
    if session.get('role') != 'root':
        return "Unauthorized", 403
    approve_user(doc_id)
    return redirect(url_for('dashboard', message="User approved!")) #return redirect(url_for('dashboard'))

@app.route("/enroll_form")
def enroll_form():
    if 'email' not in session:
        return redirect(url_for('login'))
    return render_template("enroll_form.html")
    
@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('role') != 'root':
        return "Unauthorized", 403

    fingerprints = list_enrolled_fingerprints()

    # Convert Firestore timestamps to Eastern Time
    eastern = pytz.timezone('US/Eastern')
    logins = db.collection("login_logs").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(20).stream()
    logins = [
        {
            "email": doc.to_dict().get("email"),
            "timestamp": doc.to_dict().get("timestamp")
                .astimezone(eastern)
                .strftime("%b %d, %Y  %I:%M %p") if doc.to_dict().get("timestamp") else "N/A"
        }
        for doc in logins
    ]

    return render_template("admin_dashboard.html", fingerprints=fingerprints, logins=logins)



@atexit.register
def cleanup():
    if uart: uart.close()
    

if __name__=="__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)











'''from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from fingerprint_logic import initialize_sensor, enroll_fingerprint, get_fingerprint, delete_fingerprint
from firebase_utils import (
    add_user_to_firebase, 
    list_enrolled_fingerprints,
    create_user_in_firestore,
    authenticate_user,
    get_pending_users,
    approve_user
)
import atexit

app = Flask(__name__)
app.secret_key = "supersecretkey"  # For session management

uart, finger = initialize_sensor()

# Redirect '/' to login or dashboard depending on login status
@app.route('/')
def home():
    if 'email' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

# Login page and handler
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user, error = authenticate_user(email, password)
        if error:
            return render_template('login.html', error=error)
        if not user.get('verified', False):
            return render_template('login.html', error="Your account is pending approval by the root user.")
        session['email'] = user['email']
        session['role'] = user['role']
        return redirect(url_for('dashboard'))
    return render_template('login.html')

# Signup page and handler
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        success, role_or_msg = create_user_in_firestore(email, password)
        if not success:
            return render_template('signup.html', error=role_or_msg)
        return redirect(url_for('login'))
    return render_template('signup.html')

# Logout clears the session
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Dashboard, shows different UI depending on role
@app.route('/dashboard')
def dashboard():
    if 'email' not in session:
        return redirect(url_for('login'))

    if session['role'] == 'root':
        pending_users = get_pending_users()
        return render_template('dashboard.html', pending_users=pending_users)
    else:
        return render_template('dashboard.html', pending_users=None)

# Root user approves a pending user
@app.route('/approve_user/<doc_id>')
def approve_user_route(doc_id):
    if session.get('role') != 'root':
        return "Unauthorized", 403
    approve_user(doc_id)
    return redirect(url_for('dashboard'))

# Fingerprint system page, requires login
@app.route('/index')
def fingerprint_ui():
    if 'email' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

# Existing fingerprint API routes (POST actions)
@app.route('/validate', methods=['POST'])
def validate_fingerprint():
    if get_fingerprint(finger):
        return jsonify({'success': True, 'message': 'Access granted'})
    return jsonify({'success': False, 'message': 'Access denied'})

@app.route('/enroll', methods=['POST'])
def enroll():
    success = enroll_fingerprint(finger)
    return jsonify({'success': success})

@app.route('/delete', methods=['POST'])
def delete():
    success = delete_fingerprint(finger)
    return jsonify({'success': success})

@app.route('/add_user', methods=['POST'])
def add_user():
    data = request.get_json()
    username = data.get('username', '').strip()
    if add_user_to_firebase(username):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'User already exists'})

@app.route('/list')
def list_fps():
    return jsonify(list_enrolled_fingerprints())

# Cleanup on exit
@atexit.register
def cleanup():
    if uart:
        uart.close()
    from servo_controller import cleanup_servo
    cleanup_servo()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)'''






'''from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from fingerprint_logic import initialize_sensor, enroll_fingerprint, get_fingerprint, delete_fingerprint
from firebase_utils import (
    add_user_to_firebase, list_enrolled_fingerprints,
    create_user_in_firestore, authenticate_user,
    get_pending_users, approve_user
)
import atexit

app = Flask(__name__)
app.secret_key = "supersecretkey"  # Needed for session management

uart, finger = initialize_sensor()

# ----------------- Fingerprint Functionality ----------------- #
@app.route('/')
def home():
    if 'email' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))
def index():
    return render_template('index.html')

@app.route('/validate', methods=['POST'])
def validate_fingerprint():
    if 'email' not in session or session.get('role') not in ['user', 'root']:
        return jsonify({'success': False, 'message': 'Unauthorized'})
    if get_fingerprint(finger):
        return jsonify({'success': True, 'message': 'Access granted'})
    return jsonify({'success': False, 'message': 'Access denied'})

@app.route('/enroll', methods=['POST'])
def enroll():
    if 'email' not in session or session.get('role') != 'user':
        return jsonify({'success': False, 'message': 'Unauthorized'})
    success = enroll_fingerprint(finger)
    return jsonify({'success': success})

@app.route('/delete', methods=['POST'])
def delete():
    success = delete_fingerprint(finger)
    return jsonify({'success': success})

@app.route('/add_user', methods=['POST'])
def add_user():
    data = request.get_json()
    username = data.get('username', '').strip()
    if add_user_to_firebase(username):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'User already exists'})

@app.route('/list')
def list_fps():
    return jsonify(list_enrolled_fingerprints())

# ----------------- User Authentication ----------------- #
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        success, role_or_msg = create_user_in_firestore(email, password)
        if not success:
            return f"Error: {role_or_msg}"
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user, error = authenticate_user(email, password)
        if error:
            return f"Login failed: {error}"
        if not user.get('verified'):
            return "Your account is pending approval by the root user."
        session['email'] = user['email']
        session['role'] = user['role']
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'email' not in session:
        return redirect(url_for('login'))
    if session['role'] == 'root':
        pending_users = get_pending_users()
        return render_template('dashboard.html', pending_users=pending_users)
    return render_template('dashboard.html', pending_users=None)

@app.route('/approve_user/<doc_id>')
def approve_user_route(doc_id):
    if session.get('role') != 'root':
        return "Unauthorized", 403
    approve_user(doc_id)
    return redirect(url_for('dashboard'))

# ----------------- Cleanup ----------------- #
@atexit.register
def cleanup():
    uart.close()
    from servo_controller import cleanup_servo
    cleanup_servo()

# ----------------- Run ----------------- #
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)

'''




'''from flask import Flask, render_template, request, jsonify
from fingerprint_logic import initialize_sensor, enroll_fingerprint, get_fingerprint, delete_fingerprint
from firebase_utils import add_user_to_firebase, list_enrolled_fingerprints
import atexit

app = Flask(__name__)
uart, finger = initialize_sensor()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/validate', methods=['POST'])
def validate_fingerprint():
    if get_fingerprint(finger):
        return jsonify({'success': True, 'message': 'Access granted'})
    return jsonify({'success': False, 'message': 'Access denied'})

@app.route('/enroll', methods=['POST'])
def enroll():
    success = enroll_fingerprint(finger)
    return jsonify({'success': success})

@app.route('/delete', methods=['POST'])
def delete():
    success = delete_fingerprint(finger)
    return jsonify({'success': success})

@app.route('/add_user', methods=['POST'])
def add_user():
    data = request.get_json()
    username = data.get('username', '').strip()
    if add_user_to_firebase(username):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'User already exists'})

@app.route('/list')
def list_fps():
    return jsonify(list_enrolled_fingerprints())

@atexit.register
def cleanup():
    uart.close()
    from servo_controller import cleanup_servo
    cleanup_servo()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)'''
