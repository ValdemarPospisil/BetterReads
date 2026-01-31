from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask_session import Session
from forms import RegistrationForm, LoginForm, CreateBookForm, CreateBookClubForm, EditBookClubForm
from werkzeug.security import generate_password_hash, check_password_hash
import cloudinary
import cloudinary.uploader
import cloudinary.api
from neo4j import GraphDatabase
import os
from functools import wraps
import json
from datetime import datetime
from flask_socketio import SocketIO, join_room, leave_room, send
        

app = Flask(__name__)
# Flask app setup
SECRET_KEY = 'you-will-never-guess'
USER_IMG_FOLDER = 'static/imgs/'
app.config['UPLOAD_FOLDER'] = USER_IMG_FOLDER
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)
socketio = SocketIO(app)

# Configuration       
cloudinary.config( 
    cloud_name = "dyad41msw", 
    api_key = "api-key", 
    api_secret = "api-secret",
    secure=True
)

NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"

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
            MATCH (u:User {nickname: $nickname})
            OPTIONAL MATCH (u)-[r:HAS_STATUS]->(b:Book)
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
            if record["book_name"]:
                book = {
                    "name": record["book_name"],
                    "image_url": record["image_url"]
                }
                books[record["status"]].append(book)

        if 'nickname' in session and session['nickname'] != nickname:
            friend_check = db_session.run("""
                MATCH (u:User {nickname: $user_nickname})-[:FRIEND]->(f:User {nickname: $friend_nickname})
                RETURN f
            """, user_nickname=session['nickname'], friend_nickname=nickname)
            is_friend = friend_check.single() is not None

    if 'nickname' in session and session['nickname'] == nickname:
        
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
        role = form.role.data  

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
        result = cloudinary.uploader.upload(file)
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

@app.route('/create_bValdemarPospisil/BetterReads/tree/mainook', methods=['GET', 'POST'])
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
    search_query = request.args.get('search')
    with driver.session() as db_session:
        if genre_filter and search_query:
            result = db_session.run("""
                MATCH (b:Book)<-[:WROTE]-(a:Author)
                WHERE (toLower(b.name) CONTAINS toLower($search_query) OR toLower(a.name) CONTAINS toLower($search_query) OR toLower(a.surname) CONTAINS toLower($search_query))
                AND (b)-[:BELONGS_TO]->(:Genre {name: $genre_filter})
                RETURN b.name AS book_name, a.name AS author_name, a.surname AS author_surname, b.image_url AS image_url
            """, search_query=search_query, genre_filter=genre_filter)
        elif genre_filter:
            result = db_session.run("""
                MATCH (b:Book)<-[:WROTE]-(a:Author)
                WHERE (b)-[:BELONGS_TO]->(:Genre {name: $genre_filter})
                RETURN b.name AS book_name, a.name AS author_name, a.surname AS author_surname, b.image_url AS image_url
            """, genre_filter=genre_filter)
        elif search_query:
            result = db_session.run("""
                MATCH (b:Book)<-[:WROTE]-(a:Author)
                WHERE (toLower(b.name) CONTAINS toLower($search_query) OR toLower(a.name) CONTAINS toLower($search_query) OR toLower(a.surname) CONTAINS toLower($search_query))
                RETURN b.name AS book_name, a.name AS author_name, a.surname AS author_surname, b.image_url AS image_url
            """, search_query=search_query)
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

    return render_template('list_books.html', books=books, genres=genres, selected_genre=genre_filter, search_query=search_query)

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

        # Create a notification for all friends
        friends = db_session.run("""
            MATCH (u:User {nickname: $user_nickname})-[:FRIEND]->(f:User)
            RETURN f.nickname AS friend_nickname
        """, user_nickname=user_nickname)

        for friend in friends:
            friend_nickname = friend["friend_nickname"]
            db_session.run("""
                MATCH (u:User {nickname: $user_nickname}), (f:User {nickname: $friend_nickname}), (b:Book {name: $book_name})
                CREATE (f)-[:HAS_NOTIFICATION]->(n:Notification {type: 'review', sender: $user_nickname, book_name: $book_name, rating: $rating, review_text: $review_text, timestamp: datetime()})
            """, user_nickname=user_nickname, friend_nickname=friend_nickname, book_name=book_name, rating=rating, review_text=review_text)

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
            CREATE (notification:Notification {type: 'friend_request', sender: $sender_nickname, receiver: $receiver_nickname, timestamp: datetime()})
            MERGE (receiver)-[:HAS_NOTIFICATION]->(notification)
        """, sender_nickname=sender_nickname, receiver_nickname=nickname)

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
        """, sender_nickname=nickname, receiver_nickname=receiver_nickname)

    delete_notification(receiver_nickname, 'friend_request', sender_nickname=nickname)

    flash(f'Friend request from {nickname} accepted.', 'success')
    return redirect(url_for('notifications'))

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
            RETURN n.type AS type, n.sender AS sender, n.book_name AS book_name, n.rating AS rating, n.review_text AS review_text, n.timestamp AS timestamp
        """, nickname=nickname)

        for record in result:
            notifications.append({
                "type": record["type"],
                "sender": record["sender"],
                "book_name": record["book_name"],
                "rating": record["rating"],
                "review_text": record["review_text"],
                "timestamp": record["timestamp"]
            })

    return render_template('notifications.html', notifications=notifications)

def delete_notification(user_nickname, notification_type, sender_nickname=None, book_name=None):
    with driver.session() as db_session:
        query = """
            MATCH (u:User {nickname: $user_nickname})-[n:HAS_NOTIFICATION]->(notification:Notification {type: $notification_type})
        """
        params = {"user_nickname": user_nickname, "notification_type": notification_type}

        if sender_nickname:
            query += " WHERE notification.sender = $sender_nickname"
            params["sender_nickname"] = sender_nickname

        if book_name:
            query += " AND notification.book_name = $book_name"
            params["book_name"] = book_name

        query += " DELETE n, notification"
        db_session.run(query, **params)

@app.route('/delete_notification', methods=['POST'])
def delete_notification_route():
    if 'nickname' not in session:
        return redirect(url_for('login'))

    user_nickname = session['nickname']
    sender_nickname = request.args.get('sender')
    book_name = request.args.get('book_name')
    notification_type = request.args.get('type')

    delete_notification(user_nickname, notification_type, sender_nickname=sender_nickname, book_name=book_name)

    return '', 204
        
@app.route('/create_club', methods=['GET', 'POST'])
def create_club():
    if 'nickname' not in session:
        return redirect(url_for('login'))

    form = CreateBookClubForm()

    if form.validate_on_submit():
        name = form.name.data
        short_description = form.short_description.data
        long_description = form.long_description.data
        is_private = form.is_private.data

        # Handle the image upload
        image_file = form.image.data
        image_url = upload_image(image_file)
        large_image_file = form.large_image.data
        large_image_url = upload_image(large_image_file)

        user_nickname = session['nickname']

        with driver.session() as db_session:
            db_session.run("""
                CREATE (club:BookClub {
                    name: $name,
                    short_description: $short_description,
                    long_description: $long_description,
                    image_url: $image_url,
                    large_image_url: $large_image_url,
                    is_private: $is_private,
                    owner: $user_nickname
                })
                WITH club
                MATCH (u:User {nickname: $user_nickname})
                CREATE (u)-[:MEMBER_OF]->(club)
                CREATE (u)-[:OWNER_OF]->(club)
            """, name=name, short_description=short_description, long_description=long_description, image_url=image_url, large_image_url=large_image_url, is_private=is_private, user_nickname=user_nickname)

        flash('Book club created successfully!', 'success')
        return redirect(url_for('list_clubs'))

    return render_template('create_club.html', form=form)

@app.route('/clubs')
def list_clubs():
    clubs = []
    with driver.session() as db_session:
        result = db_session.run("""
            MATCH (club:BookClub)
            OPTIONAL MATCH (club)<-[:MEMBER_OF]-(u:User)
            RETURN club.name AS name, club.short_description AS short_description, club.image_url AS image_url, count(u) AS member_count
        """)
        clubs = [{"name": record["name"], "short_description": record["short_description"], "image_url": record["image_url"], "member_count": record["member_count"]} for record in result]

    return render_template('list_clubs.html', clubs=clubs)

@app.route('/club/<club_name>')
def book_club(club_name):
    club_data = {}
    members = []
    is_member = False
    is_owner = False
    owner_nickname = None
    with driver.session() as db_session:
        result = db_session.run("""
            MATCH (club:BookClub {name: $club_name})
            OPTIONAL MATCH (club)<-[:MEMBER_OF]-(u:User)
            RETURN club.name AS name, club.short_description AS short_description, club.long_description AS long_description, 
                   club.image_url AS image_url, club.large_image_url AS large_image_url, club.is_private AS is_private, 
                   club.owner AS owner, club.topic AS topic, collect({nickname: u.nickname, full_name: u.full_name, profile_picture: u.profile_picture}) AS members
        """, club_name=club_name)
        record = result.single()
        if record:
            club_data = {
                "name": record["name"],
                "short_description": record["short_description"],
                "long_description": record["long_description"],
                "image_url": record["image_url"],
                "large_image_url": record["large_image_url"],
                "is_private": record["is_private"],
                "topic": record.get("topic", ""),  # Handle the topic field
                "members": record["members"]
            }
            owner_nickname = record["owner"]
            if 'nickname' in session:
                is_member = any(member['nickname'] == session['nickname'] for member in club_data['members'])
                is_owner = session['nickname'] == owner_nickname
        else:
            abort(404)
    return render_template('book_club.html', club=club_data, is_member=is_member, is_owner=is_owner, owner_nickname=owner_nickname)

@app.route('/join_club/<club_name>', methods=['POST'])
def join_club(club_name):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    user_nickname = session['nickname']
    answer = request.form.get('answer')

    with driver.session() as db_session:
        is_member_result = db_session.run("""
            MATCH (u:User {nickname: $user_nickname})-[:MEMBER_OF]->(club:BookClub {name: $club_name})
            RETURN u
        """, user_nickname=user_nickname, club_name=club_name)
        if is_member_result.single():
            flash('You are already a member of this club.', 'warning')
            return redirect(url_for('book_club', club_name=club_name))

        is_requested_result = db_session.run("""
            MATCH (u:User {nickname: $user_nickname})-[:REQUESTED_TO_JOIN]->(club:BookClub {name: $club_name})
            RETURN u
        """, user_nickname=user_nickname, club_name=club_name)
        if is_requested_result.single():
            flash('You have already requested to join this club.', 'warning')
            return redirect(url_for('book_club', club_name=club_name))

        result = db_session.run("""
            MATCH (club:BookClub {name: $club_name})
            RETURN club.is_private AS is_private, club.owner AS owner
        """, club_name=club_name)
        club = result.single()

        if club['is_private'] == 'private':
            # Send join request
            db_session.run("""
                MATCH (u:User {nickname: $user_nickname}), (club:BookClub {name: $club_name}), (owner:User {nickname: club.owner})
                CREATE (u)-[:REQUESTED_TO_JOIN]->(club)
                CREATE (notification:Notification {type: 'join_request', sender: $user_nickname, receiver: club.owner, timestamp: datetime()})
                MERGE (owner)-[:HAS_NOTIFICATION]->(notification)
            """, user_nickname=user_nickname, club_name=club_name)
            flash('Join request sent. The club owner will review your request.', 'success')
        else:
            # Automatically join the club
            db_session.run("""
                MATCH (u:User {nickname: $user_nickname}), (club:BookClub {name: $club_name})
                CREATE (u)-[:MEMBER_OF]->(club)
            """, user_nickname=user_nickname, club_name=club_name)
            flash('You have joined the club.', 'success')

    return redirect(url_for('book_club', club_name=club_name))

@app.route('/leave_club/<club_name>', methods=['POST'])
def leave_club(club_name):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    user_nickname = session['nickname']

    with driver.session() as db_session:
        db_session.run("""
            MATCH (u:User {nickname: $user_nickname})-[r:MEMBER_OF]->(club:BookClub {name: $club_name})
            DELETE r
        """, user_nickname=user_nickname, club_name=club_name)

    flash('You have left the club.', 'success')
    return redirect(url_for('book_club', club_name=club_name))

@app.route('/accept_join_request/<nickname>', methods=['POST'])
def accept_join_request(nickname):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    with driver.session() as db_session:
        # Find the club the user requested to join
        club_result = db_session.run("""
            MATCH (sender:User {nickname: $sender_nickname})-[r:REQUESTED_TO_JOIN]->(club:BookClub)
            RETURN club.name AS club_name
        """, sender_nickname=nickname)
        club_record = club_result.single()
        if not club_record:
            flash('Join request not found.', 'danger')
            return redirect(url_for('notifications'))

        club_name = club_record['club_name']

        # Accept the join request
        db_session.run("""
            MATCH (sender:User {nickname: $sender_nickname})-[r:REQUESTED_TO_JOIN]->(club:BookClub {name: $club_name})
            DELETE r
            CREATE (sender)-[:MEMBER_OF]->(club)
        """, sender_nickname=nickname, club_name=club_name)

    delete_notification(session['nickname'], 'join_request', sender_nickname=nickname)

    flash(f'Join request from {nickname} accepted.', 'success')
    return redirect(url_for('notifications'))

@app.route('/edit_club/<club_name>', methods=['GET', 'POST'])
def edit_club(club_name):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    user_nickname = session['nickname']

    with driver.session() as db_session:
        result = db_session.run(
            """
            MATCH (u:User {nickname: $user_nickname})-[:OWNER_OF]->(club:BookClub {name: $club_name})
            RETURN club.name AS name, club.short_description AS short_description, 
                   club.long_description AS long_description, 
                   club.image_url AS image_url, club.large_image_url AS large_image_url, 
                   club.is_private AS is_private, club.topic AS topic
            """, user_nickname=user_nickname, club_name=club_name)
        club = result.single()

        if not club:
            abort(403)

        form = EditBookClubForm()

        if form.validate_on_submit():
            short_description = form.short_description.data
            long_description = form.long_description.data
            is_private = form.is_private.data

            image = form.image.data
            large_image = form.large_image.data

            image_url = upload_image(image) if image else club['image_url']
            large_image_url = upload_image(large_image) if large_image else club['large_image_url']

            db_session.run(
                """
                MATCH (club:BookClub {name: $club_name})
                SET club.short_description = $short_description, 
                    club.long_description = $long_description, 
                    club.image_url = $image_url, 
                    club.large_image_url = $large_image_url, 
                    club.is_private = $is_private, 
                    club.topic = $topic
                """,
                club_name=club_name, short_description=short_description, 
                long_description=long_description, image_url=image_url, 
                large_image_url=large_image_url, is_private=is_private, 
                topic=form.topic.data or "")

            flash('Book club updated successfully!', 'success')
            return redirect(url_for('book_club', club_name=club_name))

        form.short_description.data = club['short_description']
        form.long_description.data = club['long_description']
        form.is_private.data = 'private' if club['is_private'] else 'public'
        form.topic.data = club['topic'] or ""

    return render_template('edit_club.html', form=form, club=club)

@app.route('/delete_club/<club_name>', methods=['POST'])
def delete_club(club_name):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    with driver.session() as db_session:
        db_session.run("MATCH (c:BookClub {name: $club_name}) DETACH DELETE c", club_name=club_name)

    flash(f'Book club {club_name} has been deleted.', 'success')
    return redirect(url_for('list_clubs'))

@app.route('/kick_member/<club_name>/<member_nickname>', methods=['POST'])
def kick_member(club_name, member_nickname):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    user_nickname = session['nickname']

    if user_nickname == member_nickname:
        flash('You cannot kick yourself out of the club.', 'danger')
        return redirect(url_for('book_club', club_name=club_name))

    with driver.session() as db_session:
        is_owner_result = db_session.run("""
            MATCH (u:User {nickname: $user_nickname})-[:OWNER_OF]->(club:BookClub {name: $club_name})
            RETURN u
        """, user_nickname=user_nickname, club_name=club_name)
        if not is_owner_result.single():
            abort(403)

        db_session.run("""
            MATCH (u:User {nickname: $member_nickname})-[r:MEMBER_OF]->(club:BookClub {name: $club_name})
            DELETE r
        """, member_nickname=member_nickname, club_name=club_name)

    flash(f'{member_nickname} has been kicked out of the club.', 'success')
    return redirect(url_for('book_club', club_name=club_name))

# Event handler for joining a group chat room
@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)
    send(f'{session["nickname"]} has joined the room.', to=room)

# Event handler for handling group messages
@socketio.on('group_message')
def handle_group_message(data):
    room = data['room']
    message = data['message'][:200]  # Limit message length to 200 characters
    timestamp = datetime.now().isoformat()
    with driver.session() as db_session:
        db_session.run("""
            MATCH (u:User {nickname: $nickname}), (c:BookClub {name: $club_name})
            CREATE (m:Message {content: $message, timestamp: $timestamp})
            CREATE (u)-[:SENT]->(m)
            CREATE (m)-[:IN]->(c)
        """, nickname=session['nickname'], club_name=room, message=message, timestamp=timestamp)
    send({'nickname': session['nickname'], 'message': message, 'timestamp': timestamp}, to=room)

@app.route('/group_chat_history/<club_name>')
def group_chat_history(club_name):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    messages = []

    with driver.session() as db_session:
        result = db_session.run("""
            MATCH (u:User)-[:SENT]->(m:Message)-[:IN]->(c:BookClub {name: $club_name})
            RETURN u.nickname AS nickname, m.content AS message, m.timestamp AS timestamp
            ORDER BY m.timestamp
        """, club_name=club_name)
        messages = [{"nickname": record["nickname"], "message": record["message"], "timestamp": record["timestamp"]} for record in result]

    return {"messages": messages}

@app.route('/chat/<friend_nickname>')
def private_chat(friend_nickname):
    if 'nickname' not in session:
        return redirect(url_for('login'))
    return render_template('private_chat.html', friend_nickname=friend_nickname)

# Event handler for joining a private chat room
@socketio.on('join_private')
def on_join_private(data):
    room = f'{session["nickname"]}_{data["friend_nickname"]}'
    join_room(room)
    send(f'{session["nickname"]} has joined the room.', to=room)

# Event handler for leaving a private chat room
@socketio.on('leave_private')
def on_leave_private(data):
    room = f'{session["nickname"]}_{data["friend_nickname"]}'
    leave_room(room)
    send(f'{session["nickname"]} has left the room.', to=room)

# Event handler for handling private messages
@socketio.on('private_message')
def handle_private_message(data):
    room = f'{session["nickname"]}_{data["friend_nickname"]}'
    message = data['message'][:200]  # Limit message length to 200 characters
    timestamp = datetime.now().isoformat()
    with driver.session() as db_session:
        db_session.run("""
            MATCH (u1:User {nickname: $nickname1}), (u2:User {nickname: $nickname2})
            CREATE (m:Message {content: $message, timestamp: $timestamp})
            CREATE (u1)-[:SENT]->(m)
            CREATE (m)-[:TO]->(u2)
        """, nickname1=session['nickname'], nickname2=data['friend_nickname'], message=message, timestamp=timestamp)
    send({'nickname': session['nickname'], 'message': message, 'timestamp': timestamp}, to=room)

@app.route('/chat_history/<friend_nickname>')
def chat_history(friend_nickname):
    if 'nickname' not in session:
        return redirect(url_for('login'))

    user_nickname = session['nickname']
    messages = []

    with driver.session() as db_session:
        result = db_session.run("""
        Call () {
        MATCH (u1:User {nickname: $user_nickname})-[:SENT]->(m:Message)-[:TO]->(u2:User {nickname: $friend_nickname})
                RETURN u1.nickname AS nickname, m.content AS message, m.timestamp AS timestamp
                UNION
                MATCH (u2:User {nickname: $friend_nickname})-[:SENT]->(m:Message)-[:TO]->(u1:User {nickname: $user_nickname})
                RETURN u2.nickname AS nickname, m.content AS message, m.timestamp AS timestamp
                
        }
        RETURN nickname, message, timestamp
        ORDER BY timestamp
        """, user_nickname=user_nickname, friend_nickname=friend_nickname)

        messages = [{"nickname": record["nickname"], "message": record["message"], "timestamp": record["timestamp"]} for record in result]

    return {"messages": messages}

@app.route('/search_results')
def search_results():
    query = request.args.get('query')
    books = []
    clubs = []
    users = []

    with driver.session() as db_session:
        # Search for books
        book_result = db_session.run("""
            MATCH (b:Book)<-[:WROTE]-(a:Author)
            WHERE toLower(b.name) CONTAINS toLower($query) OR toLower(a.name) CONTAINS toLower($query) OR toLower(a.surname) CONTAINS toLower($query)
            RETURN b.name AS book_name, a.name AS author_name, a.surname AS author_surname, b.image_url AS image_url
        """, {"query": query})
        books = [
            {
                "name": record["book_name"],
                "author": f"{record['author_name']} {record['author_surname']}",
                "image_url": record["image_url"]
            }
            for record in book_result
        ]

        # Search for book clubs
        club_result = db_session.run("""
            MATCH (c:BookClub)
            WHERE toLower(c.name) CONTAINS toLower($query) OR toLower(c.short_description) CONTAINS toLower($query)
            RETURN c.name AS club_name, c.short_description AS short_description, c.image_url AS image_url
        """, {"query": query})
        clubs = [
            {
                "name": record["club_name"],
                "short_description": record["short_description"],
                "image_url": record["image_url"]
            }
            for record in club_result
        ]

        # Search for users
        user_result = db_session.run("""
            MATCH (u:User)
            WHERE toLower(u.nickname) CONTAINS toLower($query) OR toLower(u.full_name) CONTAINS toLower($query)
            RETURN u.nickname AS nickname, u.full_name AS full_name, u.profile_picture AS profile_picture
        """, {"query": query})
        users = [
            {
                "nickname": record["nickname"],
                "full_name": record["full_name"],
                "profile_picture": record["profile_picture"]
            }
            for record in user_result
        ]

    return render_template('search_results.html', query=query, books=books, clubs=clubs, users=users)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
