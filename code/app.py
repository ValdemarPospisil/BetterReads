from flask import Flask, render_template, request, redirect, url_for
from neo4j import GraphDatabase
import os

# Flask app setup
SECRET_KEY = os.urandom(32)
USER_IMG_FOLDER = 'static/imgs/'
app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = USER_IMG_FOLDER
app.config['SECRET_KEY'] = SECRET_KEY

# Neo4j setup
NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "PassatGolf"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# Route for homepage
@app.route('/home')
@app.route('/index')
@app.route('/')
def index():
    return render_template('index.html')

# Function for creating author and book nodes and their relationship
def create_author_book_relationship(author_name, author_surname, book_data):
    with driver.session() as session:
        # Create Author node if not exists
        session.run("""
            MERGE (a:Author {name: $author_name, surname: $author_surname})
            """, author_name=author_name, author_surname=author_surname)

        # Create Book node
        session.run("""
            CREATE (b:Book {name: $name, description: $description, pages: $pages, datePublished: $datePublished, ISBN: $ISBN})
            """, **book_data)

        # Create WROTE relationship
        session.run("""
            MATCH (a:Author {name: $author_name, surname: $author_surname}),
                  (b:Book {name: $name})
            CREATE (a)-[:WROTE]->(b)
            """, author_name=author_name, author_surname=author_surname, name=book_data['name'])

# Route for creating a book and author via HTML form
@app.route('/create_book', methods=['GET', 'POST'])
def create_book():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        pages = request.form['pages']
        datePublished = request.form['datePublished']
        ISBN = request.form['ISBN']
        author_name = request.form['author_name']
        author_surname = request.form['author_surname']
        
        # Book data for Neo4j
        book_data = {
            "name": name,
            "description": description,
            "pages": pages,
            "datePublished": datePublished,
            "ISBN": ISBN
        }

        # Create author, book, and relationship
        create_author_book_relationship(author_name, author_surname, book_data)
        
        return redirect(url_for('index'))
    
    return render_template('create_book.html')

# Close Neo4j connection
@app.teardown_appcontext
def close_driver(exception=None):
    if driver:
        driver.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
