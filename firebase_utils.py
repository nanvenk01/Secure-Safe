import firebase_admin
from firebase_admin import credentials, firestore

# Make sure this matches your actual file name and path
cred = credentials.Certificate("safe-6228a-firebase-adminsdk-fbsvc-4310d3f187.json")

# Initialize Firebase app  THIS IS MISSING IN YOUR ERROR
firebase_admin.initialize_app(cred)

# Create Firestore client
db = firestore.client()

def add_user_to_firebase(username):
    users_ref = db.collection('users')
    existing = users_ref.where('username', '==', username).get()
    if existing:
        return False
    users_ref.add({'username': username})
    return True

def list_enrolled_fingerprints():
    users_ref = db.collection('users').stream()
    return [doc.to_dict() for doc in users_ref]

def create_user_in_firestore(email, password):
    users_ref = db.collection('users')
    existing = users_ref.where('email', '==', email).get()
    if existing:
        return False, "User already exists"

    # If first user, assign root
    all_users = list(users_ref.stream())
    role = 'root' if not all_users else 'pending'

    users_ref.add({
        'email': email,
        'password': password,  # NOTE: This is for mock login only
        'role': role,
        'verified': role == 'root'
    })

    return True, role

def authenticate_user(email, password):
    users_ref = db.collection('users')
    matching = users_ref.where('email', '==', email).where('password', '==', password).get()
    if not matching:
        return None, "Invalid credentials"
    
    doc = matching[0]
    data = doc.to_dict()
    data['id'] = doc.id
    return data, None

def get_pending_users():
    return [
        {**doc.to_dict(), 'doc_id': doc.id}
        for doc in db.collection('users').where('role', '==', 'pending').stream()
    ]

def approve_user(doc_id):
    user_ref = db.collection('users').document(doc_id)
    user_ref.update({'role': 'user', 'verified': True})


