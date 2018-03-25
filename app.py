__authors__ = "Jackie Cohen, Maulishree Pandey"
# An application in Flask where you can log in and create user accounts to save Gif collections
# SI 364 - W18 - HW4

# Import statements
import os
import requests
import json
from giphy_api_key import api_key
from flask import Flask, render_template, session, redirect, request, url_for, flash
from flask_script import Manager, Shell
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, FileField, PasswordField, BooleanField, SelectMultipleField, ValidationError
from wtforms.validators import Required, Length, Email, Regexp, EqualTo
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate, MigrateCommand
from werkzeug.security import generate_password_hash, check_password_hash

# Imports for login management
from flask_login import LoginManager, login_required, logout_user, login_user, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Application configurations
app = Flask(__name__)
app.debug = True
app.use_reloader = True
app.config['SECRET_KEY'] = 'hardtoguessstring'
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get('DATABASE_URL') or "postgresql://localhost/SADIESHW4db"
app.config['SQLALCHEMY_COMMIT_ON_TEARDOWN'] = True
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# App addition setups
manager = Manager(app)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
manager.add_command('db', MigrateCommand)

# Login configurations setup
login_manager = LoginManager()
login_manager.session_protection = 'strong'
login_manager.login_view = 'login'
login_manager.init_app(app) # set up login manager

####################################
######## Association Tables ########
####################################

## Association tables

#association Table between search terms and GIFs named search_gifs
search_gifs = db.Table('search_gifs', db.Column('search_id', db.Integer, db.ForeignKey('search_term.id')), db.Column('gif_id', db.Integer, db.ForeignKey('gifs.id')))


#association Table between GIFs and collections prepared by user named user_collection
user_collection = db.Table('user_collection', db.Column('user_id', db.Integer, db.ForeignKey('gifs.id')), db.Column('collection_id', db.Integer, db.ForeignKey('personalGifCollections.id')))


########################
######## Models ########
########################


## User-related Models

# Special model for users to log in
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), unique=True, index=True)
    email = db.Column(db.String(64), unique=True, index=True)
    collection = db.relationship('PersonalGifCollection', backref='User') #a one-to-many relationship for users and gif collections
    password_hash = db.Column(db.String(128))

    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)

## DB load function
## Necessary for behind the scenes login manager that comes with flask_login capabilities! Won't run without this.
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id)) # returns User object or None

# Model to store gifs
class Gif(db.Model):
    __tablename__ = 'gifs'
    id = db.Column(db.Integer, primary_key=True) # id (Integer, primary key)
    title = db.Column(db.String(128)) # title (String up to 128 characters)
    embedURL = db.Column(db.String(256)) # embedURL (String up to 256 characters)

    def __repr__(self): #__repr__ method that shows the title and the URL of the gif
        return "{}, URL: {}".format(self.title,self.embedURL)



# Model to store a personal gif collection
class PersonalGifCollection(db.Model):
    __tablename__ = "personalGifCollections"
    id = db.Column(db.Integer, primary_key=True) # id (Integer, primary key)
    name = db.Column(db.String(255)) # name (String, up to 255 characters)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id')) #one-to-many relationship with the User model (one user, many personal collections of gifs with different names)
    gifs = db.relationship('Gif', secondary=user_collection, backref=db.backref('personalGifCollections', lazy='dynamic'), lazy='dynamic') #many to many relationship with the Gif model (one gif might be in many personal collections, one personal collection could have many gifs in it).

class SearchTerm(db.Model):
    __tablename__ = 'search_term'
    id = db.Column(db.Integer, primary_key=True)# id (Integer, primary key)
    term = db.Column(db.String(32), unique=True)# term (String, up to 32 characters, unique)
    gifs = db.relationship('Gif', secondary=search_gifs, backref=db.backref('search_term', lazy='dynamic'), lazy='dynamic') #many to many relationship with gifs (a search will generate many gifs to save, and one gif could potentially appear in many searches)
    def __repr__(self):
        return "{}".format(self.term) #__repr__ method that returns the term string


########################
######## Forms #########
########################

# Provided
class RegistrationForm(FlaskForm):
    email = StringField('Email:', validators=[Required(),Length(1,64),Email()])
    username = StringField('Username:',validators=[Required(),Length(1,64),Regexp('^[A-Za-z][A-Za-z0-9_.]*$',0,'Usernames must have only letters, numbers, dots or underscores')])
    password = PasswordField('Password:',validators=[Required(),EqualTo('password2',message="Passwords must match")])
    password2 = PasswordField("Confirm Password:",validators=[Required()])
    submit = SubmitField('Register User')

    #Additional checking methods for the form
    def validate_email(self,field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError('Email already registered.')

    def validate_username(self,field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('Username already taken')

# Provided
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[Required(), Length(1,64), Email()])
    password = PasswordField('Password', validators=[Required()])
    remember_me = BooleanField('Keep me logged in')
    submit = SubmitField('Log In')

# NOTE 364: The following forms for searching for gifs and creating collections are provided and should not be edited. You SHOULD examine them so you understand what data they pass along and can investigate as you build your view functions in TODOs below.
class GifSearchForm(FlaskForm):
    search = StringField("Enter a term to search GIFs", validators=[Required()])
    submit = SubmitField('Submit')

class CollectionCreateForm(FlaskForm):
    name = StringField('Collection Name',validators=[Required()])
    gif_picks = SelectMultipleField('GIFs to include')
    submit = SubmitField("Create Collection")

########################
### Helper functions ###
########################

#makes a request to the Giphy API using the input search_string, and your api_key and returns a list of 5 gif dictionaries.
def get_gifs_from_giphy(search_string):
    """ Returns data from Giphy API with up to 5 gifs corresponding to the search input"""
    baseurl = "https://api.giphy.com/v1/gifs/search"
    params_dict = {"api_key":api_key, "q": search_string, "limit":5}
    response = requests.get(baseurl, params_dict)
    gif_list = json.loads(response.text)['data']
    return(gif_list)

# Provided
# Should return gif object or None
def get_gif_by_id(id):
    g = Gif.query.filter_by(id=id).first()
    return g

# Always returns a Gif instance
def get_or_create_gif(title, url):
    gif = Gif.query.filter_by(title=title).first()
    if gif:
        return gif
    else:
        gif = Gif(title=title, embedURL = url)
        db.session.add(gif)
        db.session.commit()
        return gif

def get_or_create_search_term(term):
    search_term = SearchTerm.query.filter_by(term=term).first()
    if search_term:
        print("Found term")
        return search_term #return the search term instance if it already exists.
    else: #If it does not exist in the database yet
        print("Adding term") #create a new SearchTerm instance
        search_term = SearchTerm(term=term)
        gif_search = get_gifs_from_giphy(term) #invoke the get_gifs_from_giphy function to get a list of gif data from Giphy
        for g in gif_search: #iterate over that list
            title = g['title']
            url = g['embed_url']
            new_gif = get_or_create_gif(title, url) #invoke get_or_create_gif for each
            search_term.gifs.append(new_gif) # append the return value from get_or_create_gif to the search term's associated gifs
        db.session.add(search_term) #added and committed to the database
        db.session.commit()
        return search_term #SearchTerm instance returned

#get or create a personal gif collection
def get_or_create_collection(name, current_user, gif_list=[]):
    gifCollection = PersonalGifCollection.query.filter_by(name=name,user_id = current_user.id).first() #Uniqueness of the gif collection should be determined by the name of the collection and the id of the logged in user
    if gifCollection:
        return gifCollection
    else: #if no such collection exists
        gifCollection = PersonalGifCollection(name=name, user_id = current_user.id, gifs = gif_list) #PersonalGifCollection instance should be created
        for g in gif_list: #each Gif in the gif_list input should be appended to it
            gifCollection.gifs.append(g)
        db.session.add(gifCollection)
        db.session.commit()
        return gifCollection



########################
#### View functions ####
########################

## Error handling routes
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


## Login-related routes - provided
@app.route('/login',methods=["GET","POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is not None and user.verify_password(form.password.data):
            login_user(user, form.remember_me.data)
            return redirect(request.args.get('next') or url_for('index'))
        flash('We cannot find this account, please register.')
    return render_template('login.html',form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out')
    return redirect(url_for('index'))

@app.route('/register',methods=["GET","POST"])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(email=form.email.data,username=form.username.data,password=form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('You can now log in!')
        return redirect(url_for('login'))
    return render_template('register.html',form=form)

@app.route('/secret')
@login_required
def secret():
    return "Only authenticated users can do this! Try to log in or contact the site admin."

# GifSearchForm can be rendered
@app.route('/', methods=['GET', 'POST'])
def index():
    form = GifSearchForm()
    if form.validate_on_submit():# If the form is submitted successfully:
        search_term = form.search.data
        term = get_or_create_search_term(search_term) # invoke get_or_create_search_term on the form input
        return redirect(url_for('search_results', search_term = search_term)) # and redirect to the function corresponding to the path  in order to see the results of the gif search

    # HINT: invoking url_for with a named argument will send additional data. e.g. url_for (functon not app route)('artist_info',artist='solange') would send the data 'solange' to a route /artist_info/<artist>
    return render_template('index.html',form=form)

# Provided
@app.route('/gifs_searched/<search_term>')
def search_results(search_term):
    term = SearchTerm.query.filter_by(term=search_term).first()
    relevant_gifs = term.gifs.all()
    return render_template('searched_gifs.html',gifs=relevant_gifs,term=term)

@app.route('/search_terms')
def search_terms():
    all_terms = SearchTerm.query.all()
    return render_template('search_terms.html', all_terms=all_terms)

# Provided
@app.route('/all_gifs')
def all_gifs():
    gifs = Gif.query.all()
    return render_template('all_gifs.html',all_gifs=gifs)

@app.route('/create_collection',methods=["GET","POST"])
@login_required
def create_collection():
    form = CollectionCreateForm()
    gifs = Gif.query.all()
    choices = [(g.id, g.title) for g in gifs]
    form.gif_picks.choices = choices
    if request.method == "POST": #If the form validates on submit
        gifs_selected = form.gif_picks.data #get the list of the gif ids that were selected from the form
        print("Gifs Selected", gifs_selected)
        gif_objects = [get_gif_by_id(int(id)) for id in gifs_selected] #Use the get_gif_by_id function to create a list of Gif objects
        print("Gifs Returned", gif_objects)
        get_or_create_collection(name=form.name.data, current_user=current_user, gif_list = gif_objects) #invoke the get_or_create_collection function
        redirect(url_for('collections', id_num = current_user)) #and redirect to the page that shows a list of all your collections.
    return render_template('create_collection.html', form=form) # If the form is not validated, this view function should simply render the create_collection.html template and send the form to the template.


@app.route('/collections',methods=["GET","POST"])
@login_required
def collections():
    collections = PersonalGifCollection.query.filter_by(user_id=current_user.id).all()
    return render_template('collections.html', collections=collections)


# Provided
@app.route('/collection/<id_num>')
def single_collection(id_num):
    id_num = int(id_num)
    collection = PersonalGifCollection.query.filter_by(id=id_num).first()
    gifs = collection.gifs.all()
    return render_template('collection.html',collection=collection, gifs=gifs)

if __name__ == '__main__':
    db.create_all()
    manager.run()
