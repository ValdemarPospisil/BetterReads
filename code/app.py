from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask_session import Session
from forms import RegistrationForm, LoginForm, CreateBookForm
from werkzeug.security import generate_password_hash, check_password_hash
import cloudinary
import cloudinary.uploader
import cloudinary.api
from neo4j import GraphDatabase
import os
from functools import wraps
import json
from datetime import datetime


app = Flask(__name__)
# Flask app setup
SECRET_KEY = 'you-will-never-guess'
USER_IMG_FOLDER = 'static/imgs/'
app.config['UPLOAD_FOLDER'] = USER_IMG_FOLDER
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'  # You can choose other session types as well
Session(app)

# Configuration       
cloudinary.config( 
    cloud_name = "dyad41msw", 
    api_key = "429495373674336", 
    api_secret = "gQK9cHKJzk83nMU2IEjyO7Efaos", # Click 'View API Keys' above to copy your API secret
    secure=True
)

NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "PassatGolf"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


@app.route('/home')
@app.route('/index')
@app.route('/')
def index():
    return render_template('index.html')

def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'nickname' not in session:
                return redirect(url_for('login'))
            with driver.session() as db_session:
                result = db_session.run("MATCH (u:User {nickname: $nickname}) RETURN u.role AS role", nickname=session['nickname'])
                record = result.single()
                if not record or record['role'] not in roles:
                    abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/admin')
@roles_required('admin')
def admin_dashboard():
    users = []
    with driver.session() as db_session:
        result = db_session.run("MATCH (u:User) RETURN u.full_name AS full_name, u.nickname AS nickname, u.email AS email")
        users = [{"full_name": record["full_name"], "nickname": record["nickname"], "email": record["email"]} for record in result]
    return render_template('admin/admin_dashboard.html', users=users)

@app.route('/delete_user/<nickname>', methods=['POST'])
@roles_required('admin')
def delete_user(nickname):
    with driver.session() as db_session:
        db_session.run("MATCH (u:User {nickname: $nickname}) DETACH DELETE u", nickname=nickname)
    flash(f'User {nickname} has been deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
@roles_required('admin')
def manage_users():
    users = []
    with driver.session() as db_session:
        result = db_session.run("MATCH (u:User) RETURN u.full_name AS full_name, u.nickname AS nickname, u.email AS email")
        users = [{"full_name": record["full_name"], "nickname": record["nickname"], "email": record["email"]} for record in result]
    return render_template('admin/users.html', users=users)

@app.route('/admin/books')
@roles_required('admin')
def manage_books():
    books = []
    with driver.session() as db_session:
        result = db_session.run("""
            MATCH (b:Book)<-[:WROTE]-(a:Author)
            OPTIONAL MATCH (u:User)-[:HAS_STATUS]->(b)
            RETURN b.name AS name, a.name AS author, collect(u.nickname) AS users
        """)
        books = [{"name": record["name"], "author": record["author"], "users": [{"nickname": user} for user in record["users"]]} for record in result]
    return render_template('admin/books.html', books=books)

@app.route('/delete_book/<book_name>', methods=['POST'])
@roles_required('admin')
def delete_book(book_name):
    with driver.session() as db_session:
        db_session.run("MATCH (b:Book {name: $book_name}) DETACH DELETE b", book_name=book_name)
    flash(f'Book {book_name} has been deleted.', 'success')
    return redirect(url_for('manage_books'))

@app.route('/profile/<nickname>', methods=['GET', 'POST'])
def profile(nickname):
    user_data = {}
    is_friend = False
    with driver.session() as db_session:
        result = db_session.run("""
            MATCH (u:User {nickname: $nickname})-[r:HAS_STATUS]->(b:Book)
            RETURN u.full_name AS full_name, u.email AS email, u.profile_picture AS profile_picture, u.bio AS bio,
                   b.name AS book_name, b.image_url AS image_url, r.status AS status
        """, nickname=nickname)
        
        books = {
            "want_to_read": [],
            "reading": [],
            "read": []
        }
        
        for record in result:
            if not user_data:
                user_data = {
                    "full_name": record["full_name"],
                    "email": record["email"],
                    "profile_picture": record["profile_picture"],
                    "bio": record["bio"]
                }
            book = {
                "name": record["book_name"],
                "image_url": record["image_url"]
            }
            books[record["status"]].append(book)

        if 'nickname' in session and session['nickname'] != nickname:
            friend_check = db_session.run("""
                MATCH (u:User {nickname: $current_nickname})-[:FRIEND]->(f:User {nickname: $profile_nickname})
                RETURN f
            """, current_nickname=session['nickname'], profile_nickname=nickname)
            is_friend = friend_check.single() is not None

    if 'nickname' in session and session['nickname'] == nickname:
        if request.method == 'POST':
            bio = request.form.get('bio')
            profile_picture = request.files.get('profile_picture')
            profile_picture_url = user_data['profile_picture']

            if profile_picture:
                upload_result = cloudinary.uploader.upload(profile_picture)
                profile_picture_url = upload_result['secure_url']

            with driver.session() as db_session:
                db_session.run("""
                    MATCH (u:User {nickname: $nickname})
                    SET u.bio = $bio, u.profile_picture = $profile_picture
                """, nickname=nickname, bio=bio, profile_picture=profile_picture_url)

            flash('Profile updated successfully!', 'success')
            return redirect(url_for('profile', nickname=nickname))

        return render_template('profile.html', books=books, nickname=nickname, user=user_data, editable=True)
    else:
        return render_template('profile.html', books=books, nickname=nickname, user=user_data, editable=False, is_friend=is_friend)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'nickname' not in session:
        return redirect(url_for('login'))

    nickname = session['nickname']
    bio = request.form.get('bio')
    profile_picture = request.files.get('profile_picture')
    profile_picture_url = None

    if profile_picture:
        upload_result = cloudinary.uploader.upload(profile_picture)
        profile_picture_url = upload_result['secure_url']

    with driver.session() as db_session:
        if profile_picture_url:
            db_session.run("""
                MATCH (u:User {nickname: $nickname})
                SET u.bio = $bio, u.profile_picture = $profile_picture
            """, nickname=nickname, bio=bio, profile_picture=profile_picture_url)
        else:
            db_session.run("""
                MATCH (u:User {nickname: $nickname})
                SET u.bio = $bio
            """, nickname=nickname, bio=bio)

    flash('Profile updated successfully!', 'success')
    return redirect(url_for('profile', nickname=nickname))

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        full_name = form.full_name.data
        nickname = form.nickname.data
        email = form.email.data
        password = generate_password_hash(form.password.data)
        role = form.role.datayy

        with driver.session() as db_session:
            result = db_session.run("MATCH (u:User {nickname: $nickname}) RETURN u", nickname=nickname)
            if result.single():
                flash('Nickname already exists. Please choose a different one.', 'danger')
            else:
                db_session.run(
                    "CREATE (u:User {full_name: $full_name, nickname: $nickname, email: $email, password: $password, role: $role})",
                    full_name=full_name, nickname=nickname, email=email, password=password, role=role
                )
                flash('Registration successful! Please log in.', 'success')
                return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        nickname = form.nickname.data
        password = form.password.data

        with driver.session() as db_session:
            result = db_session.run("MATCH (u:User {nickname: $nickname}) RETURN u.password AS password, u.role AS role", nickname=nickname)
            record = result.single()
            if record and check_password_hash(record['password'], password):
                session['nickname'] = nickname
                session['role'] = record['role']
                flash('Login successful!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Invalid nickname or password. Please try again.', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
def logout():
    session.pop('nickname', None)
    session.pop('role', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

def create_genre():
    """Creates a fixed set of genres in the database."""
    with driver.session() as db_session:
        genres = ["Fiction", "Non-Fiction", "Science Fiction", "Fantasy", "Mystery", "Thriller",
                  "Romance", "Horror", "Classic", "Biography", "Autobiography", "Self-Help",
                  "Philosophy", "Epic-fantasy", "Historical-fiction", "Young-adult", "Children",
                  "Dystopian", "Adventure", "Crime", "Short-stories", "Dark-fantasy", "Paranormal",
                  "Magic", "Adult", "LGBQT", "Gothic"]
        for genre in genres:
            db_session.run("MERGE (g:Genre {name: $name})", name=genre)
    return "Genres created successfully!"

def upload_image(file=None):
    """Uploads an image to Cloudinary, resizes it to 684x100, and returns the URL."""
    if file:
        result = cloudinary.uploader.upload(file, transformation={"width": 400, "height": 600, "scale": "limit"})
        return result.get("url")
    return None

@app.route('/update_book_status/<book_name>', methods=['POST'])
def update_book_status(book_name):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    status = request.form.get('status')
    user_nickname = session['nickname']

    with driver.session() as db_session:
        db_session.run("""
            MATCH (u:User {nickname: $user_nickname}), (b:Book {name: $book_name})
            MERGE (u)-[r:HAS_STATUS]->(b)
            SET r.status = $status
        """, user_nickname=user_nickname, book_name=book_name, status=status)

    return redirect(url_for('book_detail', book_name=book_name))

def create_author_book_relationship_with_genres(author_name, author_surname, book_data, genres):
    """Creates a book, author, and genre nodes with relationships."""
    with driver.session() as db_session:
        query = """
            MERGE (author:Author {name: $author_name, surname: $author_surname})
            CREATE (book:Book {name: $name, description: $description, pages: $pages, datePublished: $datePublished, image_url: $image_url})
            MERGE (author)-[:WROTE]->(book)
            WITH book
            UNWIND $genres AS genre_name
            MATCH (g:Genre {name: genre_name})
            MERGE (book)-[:BELONGS_TO]->(g)
        """
        db_session.run(query, author_name=author_name, author_surname=author_surname,
                    name=book_data["name"], description=book_data["description"],
                    pages=book_data["pages"], datePublished=book_data["datePublished"],
                    image_url=book_data["image_url"], genres=genres)

@app.route('/create_book', methods=['GET', 'POST'])
@roles_required('admin')
def create_book():
    form = CreateBookForm()

    # Get genres from database for the form
    with driver.session() as db_session:
        result = db_session.run("MATCH (g:Genre) RETURN g.name AS name")
        genres = [(record["name"], record["name"]) for record in result]
        form.genres.choices = genres

    if form.validate_on_submit():
        name = form.name.data
        description = form.description.data
        pages = form.pages.data
        datePublished = form.datePublished.data
        author_name = form.author_name.data
        author_surname = form.author_surname.data
        genres = form.genres.data

        # Handle the image upload
        image_file = form.image.data
        image_url = upload_image(image_file)

        # Prepare book data
        book_data = {
            "name": name,
            "description": description,
            "pages": pages,
            "datePublished": datePublished,
            "image_url": image_url
        }

        # Create the author-book relationship and add genres
        create_author_book_relationship_with_genres(author_name, author_surname, book_data, genres)

        return redirect(url_for('index'))

    return render_template('create_book.html', form=form)

@app.route('/books')
def list_books():
    genre_filter = request.args.get('genre')
    with driver.session() as db_session:
        if genre_filter:
            result = db_session.run("""
                MATCH (b:Book)-[:BELONGS_TO]->(g:Genre {name: $genre})
                MATCH (b)<-[:WROTE]-(a:Author)
                RETURN b.name AS book_name, a.name AS author_name, a.surname AS author_surname, b.image_url AS image_url
            """, genre=genre_filter)
        else:
            result = db_session.run("""
                MATCH (b:Book)<-[:WROTE]-(a:Author)
                RETURN b.name AS book_name, a.name AS author_name, a.surname AS author_surname, b.image_url AS image_url
            """)
        books = [
            {
                "name": record["book_name"],
                "author": f"{record['author_name']} {record['author_surname']}",
                "image_url": record["image_url"]
            }
            for record in result
        ]

        genres_result = db_session.run("MATCH (g:Genre) RETURN g.name AS name")
        genres = [record["name"] for record in genres_result]

    return render_template('list_books.html', books=books, genres=genres, selected_genre=genre_filter)

@app.route('/book/<book_name>')
def book_detail(book_name):
    with driver.session() as db_session:
        result = db_session.run("""
            MATCH (b:Book {name: $book_name})-[:WROTE]-(a:Author)
            OPTIONAL MATCH (b)-[:BELONGS_TO]->(g:Genre)
            OPTIONAL MATCH (u:User)-[r:REVIEWED]->(b)
            RETURN b.name AS book_name, b.description AS description, b.pages AS pages, 
                   b.datePublished AS datePublished, b.image_url AS image_url, 
                   a.name AS author_name, a.surname AS author_surname, 
                   collect(DISTINCT g.name) AS genres, collect(DISTINCT {user: u.nickname, rating: r.rating, text: r.text}) AS reviews
        """, book_name=book_name)
        book = result.single()
        if book:
            book_data = {
                "name": book["book_name"],
                "description": book["description"],
                "pages": book["pages"],
                "datePublished": book["datePublished"],
                "image_url": book["image_url"],
                "author": f"{book['author_name']} {book['author_surname']}",
                "genres": book["genres"],
                "reviews": book["reviews"]
            }
        else:
            abort(404)
    return render_template('book_detail.html', book=book_data)

@app.route('/submit_review/<book_name>', methods=['POST'])
def submit_review(book_name):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    rating = int(request.form.get('rating'))
    review_text = request.form.get('review')
    user_nickname = session['nickname']

    with driver.session() as db_session:
        # Create the review relationship
        db_session.run("""
            MATCH (u:User {nickname: $user_nickname}), (b:Book {name: $book_name})
            CREATE (u)-[:REVIEWED {rating: $rating, text: $review_text}]->(b)
        """, user_nickname=user_nickname, book_name=book_name, rating=rating, review_text=review_text)

        # Update the book status to "Read" if not already
        db_session.run("""
            MATCH (u:User {nickname: $user_nickname}), (b:Book {name: $book_name})
            MERGE (u)-[r:HAS_STATUS]->(b)
            ON CREATE SET r.status = 'read'
            ON MATCH SET r.status = CASE WHEN r.status = 'read' THEN r.status ELSE 'read' END
        """, user_nickname=user_nickname, book_name=book_name)

    return redirect(url_for('book_detail', book_name=book_name))

@app.route('/import_users', methods=['POST'])
def import_users():
    if 'nickname' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    file = request.files['file']
    if not file:
        flash('No file selected.', 'danger')
        return redirect(url_for('admin_dashboard'))

    users = json.load(file)

    with driver.session() as db_session:
        for user in users:
            full_name = user['full_name']
            nickname = user['nickname']
            email = user['email']
            password = generate_password_hash(user['password'])
            role = "user"

            result = db_session.run("MATCH (u:User {nickname: $nickname}) RETURN u", nickname=nickname)
            if result.single():
                flash(f"Nickname {nickname} already exists. Skipping user.", 'warning')
            else:
                db_session.run(
                    "CREATE (u:User {full_name: $full_name, nickname: $nickname, email: $email, password: $password, role: $role})",
                    full_name=full_name, nickname=nickname, email=email, password=password, role=role
                )
                flash(f"User {nickname} registered successfully.", 'success')

    return redirect(url_for('admin_dashboard'))


def create_friend_request_relationship():
    """Creates the friend request and friendship relationships in the database."""
    with driver.session() as db_session:
        db_session.run("""
            MATCH (u:User), (f:User)
            WHERE u.nickname <> f.nickname
            MERGE (u)-[:FRIEND_REQUEST]->(f)
            MERGE (u)-[:FRIEND]->(f)
        """)
    return "Friend request and friendship relationships created successfully!"

@app.route('/send_friend_request/<nickname>', methods=['POST'])
def send_friend_request(nickname):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    sender_nickname = session['nickname']

    with driver.session() as db_session:
        friend_check = db_session.run("""
            MATCH (sender:User {nickname: $sender_nickname})-[:FRIEND]->(receiver:User {nickname: $receiver_nickname})
            RETURN receiver
        """, sender_nickname=sender_nickname, receiver_nickname=nickname)
        
        if friend_check.single():
            flash(f'You are already friends with {nickname}.', 'warning')
            return redirect(url_for('profile', nickname=nickname))

        db_session.run("""
            MATCH (sender:User {nickname: $sender_nickname}), (receiver:User {nickname: $receiver_nickname})
            MERGE (sender)-[:FRIEND_REQUEST]->(receiver)
            CREATE (notification:Notification {type: 'friend_request', sender: $sender_nickname, receiver: $receiver_nickname, timestamp: $timestamp})
            MERGE (receiver)-[:HAS_NOTIFICATION]->(notification)
        """, sender_nickname=sender_nickname, receiver_nickname=nickname, timestamp=datetime.now().isoformat())

    flash(f'Friend request sent to {nickname}.', 'success')
    return redirect(url_for('profile', nickname=nickname))

@app.route('/accept_friend_request/<nickname>', methods=['POST'])
def accept_friend_request(nickname):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    receiver_nickname = session['nickname']

    with driver.session() as db_session:
        db_session.run("""
            MATCH (sender:User {nickname: $sender_nickname})-[r:FRIEND_REQUEST]->(receiver:User {nickname: $receiver_nickname})
            DELETE r
            MERGE (sender)-[:FRIEND]->(receiver)
            MERGE (receiver)-[:FRIEND]->(sender)
            WITH receiver
            MATCH (receiver)-[n:HAS_NOTIFICATION]->(notification:Notification {type: 'friend_request', sender: $sender_nickname})
            DELETE n, notification
        """, sender_nickname=nickname, receiver_nickname=receiver_nickname)

    flash(f'Friend request from {nickname} accepted.', 'success')
    return redirect(url_for('profile', nickname=receiver_nickname))

@app.route('/friends')
def friends():
    if 'nickname' not in session:
        return redirect(url_for('login'))

    nickname = session['nickname']
    friends = []

    with driver.session() as db_session:
        result = db_session.run("""
            MATCH (u:User {nickname: $nickname})-[:FRIEND]->(f:User)
            RETURN f.nickname AS nickname, f.full_name AS full_name, f.profile_picture AS profile_picture
        """, nickname=nickname)
        friends = [{"nickname": record["nickname"], "full_name": record["full_name"], "profile_picture": record["profile_picture"]} for record in result]

    return render_template('friends.html', friends=friends)

@app.route('/notifications')
def notifications():
    if 'nickname' not in session:
        return redirect(url_for('login'))

    nickname = session['nickname']
    notifications = []

    with driver.session() as db_session:
        result = db_session.run("""
            MATCH (u:User {nickname: $nickname})-[:HAS_NOTIFICATION]->(n:Notification)
            RETURN n.type AS type, n.sender AS sender, n.timestamp AS timestamp
        """, nickname=nickname)
        notifications = [{"type": record["type"], "sender": record["sender"], "timestamp": record["timestamp"]} for record in result]

    return render_template('notifications.html', notifications=notifications)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)