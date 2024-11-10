from flask import Flask, render_template
from redis import Redis
import os

SECRET_KEY = os.urandom(32)
USER_IMG_FOLDER = 'static/imgs/'
ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif'])

app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = USER_IMG_FOLDER
app.config['SECRET_KEY'] = SECRET_KEY


@app.route('/home')
@app.route('/index')
@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug = True)
