from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, SelectMultipleField, TextAreaField, IntegerField, FileField
from wtforms.validators import DataRequired, Email, EqualTo

class RegistrationForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired()])
    nickname = StringField('Nickname', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    role = SelectField('Role', choices=[('user', 'User'), ('admin', 'Admin')], validators=[DataRequired()])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    nickname = StringField('Nickname', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class CreateBookForm(FlaskForm):
    name = StringField('Book Name', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[DataRequired()])
    pages = IntegerField('Pages', validators=[DataRequired()])
    datePublished = StringField('Date Published', validators=[DataRequired()])
    author_name = StringField('Author Name', validators=[DataRequired()])
    author_surname = StringField('Author Surname', validators=[DataRequired()])
    genres = SelectMultipleField('Genres', validators=[DataRequired()])
    image = FileField('Book Image', validators=[DataRequired()])
    submit = SubmitField('Create Book')