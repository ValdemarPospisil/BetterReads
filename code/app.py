from flask import Flask, render_template, request, redirect, url_for
import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary.utils import cloudinary_url
from neo4j import GraphDatabase
import os

app = Flask(__name__)
# Flask app setup
SECRET_KEY = os.urandom(32)
USER_IMG_FOLDER = 'static/imgs/'
app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = USER_IMG_FOLDER
app.config['SECRET_KEY'] = SECRET_KEY

# Configuration       
cloudinary.config( 
    cloud_name = "dyad41msw", 
    api_key = "429495373674336", 
    api_secret = "gQK9cHKJzk83nMU2IEjyO7Efaos", # Click 'View API Keys' above to copy your API secret
    secure=True
)

# Upload an image
upload_result = cloudinary.uploader.upload("https://res.cloudinary.com/demo/image/upload/getting-started/shoes.jpg",
                                           public_id="shoes")
print(upload_result["secure_url"])


NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "PassatGolf"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

@app.route('/home')
@app.route('/index')
@app.route('/')
def index():
    return render_template('index.html')


def create_author_book_relationship(author_name, author_surname, book_data):
    """Creates a book and author node, and connects them with a relationship."""
    with driver.session() as session:
        # Create the book node
        query = """
            MERGE (author:Author {name: $author_name, surname: $author_surname})
            CREATE (book:Book {name: $name, description: $description, pages: $pages, datePublished: $datePublished, ISBN: $ISBN, image_url: $image_url})
            MERGE (author)-[:WROTE]->(book)
        """
        session.run(query, author_name=author_name, author_surname=author_surname, 
                    name=book_data["name"], description=book_data["description"], 
                    pages=book_data["pages"], datePublished=book_data["datePublished"], 
                    ISBN=book_data["ISBN"], image_url=book_data["image_url"])


def upload_image(file=None):
    """Uploads an image to Cloudinary, resizes it to 684x100, and returns the URL."""
    if file:
        upload_result = cloudinary.uploader.upload(
            file,
            transformation=[
                {"width": 684, "height": 1000, "crop": "scale"}
            ]
        )
    else:
        # Upload and resize the default image
        default_image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'default_book.jpg')
        upload_result = cloudinary.uploader.upload(
            default_image_path,
            transformation=[
                {"width": 684, "height": 1000, "crop": "scale"}
            ]
        )
    return upload_result['secure_url']


@app.route('/create_book', methods=['GET', 'POST'])
def create_book():
    if request.method == 'POST':
        # Collect form data
        name = request.form['name']
        description = request.form['description']
        pages = request.form['pages']
        datePublished = request.form['datePublished']
        ISBN = request.form['ISBN']
        author_name = request.form['author_name']
        author_surname = request.form['author_surname']
        
        # Handle the image upload
        
        image_file = request.files['image'] if 'image' in request.files and request.files['image'].filename else None
        image_url = upload_image(image_file)

        # Prepare book data
        book_data = {
            "name": name,
            "description": description,
            "pages": pages,
            "datePublished": datePublished,
            "ISBN": ISBN,
            "image_url": image_url  # Save the image URL if it was uploaded
        }

        # Create the author-book relationship in the Neo4j database
        create_author_book_relationship(author_name, author_surname, book_data)
        
        return redirect(url_for('index'))
    
    return render_template('create_book.html')


# Route for listing books
@app.route('/books')
def list_books():
    with driver.session() as session:
        # Query to retrieve all books along with their authors
        result = session.run("""
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)