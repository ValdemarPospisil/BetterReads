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
    return render_template('admin_dashboard.html')

@app.route('/profile/<nickname>')
def profile(nickname):
    if 'nickname' not in session or session['nickname'] != nickname:
        return redirect(url_for('login'))

    with driver.session() as db_session:
        result = db_session.run("""
            MATCH (u:User {nickname: $nickname})-[r:HAS_STATUS]->(b:Book)
            RETURN b.name AS book_name, b.image_url AS image_url, r.status AS status
        """, nickname=nickname)
        
        books = {
            "want_to_read": [],
            "reading": [],
            "read": []
        }
        
        for record in result:
            book = {
                "name": record["book_name"],
                "image_url": record["image_url"]
            }
            books[record["status"]].append(book)

    return render_template('profile.html', books=books, nickname=nickname)

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

# Route for listing books
@app.route('/books')
def list_books():
    with driver.session() as db_session:
        # Query to retrieve all books along with their authors
        result = db_session.run("""
            MATCH (b:Book)-[:WROTE]-(a:Author)
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
    return render_template('list_books.html', books=books)

@app.route('/book/<book_name>')
def book_detail(book_name):
    with driver.session() as db_session:
        result = db_session.run("""
            MATCH (b:Book {name: $book_name})-[:WROTE]-(a:Author)
            OPTIONAL MATCH (b)-[:BELONGS_TO]->(g:Genre)
            RETURN b.name AS book_name, b.description AS description, b.pages AS pages, 
                   b.datePublished AS datePublished, b.image_url AS image_url, 
                   a.name AS author_name, a.surname AS author_surname, 
                   collect(g.name) AS genres
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
                "genres": book["genres"]
            }
        else:
            abort(404)
    return render_template('book_detail.html', book=book_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)